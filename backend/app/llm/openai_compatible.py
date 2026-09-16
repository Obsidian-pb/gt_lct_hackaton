"""Провайдер поверх OpenAI-совместимого API.

Один и тот же класс обслуживает и внешний API, и локальную модель
(Ollama, vLLM, llama.cpp) — отличаются только base_url, ключ и имя модели.
Именно поэтому переключение контура не требует правки кода.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.llm.base import CommentReview, GeneratedScenario

logger = logging.getLogger(__name__)

REVIEW_SYSTEM_PROMPT = """\
Ты — специалист отдела контроля реагирования ГБУ «Система 112». Проверяешь \
комментарий диспетчера ДДС к статусу реагирования на карточку происшествия.

Требования к комментарию (памятка «Работа на АРМ-112»): указана причина отказа \
от реагирования, отражены сведения о передаче информации в другие службы, \
приведены уточнённые данные о происшествии и итоги работы диспетчера.

Проверь, раскрыт ли в комментарии каждый обязательный пункт. Пункт считается \
раскрытым, если смысл передан — дословного совпадения не требуется.

Верни строго JSON:
{"missing_points": ["<пункт, который не раскрыт>"], \
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
        self, *, base_url: str, api_key: str, model: str, timeout: float, name: str
    ) -> None:
        self.name = name
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, system: str, user: str) -> dict | None:
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
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
        return CommentReview(
            missing_points=[str(x) for x in data.get("missing_points", [])],
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
