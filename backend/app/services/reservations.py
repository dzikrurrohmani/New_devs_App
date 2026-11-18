from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple


async def _get_pool():
    from app.core.database_pool import db_pool

    if not db_pool.session_factory:
        await db_pool.initialize()
    return db_pool


def _revenue_result(
    property_id: str,
    tenant_id: str,
    total: Decimal,
    count: int,
    period: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(total),
        "currency": "USD",
        "count": count,
    }
    if period is not None:
        result["period"] = period
    return result


async def _query_revenue(
    property_id: str,
    tenant_id: str,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
) -> Tuple[Decimal, int]:
    if not tenant_id:
        raise ValueError("tenant_id is required to calculate revenue")

    from sqlalchemy import text

    db_pool = await _get_pool()

    if start_utc is not None and end_utc is not None:
        query = text("""
            SELECT
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(*) as reservation_count
            FROM reservations
            WHERE property_id = :property_id
              AND tenant_id = :tenant_id
              AND check_in_date >= :start_utc
              AND check_in_date < :end_utc
        """)
        params = {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start_utc": start_utc,
            "end_utc": end_utc,
        }
    else:
        query = text("""
            SELECT
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(*) as reservation_count
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
        """)
        params = {
            "property_id": property_id,
            "tenant_id": tenant_id,
        }

    async with db_pool.get_session() as session:
        result = await session.execute(query, params)
        row = result.fetchone()

    if row and row.total_revenue is not None:
        total_revenue = Decimal(str(row.total_revenue))
    else:
        total_revenue = Decimal("0.000")

    reservation_count = int(row.reservation_count) if row else 0
    return total_revenue, reservation_count


async def _get_property_timezone(property_id: str, tenant_id: str) -> Optional[str]:
    if not tenant_id:
        raise ValueError("tenant_id is required to calculate revenue")

    from sqlalchemy import text

    db_pool = await _get_pool()

    async with db_pool.get_session() as session:
        result = await session.execute(
            text("""
                SELECT timezone
                FROM properties
                WHERE id = :property_id AND tenant_id = :tenant_id
            """),
            {"property_id": property_id, "tenant_id": tenant_id},
        )
        row = result.fetchone()

    return row.timezone if row else None


async def calculate_monthly_revenue(
    property_id: str,
    tenant_id: str,
    month: int,
    year: int,
    property_timezone: Optional[str] = None,
    db_session=None,
) -> Dict[str, Any]:
    """
    Calculates revenue for a specific month using the property's local timezone
    so reservations are attributed to the month the client actually sees.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    period = {"month": month, "year": year}

    timezone_name = property_timezone
    if not timezone_name:
        timezone_name = await _get_property_timezone(property_id, tenant_id)

    if not timezone_name:
        return _revenue_result(property_id, tenant_id, Decimal("0.000"), 0, period)

    try:
        from zoneinfo import ZoneInfo

        property_tz = ZoneInfo(timezone_name)
    except Exception:
        property_tz = timezone.utc

    start_local = datetime(year, month, 1, tzinfo=property_tz)
    if month < 12:
        end_local = datetime(year, month + 1, 1, tzinfo=property_tz)
    else:
        end_local = datetime(year + 1, 1, 1, tzinfo=property_tz)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    total_revenue, reservation_count = await _query_revenue(
        property_id,
        tenant_id,
        start_utc=start_utc,
        end_utc=end_utc,
    )

    return _revenue_result(
        property_id,
        tenant_id,
        total_revenue,
        reservation_count,
        period,
    )


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates all-time revenue from the database for a tenant-owned property.
    """
    total_revenue, reservation_count = await _query_revenue(property_id, tenant_id)
    return _revenue_result(property_id, tenant_id, total_revenue, reservation_count)
