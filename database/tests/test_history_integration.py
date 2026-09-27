"""Optional PostgreSQL regression test; all sample rows are rolled back."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def _check_history(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                event_class_id = (await connection.execute(text(
                    "SELECT id FROM catalog.event_classes WHERE event_number = 1010101"
                ))).scalar_one_or_none()
                service_id = (await connection.execute(text(
                    "SELECT id FROM catalog.services WHERE code = 'MCHS'"
                ))).scalar_one_or_none()
                if event_class_id is None or service_id is None:
                    pytest.skip("The official incident classifier must be imported first")
                trainee, teacher, assignment = uuid4(), uuid4(), uuid4()
                template, exercise, revision = uuid4(), uuid4(), uuid4()
                session, card, answer, evaluation = uuid4(), uuid4(), uuid4(), uuid4()

                for user_id, name in ((trainee, "trainee"), (teacher, "teacher")):
                    await connection.execute(text(
                        "INSERT INTO auth.users (id, username, display_name) "
                        "VALUES (:id, :username, :display_name)"
                    ), {"id": user_id, "username": f"test_{user_id.hex}", "display_name": name})
                await connection.execute(text(
                    "INSERT INTO auth.user_services (user_id, service_id, assigned_by) "
                    "VALUES (:trainee, :service, :teacher)"
                ), {"trainee": trainee, "service": service_id, "teacher": teacher})
                await connection.execute(text(
                    "INSERT INTO training.assignments "
                    "(id, title, teacher_id, trainee_id, requested_card_count) "
                    "VALUES (:id, 'test', :teacher, :trainee, 1)"
                ), {"id": assignment, "teacher": teacher, "trainee": trainee})
                await connection.execute(text(
                    "INSERT INTO training.assignment_services (assignment_id, service_id) "
                    "VALUES (:assignment, :service)"
                ), {"assignment": assignment, "service": service_id})
                await connection.execute(text(
                    "INSERT INTO content.event_templates (id, event_class_id, topic) "
                    "VALUES (:id, :event_class, 'test')"
                ), {"id": template, "event_class": event_class_id})
                await connection.execute(text(
                    "INSERT INTO content.exercises (id, event_template_id, difficulty) "
                    "VALUES (:id, :template, 'easy')"
                ), {"id": exercise, "template": template})
                await connection.execute(text(
                    "INSERT INTO content.exercise_revisions "
                    "(id, exercise_id, revision_number, event_class_id, trainee_card, ethalon_payload) "
                    "VALUES (:id, :exercise, 1, :event_class, "
                    "jsonb_build_object('prompt', 'test'), jsonb_build_object('correct', true))"
                ), {"id": revision, "exercise": exercise, "event_class": event_class_id})
                await connection.execute(text(
                    "INSERT INTO training.sessions "
                    "(id, trainee_id, teacher_id, assignment_id, requested_card_count, "
                    "starting_difficulty, current_difficulty) "
                    "VALUES (:id, :trainee, :teacher, :assignment, 1, 'easy', 'easy')"
                ), {"id": session, "trainee": trainee, "teacher": teacher, "assignment": assignment})
                await connection.execute(text(
                    "INSERT INTO training.session_cards "
                    "(id, session_id, exercise_revision_id, sequence_number, difficulty_snapshot) "
                    "VALUES (:id, :session, :revision, 1, 'easy')"
                ), {"id": card, "session": session, "revision": revision})
                await connection.execute(text(
                    "INSERT INTO training.answers (id, session_card_id, payload) "
                    "VALUES (:id, :card, jsonb_build_object('answer', 'test'))"
                ), {"id": answer, "card": card})
                await connection.execute(text(
                    "INSERT INTO training.evaluations "
                    "(id, answer_id, accuracy_percent, threshold_percent, is_correct, "
                    "duration_ms, time_factor, accuracy_score, total_score, "
                    "current_difficulty, next_difficulty) "
                    "VALUES (:id, :answer, 100, 70, true, 12000, 1, 100, 100, 'easy', 'easy')"
                ), {"id": evaluation, "answer": answer})

                snapshot = (await connection.execute(text(
                    "SELECT exercise_snapshot #>> '{revision,trainee_card,prompt}' "
                    "FROM training.session_cards WHERE id = :card"
                ), {"card": card})).scalar_one()
                assert snapshot == "test"
                await connection.execute(text("DELETE FROM content.exercises WHERE id = :id"), {"id": exercise})
                await connection.execute(text("DELETE FROM auth.users WHERE id = :id"), {"id": trainee})
                row = (await connection.execute(text(
                    "SELECT s.trainee_id, s.trainee_id_snapshot, s.assignment_id, "
                    "c.exercise_revision_id, c.exercise_revision_id_snapshot, "
                    "c.exercise_snapshot #>> '{revision,trainee_card,prompt}' "
                    "FROM training.sessions AS s "
                    "JOIN training.session_cards AS c ON c.session_id = s.id "
                    "JOIN training.answers AS a ON a.session_card_id = c.id "
                    "WHERE s.id = :session"
                ), {"session": session})).one()
                assert row[0] is None and row[1] == trainee and row[2] is None
                assert row[3] is None and row[4] == revision and row[5] == "test"
                assert (await connection.execute(text(
                    "SELECT total_score FROM training.evaluations WHERE id = :id"
                ), {"id": evaluation})).scalar_one() == 100

                savepoint = await connection.begin_nested()
                with pytest.raises(Exception, match="retained permanently"):
                    await connection.execute(text(
                        "DELETE FROM training.answers WHERE id = :id"
                    ), {"id": answer})
                await savepoint.rollback()
                savepoint = await connection.begin_nested()
                with pytest.raises(Exception, match="retained permanently"):
                    await connection.execute(text(
                        "DELETE FROM training.evaluations WHERE id = :id"
                    ), {"id": evaluation})
                await savepoint.rollback()
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def test_results_survive_source_deletion() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration test")
    asyncio.run(_check_history(database_url))
