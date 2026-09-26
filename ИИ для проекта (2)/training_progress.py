"""Sequential scenario progression and automatic coaching for training mode.

There are only two learner modes:
- training: after a short idle interval the UI may request one reference-backed
  nudge from this module;
- testing: no reference-backed nudges are exposed.

The official assessment remains the teacher's responsibility.
"""
import copy
from datetime import datetime, timezone

AUTO_FIELDS = {'phone_aon', 'external_number', 'registered_by'}
EMPTY_JSON = {'[]', '{}', 'null', '""'}
DEFAULT_COACHING_DELAY = 10


def _same_assignment(session, other):
    a, b = session.get('training') or {}, other.get('training') or {}
    return bool(a.get('plan_id')) and a.get('plan_id') == b.get('plan_id') and session.get('student') == other.get('student')


def advance(engine, completed_id):
    """Activate the next queued card from the same assignment."""
    completed = engine.load(completed_id)
    training = completed.get('training') or {}
    if not training.get('plan_id'):
        return {'next_id': None, 'scenario_complete': True, 'adaptation': None}

    candidates = [s for s in engine.list_items('s') if _same_assignment(completed, s)]
    current_index = int(training.get('card_index') or 0)
    queued = sorted(
        (s for s in candidates if s.get('status') == 'queued' and int((s.get('training') or {}).get('card_index') or 0) > current_index),
        key=lambda s: int((s.get('training') or {}).get('card_index') or 0),
    )
    if not queued:
        return {'next_id': None, 'scenario_complete': True, 'adaptation': None}

    nxt = queued[0]
    nxt['status'] = 'active'
    nxt['activated_at'] = datetime.now(timezone.utc).isoformat()
    # Difficulty is no longer a learner/teacher setting. Keep the dialogue model
    # neutral and stable for legacy generators that still require a level token.
    nxt['effective_level'] = 'medium'
    engine.save(nxt)
    return {'next_id': nxt['id'], 'scenario_complete': False, 'adaptation': None}


def _is_blank(value):
    text = str(value or '').strip()
    return not text or text in EMPTY_JSON


def _reveal_candidates(session, draft):
    """Return reference fields in a human-friendly order.

    Automatic registration fields are never revealed as coaching because the
    learner does not need to discover them. Ordinary form fields come before
    classification/service technical fields.
    """
    task = session.get('task') or {}
    fields = task.get('fields') or {}
    draft = draft if isinstance(draft, dict) else session.get('card', {})
    already = {row.get('field') for row in session.get('training_reveals', []) if isinstance(row, dict)}

    normal, technical = [], []
    for key, row in fields.items():
        if key in AUTO_FIELDS or key in already or not isinstance(row, dict):
            continue
        expected = str(row.get('expected', '')).strip()
        if not expected:
            continue
        # Legacy seven-field exercises may not use the same key in the expanded
        # worksheet. In that case the field is still eligible until revealed.
        current = draft.get(key, '') if isinstance(draft, dict) else ''
        if not _is_blank(current):
            continue
        target = technical if key.startswith('_') else normal
        target.append((key, expected))
    return normal + technical


def coaching_nudge(engine, identifier, draft=None):
    """Reveal exactly one approved reference field in training mode."""
    session = engine._active(identifier)
    training = session.get('training') or {}
    if training.get('mode') != 'training':
        raise ValueError('В режиме тестирования подсказки недоступны.')

    candidates = _reveal_candidates(session, draft)
    if not candidates:
        return {'revealed': False, 'complete': True}

    key, expected = candidates[0]
    label = (session.get('task', {}).get('field_labels') or {}).get(key, key)
    reveal = {
        'field': key,
        'label': label,
        'value': expected,
        'at': datetime.now(timezone.utc).isoformat(),
        'number': len(session.get('training_reveals', [])) + 1,
    }
    session.setdefault('training_reveals', []).append(copy.deepcopy(reveal))
    session.setdefault('training', {})['last_coaching_at'] = reveal['at']
    # If the training system itself reveals the callback number, the learner may
    # enter it without first forcing the caller to repeat it.
    if key == 'phone_callback':
        session['callback_disclosed'] = True
    engine.save(session)
    return {'revealed': True, 'complete': False, 'reveal': reveal}
