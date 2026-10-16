import logging
import httpx
from fastapi import APIRouter, HTTPException, Query, status
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/geocode", tags=["geocode"])

_LOCATIONIQ_URL = "https://us1.locationiq.com/v1/reverse"


@router.get("/reverse")
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    if not settings.locationiq_api_key:
        raise HTTPException(status_code=503, detail="Geocoding not configured")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                _LOCATIONIQ_URL,
                params={
                    "key": settings.locationiq_api_key,
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "accept-language": "en",
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Geocoding timed out")
    except httpx.RequestError as e:
        logger.exception("LocationIQ request failed")
        raise HTTPException(status_code=503, detail="Geocoding unavailable")

    if response.status_code != 200:
        logger.warning("LocationIQ returned %s: %s", response.status_code, response.text[:200])
        return {"address": ""}

    data = response.json()
    return {"address": data.get("display_name", "")}