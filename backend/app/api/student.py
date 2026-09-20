"""Личный кабинет обучающегося: собственные результаты, ошибки, прогресс."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.training import Attempt
from app.models.user import Role, User
from app.services import progress as service

router = APIRouter(prefix="/api/student", tags=["Личный кабинет обучающегося"])


class ModeStatsOut(BaseModel):
    mode: str
    attempts: int
    finished: int
    average_score: float
    overdue_pickup: int


class WorkOut(BaseModel):
    attempt_id: int
    title: str
    mode: str
    finished_at: str
    score: float
    violations: int
    critical: int


class MistakeOut(BaseModel):
    code: str
    title: str
    severity: str
    criterion: str
    count: int
    share: float
    example: str


class ProgressOut(BaseModel):
    student_id: int
    student_name: str
    total: int
    finished: int
    average_score: float
    average_pickup_seconds: float | None
    overdue_pickup: int
    grammar_issues: int
    trend: float | None
    by_mode: list[ModeStatsOut]
    mistakes: list[MistakeOut]
    works: list[WorkOut]
    advice: list[str]


@router.get("/progress", response_model=ProgressOut)
def my_progress(
    student_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProgressOut:
    """Прогресс обучающегося по всем его занятиям.

    Обучающийся видит только себя: техническое задание прямо ограничивает
    его в доступе к результатам других. Преподавателю чужой прогресс
    открыт — он обязан отслеживать успеваемость. Администратору закрыт:
    это персональные данные, а его полномочия ограничены техническим
    состоянием комплекса.
    """
    target_id = user.id
    if student_id is not None and student_id != user.id:
        if user.role is not Role.TEACHER:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Доступен только собственный прогресс"
            )
        target_id = student_id

    student = db.get(User, target_id)
    if student is None or student.role is not Role.STUDENT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обучающийся не найден")

    attempts = db.scalars(
        select(Attempt).where(Attempt.student_id == target_id).order_by(Attempt.id)
    ).all()
    result = service.build(list(attempts))

    return ProgressOut(
        student_id=student.id,
        student_name=student.full_name,
        total=result.total,
        finished=result.finished,
        average_score=result.average_score,
        average_pickup_seconds=result.average_pickup_seconds,
        overdue_pickup=result.overdue_pickup,
        grammar_issues=result.grammar_issues,
        trend=result.trend,
        by_mode=[
            ModeStatsOut(
                mode=str(s.mode),
                attempts=s.attempts,
                finished=s.finished,
                average_score=s.average_score,
                overdue_pickup=s.overdue_pickup,
            )
            for s in result.by_mode
        ],
        mistakes=[MistakeOut(**vars(m)) for m in result.mistakes],
        works=[
            WorkOut(
                attempt_id=w.attempt_id,
                title=w.title,
                mode=str(w.mode),
                finished_at=w.finished_at,
                score=w.score,
                violations=w.violations,
                critical=w.critical,
            )
            for w in result.works
        ],
        advice=result.advice,
    )
