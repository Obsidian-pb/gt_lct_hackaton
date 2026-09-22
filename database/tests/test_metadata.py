from trainer_db.models import Base
from pathlib import Path


EXPECTED_TABLES = {
    "audit.audit_log",
    "auth.permissions",
    "auth.role_permissions",
    "auth.roles",
    "auth.user_roles",
    "auth.users",
    "catalog.classifier_version_events",
    "catalog.classifier_versions",
    "catalog.event_class_services",
    "catalog.event_classes",
    "catalog.event_features_1",
    "catalog.event_features_2",
    "catalog.event_features_3",
    "catalog.event_types",
    "catalog.services",
    "content.event_template_services",
    "content.event_templates",
    "content.exercise_revisions",
    "content.exercise_services",
    "content.exercises",
    "content.incident_card_details",
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


def test_event_classifier_structure_is_registered() -> None:
    event_class = Base.metadata.tables["catalog.event_classes"]
    assert {
        "event_number",
        "event_type_id",
        "event_feature_1_id",
        "event_feature_2_id",
        "event_feature_3_id",
        "main_service_id",
    } <= set(event_class.columns.keys())

    revision = Base.metadata.tables["content.exercise_revisions"]
    assert {
        "event_class_id",
        "classification_status",
        "classification_proposal",
        "additional_attributes",
        "scenario_override",
        "service_overrides",
    } <= set(revision.columns.keys())

    session = Base.metadata.tables["training.sessions"]
    assert "classifier_version_id" in session.columns.keys()


def test_incident_card_has_structured_details() -> None:
    details = Base.metadata.tables["content.incident_card_details"]
    assert {
        "exercise_revision_id",
        "registered_by_name",
        "controlled_by_name",
        "controlled_at",
        "aon_phone",
        "applicant_phone",
        "scene_phone",
        "applicant_full_name",
        "applicant_status",
        "latitude",
        "longitude",
        "incident_description",
        "vis_information",
        "control_notes",
    } <= set(details.columns.keys())

    revision_foreign_keys = {
        foreign_key.target_fullname for foreign_key in details.foreign_keys
    }
    assert revision_foreign_keys == {"content.exercise_revisions.id"}


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
    assert "CREATE FUNCTION catalog.assign_event_number" in schema_sql
    assert "CREATE FUNCTION catalog.prevent_classifier_code_change" in schema_sql
    assert "CREATE TRIGGER trg_event_classes_assign_event_number" in schema_sql
    assert "CREATE TABLE content.incident_card_details" in schema_sql
