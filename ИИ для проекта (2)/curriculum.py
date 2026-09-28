"""Shared local curriculum and role based incident handoff for the trainer.

The repository is an integration seam: the team's database can replace the
JSON repository without changing the REST resource or browser workflow.
The HTTP server serialises these operations with its existing storage lock.
"""
import copy
import json
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_core import now, require_text

ROLES = {'operator', 'dds', 'service'}
STATES = {'prepared', 'active', 'completed'}
SCENARIO_STATES = {'draft', 'approved'}
ID_PATTERN = re.compile(r'(scenario|training)-[a-f0-9]{12}$')


def _path(engine, identifier):
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        raise ValueError('Неверный идентификатор учебного ресурса.')
    root = Path(engine.directory) / 'curriculum'
    root.mkdir(parents=True, exist_ok=True)
    return root / (identifier + '.json')


def _write(engine, item):
    path = _path(engine, item['id'])
    item['updated_at'] = now()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return copy.deepcopy(item)


def get(engine, identifier):
    value = json.loads(_path(engine, identifier).read_text(encoding='utf-8'))
    if value.get('id') != identifier:
        raise ValueError('Учебный ресурс повреждён.')
    return value


def list_resources(engine, kind):
    if kind not in ('scenario', 'training'):
        raise ValueError('Неизвестный учебный ресурс.')
    root = Path(engine.directory) / 'curriculum'
    if not root.exists():
        return []
    return sorted((get(engine, p.stem) for p in root.glob(kind + '-*.json')),
                  key=lambda v: v['created_at'], reverse=True)


def _task_ids(engine, values):
    if not isinstance(values, list) or not 1 <= len(values) <= 100 or len(set(values)) != len(values):
        raise ValueError('Выберите от 1 до 100 различных учебных задач.')
    for identifier in values:
        task = engine.load(identifier)
        if not identifier.startswith('t-') or task.get('status') != 'approved':
            raise ValueError('В сценарий входят только утверждённые задачи.')
    return values


def save_scenario(engine, data, identifier=None):
    previous = get(engine, identifier) if identifier else None
    if previous and previous['status'] == 'approved':
        raise ValueError('Утверждённый сценарий зафиксирован. Создайте новый.')
    task_ids = _task_ids(engine, data.get('task_ids'))
    levels = data.get('task_difficulties') or {}
    if not isinstance(levels, dict) or set(levels) - set(task_ids) or any(type(v) is not int or not 1 <= v <= 5 for v in levels.values()):
        raise ValueError('Сложность каждой задачи: целое число от 1 до 5.')
    item = previous or {'id': 'scenario-' + uuid.uuid4().hex[:12], 'status': 'draft', 'created_at': now()}
    item.update(title=require_text(data.get('title'), 'Название сценария', 100),
                description=str(data.get('description') or '')[:2000], task_ids=task_ids,
                task_difficulties={task_id:levels.get(task_id,3) for task_id in task_ids},
                created_by=require_text(data.get('teacher'), 'Преподаватель', 160))
    return _write(engine, item)


def approve_scenario(engine, identifier, teacher):
    item = get(engine, identifier)
    if item['status'] != 'draft':
        raise ValueError('Сценарий уже утверждён.')
    _task_ids(engine, item['task_ids'])
    item.update(status='approved', approved_by=require_text(teacher, 'Преподаватель', 160), approved_at=now())
    return _write(engine, item)


def delete_scenario(engine, identifier):
    item = get(engine, identifier)
    if item['status'] != 'draft' or any(identifier in t['scenario_ids'] for t in list_resources(engine, 'training')):
        raise ValueError('Удалить можно только черновик, не включённый в тренировки.')
    _path(engine, identifier).unlink()
    return {'deleted': True}


