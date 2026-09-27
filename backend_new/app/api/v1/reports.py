from __future__ import annotations

import csv
import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_session
from app.repositories.training import TrainingRepository
from app.schemas.reports import ReportSummaryOut, TrainingReportOut

router = APIRouter(prefix="/reports", tags=["reports"])
report_access = require_roles("system_admin", "admin", "teacher")


def _avg(values: list) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


@router.get("/summary", response_model=ReportSummaryOut, summary="Общая статистика (окно 16 ТЗ)")
async def summary(
    _: Annotated[object, Depends(report_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportSummaryOut:
    cards = await TrainingRepository(session).list_cards()
    submitted = [c for c in cards if c.status != "draft"]
    evaluated = [c for c in cards if c.final_score is not None]
    by_status: dict[str, int] = {}
    for card in cards:
        by_status[card.status] = by_status.get(card.status, 0) + 1
    return ReportSummaryOut(
        total_cards=len(cards),
        submitted_cards=len(submitted),
        evaluated_cards=len(evaluated),
        avg_machine_score=_avg([float(c.machine_score) for c in submitted if c.machine_score is not None]),
        avg_final_score=_avg([float(c.final_score) for c in evaluated]),
        avg_duration_ms=_avg([c.duration_ms for c in cards if c.duration_ms is not None]),
        cards_by_status=by_status,
    )


@router.get("/training/{training_id}", response_model=TrainingReportOut, summary="Отчёт по тренировке")
async def training_report(
    training_id: UUID,
    _: Annotated[object, Depends(report_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingReportOut:
    repo = TrainingRepository(session)
    training = await repo.get_training(training_id)
    if training is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Тренировка не найдена"
        )
    cards = await repo.list_cards(training_id=training_id)
    submitted = [c for c in cards if c.status != "draft"]
    evaluated = [c for c in cards if c.final_score is not None]
    sessions = await repo.list_sessions(training_id)
    participants: list[dict] = []
    for session_item in sessions:
        user_cards = [c for c in cards if c.session_id == session_item.id]
        user_submitted = [c for c in user_cards if c.status != "draft"]
        participants.append(
            {
                "user_id": str(session_item.user_id),
                "total_cards": len(user_cards),
                "submitted_cards": len(user_submitted),
                "avg_machine_score": _avg(
                    [float(c.machine_score) for c in user_submitted if c.machine_score is not None]
                ),
            }
        )
    return TrainingReportOut(
        training_id=str(training_id),
        title=training.title,
        total_cards=len(cards),
        submitted_cards=len(submitted),
        evaluated_cards=len(evaluated),
        avg_machine_score=_avg([float(c.machine_score) for c in submitted if c.machine_score is not None]),
        avg_final_score=_avg([float(c.final_score) for c in evaluated]),
        participants=participants,
    )


@router.get("/export.csv", summary="Экспорт карточек в CSV (окно 16 ТЗ)")
async def export_csv(
    _: Annotated[object, Depends(report_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
    training_id: UUID | None = None,
    user_id: UUID | None = None,
) -> StreamingResponse:
    cards = await TrainingRepository(session).list_cards(
        training_id=training_id, user_id=user_id
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "id",
            "session_id",
            "study_task_id",
            "sequence_number",
            "status",
            "machine_score",
            "ai_score",
            "final_score",
            "duration_ms",
            "created_at",
            "submitted_at",
        ]
    )
    for card in cards:
        writer.writerow(
            [
                card.id,
                card.session_id,
                card.study_task_id,
                card.sequence_number,
                card.status,
                card.machine_score,
                card.ai_score,
                card.final_score,
                card.duration_ms,
                card.created_at.isoformat() if card.created_at else "",
                card.submitted_at.isoformat() if card.submitted_at else "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cards_export.csv"},
    )