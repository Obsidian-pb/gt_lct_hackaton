from trainer_db.models import Base
from pathlib import Path


EXPECTED_TABLES = {
    "audit.audit_log",
    "auth.permissions",
    "auth.role_permissions",
    "auth.roles",
    "auth.user_roles",
    "auth.users",
    "catalog.event_classes",
    "catalog.services",
    "content.event_template_services",
    "content.event_templates",
    "content.exercise_revisions",
    "content.exercise_services",
    "content.exercises",
    "training.answers",
    "training.evaluations",
    "training.scoring_profiles",
    "training.scoring_rules",
    "training.session_cards",
    "training.sessions",
}


def test_all_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_exercise_uses_dynamic_json_documents() -> None:
    revision = Base.metadata.tables["content.exercise_revisions"]
    assert {"field_schema", "source_payload", "trainee_card", "ethalon_payload"} <= set(
        revision.columns.keys()
    )


def test_retained_entities_have_deletion_deadlines() -> None:
    retained = (
        "auth.users",
        "catalog.event_classes",
        "catalog.services",
        "content.event_templates",
        "content.exercises",
        "training.scoring_profiles",
        "training.sessions",
    )
    for table_name in retained:
        columns = Base.metadata.tables[table_name].columns
        assert "deleted_at" in columns
        assert "purge_after" in columns


def test_exported_schema_contains_database_functions() -> None:
    schema_sql = (Path(__file__).parents[1] / "schema.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE FUNCTION training.calculate_total_score" in schema_sql
    assert "CREATE FUNCTION training.next_difficulty" in schema_sql
    assert "CREATE FUNCTION audit.purge_expired_data" in schema_sql
