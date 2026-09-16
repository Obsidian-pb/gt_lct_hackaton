"""Проверка авторизации GigaChat без обращения к сети."""

import base64
import time

import pytest

from app.llm.gigachat import GigaChatProvider


def provider(**kwargs) -> GigaChatProvider:
    defaults = dict(auth_key="key==", scope="GIGACHAT_API_PERS", model="GigaChat", timeout=30.0)
    return GigaChatProvider(**{**defaults, **kwargs})


def test_готовый_ключ_остаётся_как_есть():
    assert provider(auth_key="YWJjOmRlZg==")._auth_key == "YWJjOmRlZg=="


def test_пара_client_id_и_secret_кодируется():
    """В кабинете дают base64, но пару с двоеточием копируют не реже."""
    encoded = provider(auth_key="my-client-id:my-secret")._auth_key
    assert base64.b64decode(encoded).decode() == "my-client-id:my-secret"


def test_пробелы_вокруг_ключа_срезаются():
    assert provider(auth_key="  YWJjOmRlZg==  ")._auth_key == "YWJjOmRlZg=="


def test_response_format_не_отправляется():
    """GigaChat его не поддерживает — строгий JSON обеспечивает промпт."""
    assert provider()._supports_response_format is False


@pytest.mark.asyncio
async def test_действующий_токен_не_обновляется(monkeypatch):
    p = provider()
    p._token = "живой-токен"
    p._token_expires_at = time.time() + 600

    async def fail():
        raise AssertionError("обновление токена не требовалось")

    monkeypatch.setattr(p, "_refresh_token", fail)
    assert await p._auth_headers() == {"Authorization": "Bearer живой-токен"}


@pytest.mark.asyncio
async def test_истёкший_токен_обновляется(monkeypatch):
    p = provider()
    p._token = "старый"
    p._token_expires_at = time.time() - 1
    calls = []

    async def refresh():
        calls.append(1)
        p._token = "новый"
        p._token_expires_at = time.time() + 600

    monkeypatch.setattr(p, "_refresh_token", refresh)
    assert await p._auth_headers() == {"Authorization": "Bearer новый"}
    assert len(calls) == 1
