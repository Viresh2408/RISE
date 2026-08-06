"""Reports Router."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from schemas import AutonomyReportDTO, MttrReportDTO
from apps.api.src.deps import require_role, UserContext
from apps.api.src.middleware.envelope import build_response

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])


@router.get("/mttr")
async def get_mttr_report(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    service: Optional[str] = Query(None),
    user: UserContext = Depends(require_role("viewer")),
):
    mttr = MttrReportDTO(
        avg_mttr_minutes=8.2,
        trend=[
            {"date": "2026-07-25", "mttr_minutes": 10.5},
            {"date": "2026-08-01", "mttr_minutes": 8.2},
        ],
    ).model_dump()
    return build_response(data=mttr)


@router.get("/autonomy")
async def get_autonomy_report(
    user: UserContext = Depends(require_role("viewer")),
):
    autonomy = AutonomyReportDTO(
        auto_resolved_pct=42.3,
        human_approved_pct=51.0,
        rejected_pct=6.7,
    ).model_dump()
    return build_response(data=autonomy)
