"""Личный кабинет обучающегося: собственные результаты, ошибки, прогресс."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.base import as_utc, utcnow
from app.models.training import Attempt, SessionState, TrainingSession, session_student
from app.models.user import Role, User
from app.services import progress as service
from app.services import report

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
    # Обратная связь преподавателя по этой работе — требование ТЗ о комментариях
    # к результатам. Обучающийся видит её и в разборе карточки, и здесь, чтобы
    # не открывать каждую работу в поисках, где преподаватель что-то написал.
    teacher_feedback: str | None = None
    teacher_feedback_by: str | None = None
    # Повторная выдача проваленной карточки и её итог: исправился ли.
    is_repeat: bool = False
    repeat_fixed: bool | None = None


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
    # Повторные выдачи: завершено и исправлено. В статистику выше не входят.
    repeats_finished: int = 0
    repeats_fixed: int = 0


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
                teacher_feedback=w.teacher_feedback,
                teacher_feedback_by=w.teacher_feedback_by,
                is_repeat=w.is_repeat,
                repeat_fixed=w.repeat_fixed,
            )
            for w in result.works
        ],
        advice=result.advice,
        repeats_finished=result.repeats_finished,
        repeats_fixed=result.repeats_fixed,
    )


class SessionBriefOut(BaseModel):
    """Занятие глазами обучающегося: до первого вызова — инструктаж, после
    последнего — итог. Всё, что здесь есть, обучающийся вправе знать о себе."""

    id: int
    title: str
    mode: str
    state: str
    teacher_name: str
    pickup_deadline_seconds: int
    handling_deadline_seconds: int
    call_interval_seconds: int
    pass_score: float
    max_critical_violations: int
    repeat_failed: bool
    started_at: str | None
    # Карточки этого обучающегося в занятии: всего запланировано, уже
    # поступило, завершено. Повторные выдачи входят в счёт.
    cards_total: int
    cards_issued: int
    cards_done: int
    # Через сколько секунд поступит следующая карточка; None — все уже поступили.
    next_issue_in_seconds: float | None
    # Итог по первым попыткам: средний балл, критические нарушения, зачёт.
    # passed = None, пока завершённых работ нет.
    average_score: float
    critical: int
    passed: bool | None


@router.get("/sessions", response_model=list[SessionBriefOut])
def my_sessions(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[SessionBriefOut]:
    """Занятия обучающегося: идущие первыми, затем завершённые, недавние выше.

    Только своё: обучающийся входит в состав занятия и получает в нём карточки —
    ни чужих занятий, ни чужих результатов здесь нет по построению запроса.
    """
    if user.role is not Role.STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Раздел для обучающихся")
    # Занятие «своё», если обучающийся в его составе или уже получил в нём
    # карточку: состав правится преподавателем и после запуска, а карточки —
    # факт, который не оспоришь.
    mine = or_(
        TrainingSession.id.in_(
            select(session_student.c.session_id).where(session_student.c.student_id == user.id)
        ),
        TrainingSession.id.in_(select(Attempt.session_id).where(Attempt.student_id == user.id)),
    )
    sessions = db.scalars(
        select(TrainingSession)
        .where(mine, TrainingSession.state != SessionState.DRAFT)
        .order_by(TrainingSession.started_at.desc().nullslast(), TrainingSession.id.desc())
    ).all()
    now = utcnow()
    out: list[SessionBriefOut] = []
    for session in sessions:
        attempts = [a for a in session.attempts if a.student_id == user.id]
        issued = [a for a in attempts if as_utc(a.issued_at) <= now]
        upcoming = sorted(
            (as_utc(a.issued_at) - now).total_seconds() for a in attempts if as_utc(a.issued_at) > now
        )
        summary = report.build(session, attempts)
        me = next((r for r in summary.students if r.student_id == user.id), None)
        out.append(
            SessionBriefOut(
                id=session.id,
                title=session.title,
                mode=str(session.mode),
                state=str(session.state),
                teacher_name=session.teacher.full_name,
                pickup_deadline_seconds=session.pickup_deadline_seconds,
                handling_deadline_seconds=session.handling_deadline_seconds,
                call_interval_seconds=session.call_interval_seconds,
                pass_score=session.pass_score,
                max_critical_violations=session.max_critical_violations,
                repeat_failed=session.repeat_failed,
                started_at=as_utc(session.started_at).isoformat() if session.started_at else None,
                cards_total=len(attempts),
                cards_issued=len(issued),
                cards_done=sum(1 for a in attempts if a.finished_at is not None),
                next_issue_in_seconds=round(upcoming[0], 1) if upcoming else None,
                average_score=me.average_score if me else 0.0,
                critical=me.critical if me else 0,
                passed=me.passed(session.pass_score, session.max_critical_violations) if me else None,
            )
        )
    active = [o for o in out if o.state == str(SessionState.ACTIVE)]
    finished = [o for o in out if o.state != str(SessionState.ACTIVE)]
    return active + finished
