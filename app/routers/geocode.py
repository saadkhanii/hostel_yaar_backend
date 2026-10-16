"""
Reverse-geocoding proxy.

The Flutter app never calls Nominatim directly — it goes through this
endpoint. Two reasons:

1. Nominatim's usage policy requires a meaningful User-Agent
   identifying the *application*. Flutter's HTTP client sends a generic
   one, which Nominatim rejects with 403.

2. It lets us throttle, cache, and swap providers later without a
   Flutter rebuild. If Nominatim becomes too slow or unavailable, this
   file is the only thing that changes.

Docs: https://operations.osmfoundation.org/policies/nominatim/
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException, Query, status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/geocode", tags=["geocode"])

# Nominatim requires a real identifier. Update this if you rename the
# app or change contact email.
_USER_AGENT = "HostelYaar/1.0 (contact@hostelyaar.app)"

_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"


@router.get("/reverse")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """
    Turn a (lat, lng) pair into a human-readable address string.

    Returns {"address": "..."} on success. Returns an empty address
    string if the upstream service returns no result — the Flutter
    side falls back to showing raw coordinates in that case.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                _NOMINATIM_REVERSE,
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "zoom": 18,       # building-level detail
                    "addressdetails": 0,
                },
                headers={"User-Agent": _USER_AGENT},
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Reverse geocoding timed out. Please try again.",
        )
    except httpx.RequestError as e:
        logger.exception("Nominatim request failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Reverse geocoding unavailable: {e}",
        )

    if response.status_code != 200:
        logger.warning(
            "Nominatim returned %s: %s",
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reverse geocoding is temporarily unavailable.",
        )

    data = response.json()
    return {"address": data.get("display_name", "")}