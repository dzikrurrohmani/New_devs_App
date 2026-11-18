import json
import logging
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os

logger = logging.getLogger(__name__)

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def _revenue_cache_key(
    tenant_id: str,
    property_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> str:
    """Build a tenant-scoped cache key for a revenue period."""
    if not tenant_id:
        raise ValueError("tenant_id is required to cache revenue data")

    period = f"{year:04d}-{month:02d}" if month is not None and year is not None else "all"
    return f"revenue:v2:{tenant_id}:{property_id}:{period}"


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    cache_key = _revenue_cache_key(tenant_id, property_id, month, year)

    # Try to get from cache. Cache failures must not break revenue reporting.
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.warning(f"Revenue cache read failed for {cache_key}: {exc}")

    # Revenue calculation is delegated to the reservation service.
    if month is not None and year is not None:
        from app.services.reservations import calculate_monthly_revenue

        result = await calculate_monthly_revenue(property_id, tenant_id, month, year)
    else:
        from app.services.reservations import calculate_total_revenue

        result = await calculate_total_revenue(property_id, tenant_id)

    # Cache the result for 5 minutes. A cache outage must not fail the request.
    try:
        await redis_client.setex(cache_key, 300, json.dumps(result))
    except Exception as exc:
        logger.warning(f"Revenue cache write failed for {cache_key}: {exc}")

    return result
