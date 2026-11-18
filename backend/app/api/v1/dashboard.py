import logging
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: Optional[int] = Query(default=None, ge=1, le=12),
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context is missing")

    if (month is None) != (year is None):
        raise HTTPException(
            status_code=400,
            detail="month and year must be provided together",
        )

    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, month, year)
    except Exception as exc:
        logger.exception(
            "Failed to load revenue for tenant=%s property=%s period=%s-%s: %s",
            tenant_id,
            property_id,
            year,
            month,
            exc,
        )
        raise HTTPException(status_code=503, detail="Revenue data is temporarily unavailable")

    total_revenue_float = float(
        Decimal(revenue_data['total']).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )
    )

    response = {
        "property_id": revenue_data['property_id'],
        "total_revenue": total_revenue_float,
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count'],
    }
    if "period" in revenue_data:
        response["period"] = revenue_data["period"]

    return response
