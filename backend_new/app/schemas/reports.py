from __future__ import annotations

from pydantic import BaseModel


class ReportSummaryOut(BaseModel):
    total_cards: int
    submitted_cards: int
    evaluated_cards: int
    avg_machine_score: float | None = None
    avg_final_score: float | None = None
    avg_duration_ms: float | None = None
    cards_by_status: dict[str, int] = {}


class TrainingReportOut(BaseModel):
    training_id: str
    title: str
    total_cards: int
    submitted_cards: int
    evaluated_cards: int
    avg_machine_score: float | None = None
    avg_final_score: float | None = None
    participants: list[dict] = []