def _participants(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError('Укажите участников тренировки.')
    participants = []
    names = set()
    for row in values:
        if not isinstance(row, dict) or row.get('role') not in ROLES:
            raise ValueError('Для каждого участника укажите учебную роль.')
        student = require_text(row.get('student'), 'Обучающийся', 160)
        if student in names:
            raise ValueError('Роль обучающегося в одной тренировке должна быть однозначной.')
        names.add(student)
        service = str(row.get('service') or '').strip()
        if row['role'] == 'service' and not service:
            raise ValueError('Диспетчеру службы назначьте службу.')
        if row['role'] == 'service':
            from card_factory import SERVICES
            if service not in SERVICES:
                raise ValueError('Код службы отсутствует в классификаторе.')
        participants.append({'student': student, 'role': row['role'], 'service': service if row['role'] == 'service' else ''})
    if not any(row['role'] == 'operator' for row in participants):
        raise ValueError('В тренировке нужен хотя бы один оператор 112.')
    if any(row['role'] == 'dds' for row in participants) and not any(row['role'] == 'service' for row in participants):
        raise ValueError('Для передачи карточек диспетчеру ДДС назначьте хотя бы одну службу.')
    return participants


def save_training(engine, data, identifier=None):
    previous = get(engine, identifier) if identifier else None
    if previous and previous['status'] != 'prepared':
        raise ValueError('Активную или завершённую тренировку менять нельзя.')
    scenarios = data.get('scenario_ids')
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 20 or len(set(scenarios)) != len(scenarios):
        raise ValueError('В тренировку входит от 1 до 20 разных сценариев.')
    for scenario_id in scenarios:
        if get(engine, scenario_id)['status'] != 'approved':
            raise ValueError('В тренировку входят только утверждённые сценарии.')
    seconds = data.get('seconds', 30)
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise ValueError('Время на карточку: от 0 до 86400 секунд.')
    mode = data.get('mode', 'training')
    if mode not in ('training', 'testing'):
        raise ValueError('Режим: обучение или тестирование.')
    item = previous or {'id': 'training-' + uuid.uuid4().hex[:12], 'status': 'prepared', 'created_at': now(), 'cards': []}
    item.update(title=require_text(data.get('title'), 'Название тренировки', 100),
                description=str(data.get('description') or '')[:2000], mode=mode, seconds=seconds,
                scenario_ids=scenarios, participants=_participants(data.get('participants')),
                teacher=require_text(data.get('teacher'), 'Преподаватель', 160),
                group=str(data.get('group') or '')[:160],
                difficulty=data.get('difficulty', 'medium'))
    if item['difficulty'] not in ('easy', 'medium', 'hard', 'adaptive'):
        raise ValueError('Неизвестная сложность тренировки.')
    return _write(engine, item)


def activate(engine, identifier):
    item = get(engine, identifier)
    if item['status'] != 'prepared':
        raise ValueError('Тренировка уже запущена или завершена.')
    tasks = list(dict.fromkeys(tid for sid in item['scenario_ids'] for tid in get(engine, sid)['task_ids']))
    task_levels = {tid: get(engine,sid).get('task_difficulties',{}).get(tid,3) for sid in item['scenario_ids'] for tid in get(engine,sid)['task_ids']}
    random.shuffle(tasks)
    target={'easy':1,'medium':3,'hard':5,'adaptive':3}[item['difficulty']]
    tasks.sort(key=lambda tid:abs(task_levels[tid]-target))
    operators = [row for row in item['participants'] if row['role'] == 'operator']
    if len(tasks) * len(operators) > 5000:
        raise ValueError('Слишком много карточек для одного запуска.')
    for operator in operators:
        for index, task_id in enumerate(tasks, 1):
            session = engine.start(task_id, operator['student'], training={
                'plan_id': item['id'], 'training_id': item['id'], 'scenario_ids': item['scenario_ids'],
                'title': item['title'], 'group': item['group'], 'teacher': item['teacher'],
                'seconds': item['seconds'], 'mode': item['mode'], 'role': 'operator',
                'difficulty': item['difficulty'], 'task_difficulty': task_levels[task_id],
                'coaching_delay_seconds': 10 if item['mode'] == 'training' else 0,
                'card_index': index, 'card_total': len(tasks)})
            session['status'] = 'awaiting_call' if index == 1 else 'queued'
            session['effective_level'] = {'easy':'easy','medium':'medium','hard':'hard','adaptive':'medium'}[item['difficulty']]
            session['activated_at'] = None
            engine.save(session)
            item['cards'].append({'id': 'card-' + uuid.uuid4().hex[:12], 'operator_session_id': session['id'],
                                  'task_id': task_id, 'student': operator['student'], 'status': 'awaiting_call',
                                  'service_actions': {}, 'services': [], 'card': None})
    item.update(status='active', started_at=now())
    return _write(engine, item)


def accept_call(engine, session):
    if session['status'] != 'awaiting_call':
        raise ValueError('Нет ожидающего входящего вызова.')
    training = session.get('training') or {}
    if training.get('training_id'):
        item = get(engine, training['training_id'])
        if item['status'] != 'active':
            raise ValueError('Тренировка не активна.')
    session.update(status='active', activated_at=now())
    engine.save(session)
    return session


def _deadline(session):
    seconds = (session.get('training') or {}).get('seconds') or 0
    if not seconds or not session.get('activated_at'):
        return None
    return datetime.fromisoformat(session['activated_at']) + timedelta(seconds=seconds)


def expire(engine, session):
    """Save the last server-side draft on timeout and move to the next call."""
    limit = _deadline(session)
    if session['status'] == 'active' and limit and datetime.now(timezone.utc) >= limit:
        session.update(status='submitted', submitted_at=now(), timed_out=True)
        from scoring import compare
        session['machine_assessment'] = compare(session)
        engine.save(session)
        on_submission(engine, session)
        from training_progress import advance
        advance(engine, session['id'])
        return True
    return False


def on_submission(engine, session):
    training_id = (session.get('training') or {}).get('training_id')
    if not training_id:
        return
    item = get(engine, training_id)
    for record in item['cards']:
        if record['operator_session_id'] == session['id']:
            if record['status'] not in ('awaiting_call', 'operator_work'):
                return
            record['card'] = copy.deepcopy(session['card'])
            has_dds = any(p['role'] == 'dds' for p in item['participants'])
            record['status'] = 'dds_review' if has_dds else 'service_review'
            record['submitted_at'] = now()
            if not has_dds:
                available = {p['service'] for p in item['participants'] if p['role'] == 'service'}
                record['services'] = [code for code in _services(session['card']) if code in available]
                if not record['services']:
                    record['status'] = 'done'
            _write(engine, item)
            return


def _services(card):
    try:
        values = json.loads(card.get('_services') or '[]')
        return list(dict.fromkeys(str(v) for v in values)) if isinstance(values, list) else []
    except (TypeError, ValueError):
        return []


def desk(engine, student):
    student = require_text(student, 'Обучающийся', 160)
    result = []
    for item in list_resources(engine, 'training'):
        participant = next((p for p in item['participants'] if p['student'] == student), None)
        if not participant:
            continue
        role, service = participant['role'], participant['service']
        cards = []
        for record in item['cards']:
            if role == 'dds' and record['status'] == 'dds_review' or role == 'service' and record['status'] == 'service_review' and service in record['services']:
                cards.append({**copy.deepcopy(record), 'field_labels': engine.load(record['operator_session_id'])['task'].get('field_labels', {})})
        result.append({'id': item['id'], 'title': item['title'], 'status': item['status'],
                       'role': role, 'service': service, 'cards': cards, 'total': len(item['cards']),
                       'completed': sum(c['status'] in ('done', 'service_review') for c in item['cards'])})
    return result


def route_card(engine, training_id, card_id, student, services, updates):
    item = get(engine, training_id)
    if item['status'] != 'active' or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants']):
        raise ValueError('Карточку может направить назначенный диспетчер ДДС.')
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not record or record['status'] != 'dds_review':
        raise ValueError('Карточка уже обработана или недоступна.')
    if not isinstance(updates, dict) or not isinstance(record['card'], dict) or any(k not in record['card'] or not isinstance(v, str) or len(v) > 3000 for k,v in updates.items()):
        raise ValueError('Некорректные исправления карточки.')
    if not isinstance(services, list) or len(services) != len(set(services)) or not services or any(not isinstance(v, str) for v in services):
        raise ValueError('Выберите службу для направления карточки.')
    available = {p['service'] for p in item['participants'] if p['role'] == 'service'}
    if not set(services) <= available:
        raise ValueError('Выбранной службы нет среди участников тренировки.')
    record['card'].update(updates)
    record.update(status='service_review', services=services, dds_by=student, routed_at=now())
    return _write(engine, item)


def service_action(engine, training_id, card_id, student, text):
    item = get(engine, training_id)
    participant = next((p for p in item['participants'] if p['student'] == student and p['role'] == 'service'), None)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not participant or not record or item['status'] != 'active' or record['status'] != 'service_review' or participant['service'] not in record['services']:
        raise ValueError('Карточка не направлена вашей службе.')
    record['service_actions'][participant['service']] = {'student': student, 'text': require_text(text, 'Действия службы', 2000), 'at': now()}
    if all(s in record['service_actions'] for s in record['services']):
        record['status'] = 'done'
    return _write(engine, item)


def complete(engine, training_id, teacher):
    item = get(engine, training_id)
    if item['status'] != 'active' or item['teacher'] != teacher:
        raise ValueError('Тренировка не активна или назначена другому преподавателю.')
    for record in item['cards']:
        s = engine.load(record['operator_session_id'])
        if s['status'] in ('active', 'awaiting_call', 'queued'):
            s.update(status='submitted', submitted_at=now(), forced_finish={'teacher': teacher, 'reason': 'Тренировка завершена', 'at': now()})
            engine.save(s)
            if record['status'] in ('awaiting_call', 'operator_work'):
                record.update(card=copy.deepcopy(s['card']), status='stopped')
    item.update(status='completed', completed_at=now())
    return _write(engine, item)


def delete_training(engine, identifier):
    item = get(engine, identifier)
    if item['status'] != 'prepared':
        raise ValueError('Удалить можно только подготовленную тренировку.')
    _path(engine, identifier).unlink()
    return {'deleted': True}
