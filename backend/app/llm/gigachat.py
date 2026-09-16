"""Провайдер GigaChat (Сбер).

Тело запроса `/chat/completions` совместимо с OpenAI, поэтому промпты и разбор
ответа берутся из базового провайдера. Отличий три:

  * авторизация — OAuth: ключ обменивается на токен, который живёт около
    30 минут и требует обновления;
  * цепочка TLS подписана НУЦ Минцифры, и без его корневого сертификата
    проверка не проходит;
  * `response_format` не поддерживается, строгий JSON обеспечивается
    промптом и устойчивым разбором ответа.
"""

from __future__ import annotations

import base64
import logging
import time
import uuid

import httpx

from app.llm.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_BASE = "https://gigachat.devices.sberbank.ru/api/v1"

# Токен обновляется заранее, чтобы запрос не ушёл с истекающим ключом.
TOKEN_LEEWAY_SECONDS = 60


class GigaChatProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        auth_key: str,
        scope: str,
        model: str,
        timeout: float,
        base_url: str = API_BASE,
        verify: bool | str = True,
        name: str = "gigachat",
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key="",
            model=model,
            timeout=timeout,
            name=name,
            supports_response_format=False,
            verify=verify,
        )
        self._auth_key = self._normalize_auth_key(auth_key)
        self._scope = scope
        self._verify = verify
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @staticmethod
    def _normalize_auth_key(auth_key: str) -> str:
        """Принимает и готовый ключ авторизации, и пару client_id:client_secret.

        В личном кабинете выдают base64-строку, но пользователи часто копируют
        именно пару с двоеточием — поддерживаем оба варианта.
        """
        key = auth_key.strip()
        if ":" in key and not key.endswith("="):
            return base64.b64encode(key.encode("utf-8")).decode("ascii")
        return key

    async def _auth_headers(self) -> dict[str, str]:
        if self._token is None or time.time() >= self._token_expires_at:
            await self._refresh_token()
        return {"Authorization": f"Bearer {self._token}"}

    async def _refresh_token(self) -> None:
        async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
            response = await client.post(
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {self._auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": self._scope},
            )
            response.raise_for_status()
            data = response.json()

        self._token = data["access_token"]
        # expires_at приходит в миллисекундах эпохи.
        self._token_expires_at = data["expires_at"] / 1000 - TOKEN_LEEWAY_SECONDS
        logger.info("Получен токен GigaChat, действителен до %s", self._token_expires_at)
