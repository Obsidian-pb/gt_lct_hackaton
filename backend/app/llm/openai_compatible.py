"""Провайдер поверх OpenAI-совместимого API.

Один и тот же класс обслуживает и внешний API, и локальную модель
(Ollama, vLLM, llama.cpp) — отличаются только base_url, ключ и имя модели.
Именно поэтому переключение контура не требует правки кода.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from urllib.parse import urlparse

import httpx

from app.llm.base import CommentReview, GeneratedScenario

logger = logging.getLogger(__name__)


def _parse_json(content: str) -> dict:
    """Разбирает ответ модели.

    Модель часто оборачивает JSON в markdown-блок, несмотря на требование
    response_format, поэтому сначала снимаем обрамление и берём объект
    от первой открывающей скобки до последней закрывающей.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _is_local(base_url: str) -> bool:
    """Локальный ли адрес модели.

    К локальной модели нельзя ходить через HTTP_PROXY из окружения: прокси
    не знает про loopback и возвращает ошибку. К внешнему API, наоборот,
    прокси может быть единственным маршрутом, поэтому там окружение уважаем.
    """
    host = urlparse(base_url).hostname or ""
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


REVIEW_SYSTEM_PROMPT = """\
Ты — специалист отдела контроля реагирования ГБУ «Система 112». Проверяешь \
комментарий диспетчера ДДС к статусу реагирования на карточку происшествия.

Проверь, раскрыт ли в комментарии каждый обязательный пункт. Пункт считается \
раскрытым, если сведения из него прямо сообщены — дословного совпадения \
не требуется, достаточно передать смысл своими словами.

Пункт НЕ считается раскрытым, если комментарий лишь подразумевает его косвенно. \
Отказ от реагирования не заменяет сведений: «не обслуживаем» не сообщает, кто \
обслуживает, и не сообщает, куда передана информация.

В missing_points перечисли нераскрытые пункты ДОСЛОВНО в той формулировке, \
в которой они даны. Не переформулируй их и не добавляй своих. Раскрытые пункты \
в ответ не включай.

Верни строго JSON:
{"missing_points": ["<нераскрытый пункт дословно>"], \
"grammar_issues": ["<орфографическая или грамматическая ошибка>"], \
"summary": "<одно предложение для обучающегося>"}"""

SCENARIO_SYSTEM_PROMPT = """\
Ты формируешь учебный сценарий для тренажёра диспетчера ДДС города Москвы.
Придумай правдоподобное происшествие указанного типа: краткое описание, \
московский адрес, заявителя и обязательные пункты комментария.

Верни строго JSON:
{"incident_description": "", "address": "", "caller": "", "signs": [], \
"expected_primary_status": "Принята|Не принята", "required_comment_points": []}"""


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        name: str,
        disable_thinking: bool = False,
        supports_response_format: bool = True,
        verify: bool | str = True,
    ) -> None:
        self.name = name
        self._model = model
        self._disable_thinking = disable_thinking
        self._supports_response_format = supports_response_format
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            trust_env=not _is_local(base_url),
            verify=verify,
        )

    async def _auth_headers(self) -> dict[str, str]:
        """Заголовки авторизации на каждый запрос.

        Базовая реализация ничего не добавляет: ключ задан один раз при
        создании клиента. Провайдерам с истекающими токенами нужно обновление,
        поэтому они переопределяют этот метод.
        """
        return {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, system: str, user: str) -> dict | None:
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if self._supports_response_format:
            payload["response_format"] = {"type": "json_object"}
        if self._disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        try:
            response = await self._client.post(
                "/chat/completions", json=payload, headers=await self._auth_headers()
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_json(content or "")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # Недоступность LLM не должна ронять занятие: детерминированная
            # часть оценки уже посчитана и будет показана обучающемуся.
            logger.warning("Провайдер %s недоступен: %s", self.name, exc)
            return None

    async def review_comment(
        self, *, comment: str, required_points: list[str], context: str
    ) -> CommentReview:
        points = "\n".join(f"- {p}" for p in required_points) or "- (нет)"
        user = (
            f"Происшествие: {context}\n\n"
            f"Обязательные пункты:\n{points}\n\n"
            f"Комментарий диспетчера:\n{comment or '(пусто)'}"
        )
        data = await self._complete(REVIEW_SYSTEM_PROMPT, user)
        if data is None:
            return CommentReview(available=False)

        # Модель иногда возвращает собственные формулировки вместо переданных
        # пунктов. Засчитываем только то, что есть в исходном списке, — иначе
        # обучающийся получит замечание о пункте, которого ему не задавали.
        allowed = {p.strip(): p for p in required_points}
        missing = [
            allowed[str(x).strip()]
            for x in data.get("missing_points", [])
            if str(x).strip() in allowed
        ]
        return CommentReview(
            missing_points=missing,
            grammar_issues=[str(x) for x in data.get("grammar_issues", [])],
            summary=str(data.get("summary", "")),
        )

    async def generate_scenario(
        self, *, incident_type: str, group: str, difficulty: str
    ) -> GeneratedScenario:
        user = (
            f"Группа происшествий: {group}\n"
            f"Итоговый тип происшествия: {incident_type}\n"
            f"Сложность: {difficulty}"
        )
        data = await self._complete(SCENARIO_SYSTEM_PROMPT, user) or {}
        return GeneratedScenario(
            incident_description=str(data.get("incident_description", incident_type)),
            address=str(data.get("address", "")),
            caller=str(data.get("caller", "")),
            signs=[str(x) for x in data.get("signs", [])],
            expected_primary_status=str(data.get("expected_primary_status", "Принята")),
            required_comment_points=[str(x) for x in data.get("required_comment_points", [])],
        )
