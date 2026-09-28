"""Transparent preliminary machine comparison of approved reference fields.

Only a teacher can make the final decision. A deterministic string comparison
cannot judge semantically equivalent free text, so it is reported separately.
"""
import json
import re
from ai_core import now

IGNORED = {'phone_aon', 'external_number', 'registered_by'}


def _normal(value):
    text = str(value or '').strip().casefold().replace('ё', 'е')
    if text[:1] in ('[', '{'):
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True)
        except (ValueError, TypeError):
            pass
    return re.sub(r'\s+', ' ', text)


def compare(session):
    card = session.get('card') or {}
    details = {}
    points = maximum = 0
    for key, reference in (session['task'].get('fields') or {}).items():
        expected = _normal(reference.get('expected'))
        if key in IGNORED or not expected:
            continue
        value = _normal(card.get(key))
        weight = max(1, min(10, int(reference.get('weight') or 1)))
        verdict = 'correct' if value == expected else 'missing' if not value else 'different'
        details[key] = {'verdict': verdict, 'weight': weight}
        maximum += weight
        if verdict == 'correct':
            points += weight
    return {'percent': round(100 * points / maximum) if maximum else 0,
            'compared': len(details), 'fields': details, 'at': now(),
            'method': 'Точное сравнение нормализованных значений; смысл текста проверяет преподаватель.'}


def ai_percent(session):
    assessment = session.get('assessment')
    if not assessment:
        return None
    weights = session['task'].get('fields') or {}
    scores = {'correct': 1, 'partial': .5, 'incorrect': 0, 'missing': 0, 'unavailable': None}
    total = weight = 0
    for key, row in assessment.get('fields', {}).items():
        factor = scores.get(row['verdict'])
        if factor is None:
            continue
        w = max(1, min(10, int((weights.get(key) or {}).get('weight') or 1)))
        total += w * factor
        weight += w
    return round(100 * total / weight) if weight else None
