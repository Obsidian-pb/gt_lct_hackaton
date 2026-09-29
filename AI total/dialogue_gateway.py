"""Trusted gateway between the training application and dedicated AI REST service."""
from __future__ import annotations

import copy
import re

import ai_rest_client
from card_factory import LABELS, validate_content
from card_caller import validate_scenario

PROMPT_VERSION = 'dedicated-ai-rest-gateway-v1'
LEARNER_EXTRA = {'_report', '_class_ids', '_services', '_main_service', '_flags'}
LEARNER_FIELDS = frozenset(LABELS) | LEARNER_EXTRA


def _phone_key(value):
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 11 and digits[:1] in {'7', '8'}:
        return digits[-10:]
    if len(digits) == 10:
        return digits
    return digits


def _reply_discloses_phone(reply, phone):
    wanted = _phone_key(phone)
    if not wanted:
        return False
    for match in re.findall(r'(?:\+?\d[\s()+.\-]*){7,}', reply):
        if _phone_key(match) == wanted:
            return True
    return False


def _trusted_card(content, scenario):
    card = copy.deepcopy(validate_content(content))
    scenario = validate_scenario(scenario)
    # The callback number is teacher-owned scenario data.  It is added only on
    # the trusted backend and therefore never needs to be present in the learner
    # browser projection.
    card['fields']['phone_callback'] = scenario['phone_callback']
    return card, scenario


def _validate_turns(turns):
    turns = turns or []
    if (not isinstance(turns, list) or len(turns) > 100 or len(turns) % 2 or
            any(not isinstance(t, dict) or set(t) != {'role', 'text'} or
                t['role'] != ('dispatcher' if i % 2 == 0 else 'caller') or
                not isinstance(t['text'], str) or not t['text'].strip() or len(t['text']) > 2000
                for i, t in enumerate(turns))):
        raise ValueError('Неверная история разговора или достигнут предел 50 вопросов.')
    if len(turns) >= 100:
        raise ValueError('Достигнут предел 50 вопросов. Начните разговор заново.')
    return copy.deepcopy(turns)


def _validate_student_fields(value):
    if value is None:
        return {}
    if (not isinstance(value, dict) or len(value) > len(LEARNER_FIELDS) or
            any(k not in LEARNER_FIELDS or not isinstance(v, str) or len(v) > 3000 for k, v in value.items())):
        raise ValueError('Проверьте текущие поля обучающегося.')
    return copy.deepcopy(value)


def ask(*, content, caller_scenario, question, turns=None, student_fields=None):
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError('Введите вопрос заявителю (до 2000 символов).')
    card, scenario = _trusted_card(content, caller_scenario)
    result = ai_rest_client.caller_reply(
        card=card,
        student_fields=_validate_student_fields(student_fields),
        turns=_validate_turns(turns),
        question=question.strip(),
    )
    return {
        'reply': result['reply'],
        'callback_disclosed': _reply_discloses_phone(result['reply'], scenario['phone_callback']),
        'prompt_version': PROMPT_VERSION,
    }
