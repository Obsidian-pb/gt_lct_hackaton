"""Провайдер поверх OpenAI-совместимого API.

Один и тот же класс обслуживает и внешний API, и локальную модель
(Ollama, vLLM, llama.cpp) — отличаются только base_url, ключ и имя модели.
Именно поэтому переключение контура не требует правки кода.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
from urllib.parse import urlparse

import httpx

from app.llm.base import CommentReview, GeneratedScenario

logger = logging.getLogger(__name__)

# Повторы при ограничении частоты обращений: провайдер просит подождать,
# а не отказывает окончательно.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.5


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


def _as_text_list(value: object) -> list[str]:
    """Приводит список из ответа модели к строкам.

    Модель нередко возвращает вместо строк объекты вида
    {"text": "...", "number": 1}. Без разбора они превращались бы
    в мусорные строки с фигурными скобками.
    """
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("text") or item.get("point") or item.get("value") or ""
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _is_local(base_url: str) -> bool:
    """Локальный ли адрес модели.

    К локальной модели нельзя ходить через HTTP_PROXY из окружения: прокси
    не знает про loopback и возвращает ошибку. К внешнему API, наоборот,
    прокси может быть единственным маршрутом, поэтому там окружение уважаем.
    """
    host = urlparse(base_url).hostname or ""
    if host in {"localhost", "host.docker.internal"}:
        return True
    # Имя без точки — сервис из той же сети compose (`llm`, `backend`):
    # такое имя разрешает только внутренний DNS Docker, снаружи его нет,
    # и прокси о нём тем более не знает.
    if "." not in host:
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
Ты готовишь учебный сценарий для тренажёра диспетчера дежурно-диспетчерской \
службы города Москвы.

Как устроено обучение. Диспетчеру ДДС поступает карточка происшествия из \
системы-112. Он обязан в течение 30 секунд проставить статус реагирования — \
«Принята», если происшествие в зоне ответственности его службы, либо \
«Не принята», если нет, — и сопроводить статус комментарием.

Комментарий — это ТЕКСТ, который диспетчер пишет в карточку. В нём должны быть \
СВЕДЕНИЯ: причина отказа от реагирования, сведения о передаче информации в \
другую службу, уточнённые данные о происшествии, итоги работы.

required_comment_points — это факты, которые обязаны прозвучать в тексте \
комментария. Это НЕ действия диспетчера и НЕ вопросы заявителю.

  Правильно: «лифты в доме обслуживает подрядная организация «Практика»»,
             «информация передана в диспетчерскую «Практика»»,
             «на месте работает аварийная бригада, прибыла в 14:20».
  Неправильно: «Запросить информацию о пострадавших» — это действие;
               «Определить модель лифта» — это действие;
               «уточнённые данные о происшествии» — обобщение, его нельзя
               проверить в тексте; напиши сами данные.

Каждый пункт — конкретное проверяемое утверждение об этом происшествии. \
Если пишешь про причину, назови саму причину. Если про передачу информации — \
назови, кому передана. Пунктов должно быть два или три.

ВАЖНО: комментарий пишет сама служба обучающегося, от своего лица. Поэтому \
пункт «информация передана в <служба обучающегося>» бессмысленен — она не \
передаёт сведения сама себе. Если происшествие для неё непрофильное, укажи \
в пунктах другую службу, в чьей зоне ответственности происшествие находится.

Адреса делай разнообразными и настоящими для Москвы: разные округа, улицы, \
номера домов, подъезды. Заявителя не выдумывай — его подставят отдельно, \
оставь поле caller пустым.

Верни строго JSON, все элементы списков — строки:
{"incident_description": "<что произошло, 1-2 предложения>",
 "address": "<московский адрес>",
 "caller": "<ФИО, телефон>",
 "signs": ["<признак происшествия>"],
 "expected_primary_status": "Принята" или "Не принята",
 "is_profile": true или false,
 "required_comment_points": ["<факт, который обязан быть в комментарии>"]}"""


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

    async def probe(self) -> str:
        """Проверка связи: самый дешёвый запрос, какой понимает модель.

        Именно `/chat/completions`, а не `/models`: список моделей отдают
        не все локальные серверы, и он не показал бы главного — принят ли
        ключ и существует ли модель с указанным именем. Ошибки наружу
        не глушатся намеренно, их разбирает вызывающий.
        """
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            headers=await self._auth_headers(),
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("model") or self._model)

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

        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = await self._client.post(
                    "/chat/completions", json=payload, headers=await self._auth_headers()
                )
                # Ограничение частоты — не отказ: провайдер просит подождать.
                if response.status_code == 429 and attempt < RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_BASE_DELAY * 2**attempt)
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return _parse_json(content or "")
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                if attempt < RETRY_ATTEMPTS - 1 and isinstance(exc, httpx.TransportError):
                    await asyncio.sleep(RETRY_BASE_DELAY * 2**attempt)
                    continue
                # Недоступность модели не должна ронять занятие: детерминированная
                # часть оценки уже посчитана и будет показана обучающемуся.
                logger.warning("Провайдер %s недоступен: %s", self.name, exc)
                return None
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
        self,
        *,
        incident_type: str,
        group: str,
        difficulty: str,
        service: str = "дежурно-диспетчерская служба района",
        signs: list[str] | None = None,
        note: str | None = None,
        is_profile: bool | None = None,
        other_services: list[str] | None = None,
    ) -> GeneratedScenario:
        lines = [
            f"Служба обучающегося: {service}",
            f"Группа происшествий: {group}",
            f"Итоговый тип происшествия: {incident_type}",
        ]
        if signs:
            lines.append("Признаки происшествия по классификатору: " + ", ".join(signs))
        if is_profile is not None:
            lines.append(
                "Происшествие профильное для службы обучающегося, ожидается «Принята»."
                if is_profile
                else "Происшествие НЕ профильное для службы обучающегося, ожидается "
                "«Не принята» с указанием, куда передана информация."
            )
        if other_services:
            # Реальный список оповещения из ЕКП: чтобы модель называла
            # существующие службы, а не выдумывала их.
            lines.append(
                "По классификатору на это происшествие реагируют: "
                + ", ".join(other_services[:8])
            )
        lines.append(f"Сложность: {difficulty}")
        if note:
            # Замечание преподавателя к ранее сформированному сценарию —
            # сценарий «Коррекция» из технического задания.
            lines.append(f"\nЗамечание преподавателя, учти его: {note}")

        data = await self._complete(SCENARIO_SYSTEM_PROMPT, "\n".join(lines))
        if data is None:
            return GeneratedScenario.unavailable(incident_type)
        status = str(data.get("expected_primary_status") or "Принята").strip()
        if status not in {"Принята", "Не принята"}:
            status = "Принята"
        return GeneratedScenario(
            incident_description=str(data.get("incident_description") or incident_type),
            address=str(data.get("address") or ""),
            caller=str(data.get("caller") or ""),
            signs=_as_text_list(data.get("signs")),
            expected_primary_status=status,
            is_profile=bool(data.get("is_profile", status == "Принята")),
            required_comment_points=_as_text_list(data.get("required_comment_points")),
        )
