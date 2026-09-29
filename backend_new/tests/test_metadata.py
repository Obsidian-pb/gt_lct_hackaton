"""Проверка полноты модели данных: все 32 таблицы зарегистрированы в метаданных."""

from app import models  # noqa: F401
from app.db.base import Base

EXPECTED_TABLES = {
    "auth": {"users", "roles", "permissions", "user_roles", "role_permissions"},
    "catalog": {
        "classifier_versions",
        "classifier_version_events",
        "event_types",
        "event_features_1",
        "event_features_2",
        "event_features_3",
        "event_classes",
        "event_class_services",
        "event_class_extra_fields",
        "services",
    },
    "reference": {"scenario_statuses", "applicant_statuses", "training_roles"},
    "content": {
        "study_tasks",
        "task_etalons",
        "study_task_services",
        "scenarios",
        "scenario_tasks",
        "study_materials",
    },
    "training": {
        "trainings",
        "training_scenarios",
        "training_participants",
        "training_sessions",
        "incident_cards",
        "card_services",
    },
    "audit": {"audit_log"},
    "system": {"system_settings"},
}


def test_all_expected_tables_registered() -> None:
    actual: dict[str, set[str]] = {}
    for table in Base.metadata.tables.values():
        actual.setdefault(table.schema or "", set()).add(table.name)
    for schema, tables in EXPECTED_TABLES.items():
        assert tables <= actual.get(schema, set()), (
            f"Схема {schema}: отсутствуют таблицы {tables - actual.get(schema, set())}"
        )


def test_soft_delete_columns_present() -> None:
    """Сущности с мягким удалением должны иметь deleted_at и purge_after."""
    for name in (
        "auth.users",
        "catalog.services",
        "catalog.event_classes",
        "content.study_tasks",
        "content.scenarios",
        "content.study_materials",
        "training.trainings",
    ):
        table = Base.metadata.tables[name]
        assert "deleted_at" in table.c, f"{name}: нет deleted_at"
        assert "purge_after" in table.c, f"{name}: нет purge_after"