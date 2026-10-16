import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import BookingType, Hostel, Room
from app.schemas import (
    AiSearchFilters,
    AiSearchRequest,
    AiSearchResponse,
    HostelSummary,
)
from app.utils.deps import get_current_user
from sqlalchemy import and_, or_

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


_SYSTEM_PROMPT = """You are a filter extractor for a hostel-listing app in Pakistan.

Given a user's free-text description of what they want, extract structured filters
and return them as JSON. Output ONLY valid JSON — no prose, no markdown.

JSON schema you must return:
{
  "city": string or null,           // e.g. "Lahore", "Karachi"
  "min_price": integer or null,     // monthly rent lower bound in PKR
  "max_price": integer or null,     // monthly rent upper bound in PKR
  "facilities": [string],           // subset of: "WiFi", "Meals", "Laundry",
                                    // "Generator", "Parking", "CCTV", "Kitchen",
                                    // "Refrigerator", "Water Cooler"
  "type": "Boys" or "Girls" or "Mixed" or null,
  "booking_type": "Room" or "Seat" or null,
  "room_type": integer or null,     // seater count 1-6: "single"=1, "double"=2,
                                    // "triple"=3, "N seater"=N
  "explanation": string             // one short sentence summarizing what you understood,
                                    // starting with "Looking for"
}

Rules:
- Interpret "k" as thousands. "15k" = 15000. "under 20" when talking about rent means 20000.
- If the user says "my own room" or "whole room" or "complete room", booking_type = "Room".
- If they say "seat", "bed", "shared", "per seat", booking_type = "Seat".
- "girls only" or "for girls" -> type = "Girls". Same for Boys. Otherwise Mixed or null.
- For room_type: "single" = 1, "double" = 2, "triple" = 3, "4 seater" = 4, etc.
  Only set room_type if the user explicitly mentions a seater count or one of those words.
  If they just say "room" without a number, leave room_type null.
- If a field is not mentioned, use null (or [] for facilities).
- Never invent facilities the user didn't mention.
- Never invent a city if the user didn't name one.
"""


# ── Gemini client ───────────────────────────────────────────────────────
# Lazy-initialized so a missing key doesn't crash the app at import time —
# it just makes /ai/search return 503 until the key is set.

_genai_client: genai.Client | None = None


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is not None:
        return _genai_client
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI search is not configured (missing GEMINI_API_KEY)",
        )
    _genai_client = genai.Client(api_key=settings.gemini_api_key)
    return _genai_client


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "nullable": True},
        "min_price": {"type": "integer", "nullable": True},
        "max_price": {"type": "integer", "nullable": True},
        "facilities": {
            "type": "array",
            "items": {"type": "string"},
        },
        "type": {
            "type": "string",
            "enum": ["Boys", "Girls", "Mixed"],
            "nullable": True,
        },
        "booking_type": {
            "type": "string",
            "enum": ["Room", "Seat"],
            "nullable": True,
        },
        "room_type": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "maximum": 6,
        },
        "explanation": {"type": "string"},
    },
    "required": ["explanation"],
}


def _call_llm(query: str) -> dict[str, Any]:
    """Send the query to Gemini and return the parsed JSON dict."""
    client = _get_genai_client()

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=query,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                temperature=0.1,
                max_output_tokens=500,
            ),
        )
    except Exception as e:
        logger.exception("Gemini call failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {e}",
        )

    raw = (response.text or "{}").strip()

    # Gemini sometimes wraps JSON in a markdown fence even in JSON mode.
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Gemini returned non-JSON: %s", raw[:200])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an unparseable response",
        )


# ── Filter application ──────────────────────────────────────────────────

def _apply_filters(db: Session, filters: AiSearchFilters) -> list[Hostel]:
    q = db.query(Hostel).filter(Hostel.active.is_(True))

    if filters.city:
        q = q.filter(Hostel.city.ilike(f"%{filters.city}%"))

    if filters.type:
        q = q.filter(Hostel.type == filters.type)

    if filters.facilities:
        q = q.filter(Hostel.facilities.contains(filters.facilities))

    if (
        filters.max_price is not None
        or filters.min_price is not None
        or filters.booking_type is not None
        or filters.room_type is not None
    ):
        q = q.join(Room, Room.hostel_id == Hostel.id)

        if filters.booking_type:
            q = q.filter(Room.booking_type == filters.booking_type)

        if filters.room_type is not None:
            q = q.filter(Room.room_type == filters.room_type)

        if filters.max_price is not None:
            q = q.filter(Room.price <= filters.max_price)

        if filters.min_price is not None:
            q = q.filter(Room.price >= filters.min_price)

        # NEW — only count rooms that are actually available.
        # Whole rooms: vacant = true. Per-seat: available_seats > 0.
        availability_clause = or_(
            and_(
                Room.booking_type == BookingType.room,
                Room.vacant.is_(True),
            ),
            and_(
                Room.booking_type == BookingType.seat,
                Room.available_seats > 0,
            ),
        )
        q = q.filter(availability_clause)

        q = q.distinct()

    return q.limit(50).all()


def _to_summary(hostel: Hostel) -> HostelSummary:
    """Same shape as GET /hostels returns. Computed from rooms."""
    rooms = hostel.rooms or []
    prices = [r.price for r in rooms if r.price and r.price > 0]
    starting_price = min(prices) if prices else 0

    has_vacancy = any(
        (r.booking_type == BookingType.room and r.vacant)
        or (r.booking_type == BookingType.seat and (r.available_seats or 0) > 0)
        for r in rooms
    )

    return HostelSummary(
        id=hostel.id,
        warden_id=hostel.warden_id,
        name=hostel.name,
        city=hostel.city,
        address=hostel.address,
        type=hostel.type,
        latitude=hostel.latitude,
        longitude=hostel.longitude,
        facilities=hostel.facilities or [],
        photos=hostel.photos or [],
        phone=hostel.phone,
        whatsapp=hostel.whatsapp,
        in_app_chat=hostel.in_app_chat,
        active=hostel.active,
        starting_price=starting_price,
        has_vacancy=has_vacancy,
        room_count=len(rooms),
        created_at=hostel.created_at,
        updated_at=hostel.updated_at,
    )


# ── Endpoint ────────────────────────────────────────────────────────────

@router.post("/search", response_model=AiSearchResponse)
def ai_search(
    payload: AiSearchRequest,
    db: Session = Depends(get_db),
    _current_user: dict = Depends(get_current_user),
):
    """
    Free-text hostel search. Extracts filters via Gemini, applies them,
    and returns matching hostel summaries plus a one-line explanation.
    """
    data = _call_llm(payload.query)

    try:
        filters = AiSearchFilters(**data)
    except Exception as e:
        logger.warning("Invalid AI filter payload: %s (%s)", data, e)
        filters = AiSearchFilters()

    hostels = _apply_filters(db, filters)

    explanation = (
        data.get("explanation") or "Here are hostels that match your needs."
    )

    return AiSearchResponse(
        filters=filters,
        explanation=explanation,
        hostels=[_to_summary(h) for h in hostels],
    )