"""Контрактные тесты OpenAPI: защищают от случайной поломки API-контракта
при изменении БД или рефакторинге. Не требуют подключения к БД.

Запуск из каталога backend_new: pytest
"""

from app.main import app

REQUIRED_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/me",
    "/api/v1/users",
    "/api/v1/study-tasks",
    "/api/v1/scenarios",
    "/api/v1/trainings",
    "/api/v1/sessions/start",
    "/api/v1/cards",
    "/api/v1/reports/summary",
    "/api/v1/materials",
    "/api/v1/system/health",
    "/api/v1/audit",
}


def test_openapi_paths_contract() -> None:
    schema = app.openapi()
    paths = set(schema["paths"].keys())
    missing = REQUIRED_PATHS - paths
    assert not missing, f"Отсутствуют обязательные маршруты: {sorted(missing)}"


def test_auth_schemes_present() -> None:
    schema = app.openapi()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert any("bearer" in s.get("scheme", "") for s in schemes.values()), schemes
    security = schema["paths"]["/api/v1/users"].get("get", {}).get("security", [])
    assert security, "Защищённый маршрут /users должен требовать авторизацию"


def test_responses_have_models() -> None:
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        for operation in methods.values():
            responses = operation.get("responses", {})
            assert responses, f"Маршрут {path} не имеет описания ответов"