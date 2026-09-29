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

ROLES = {'waiting', 'operator', 'dds', 'service'}
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
    item['updated_at'] = now()
    if getattr(engine, 'store', None) is not None:
        engine.store.save_curriculum(item)
        return copy.deepcopy(item)
    path = _path(engine, item['id'])
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    return copy.deepcopy(item)


def get(engine, identifier):
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        raise ValueError('Неверный идентификатор учебного ресурса.')
    if getattr(engine, 'store', None) is not None:
        value = engine.store.load_curriculum(identifier)
    else:
        value = json.loads(_path(engine, identifier).read_text(encoding='utf-8'))
    if value.get('id') != identifier:
        raise ValueError('Учебный ресурс повреждён.')
    return value


def list_resources(engine, kind):
    if kind not in ('scenario', 'training'):
        raise ValueError('Неизвестный учебный ресурс.')
    if getattr(engine, 'store', None) is not None:
        return engine.store.list_curriculum(kind)
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
    if getattr(engine, 'store', None) is not None:
        engine.store.delete_curriculum(identifier)
    else:
        _path(engine, identifier).unlink()
    return {'deleted': True}


def _participants(values, previous=()):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError('Допустимо не более 100 участников.')
    participants, names = [], set()
    for row in values:
        if not isinstance(row, dict) or row.get('role') not in ROLES:
            raise ValueError('Для каждого участника укажите учебную роль.')
        student = require_text(row.get('student'), 'Обучающийся', 160)
        if student.casefold() in names:
            raise ValueError('Имя участника в одной тренировке должно быть уникальным.')
        names.add(student.casefold())
        service = str(row.get('service') or '').strip()
        if row['role'] == 'service':
            from card_factory import SERVICES
            if service not in SERVICES:
                raise ValueError('Диспетчеру службы назначьте код из классификатора.')
        old = next((p for p in previous if p['student'].casefold() == student.casefold()), {})
        participants.append({'id': old.get('id') or uuid.uuid4().hex[:12], 'student':student,
            'role':row['role'], 'service':service if row['role'] == 'service' else '',
            'joined_at':old.get('joined_at') or now()})
    return participants



def _training_task_ids(engine, item):
    if item.get('task_ids'):
        return list(item['task_ids'])
    return list(dict.fromkeys(tid for sid in item['scenario_ids'] for tid in get(engine,sid)['task_ids']))


def _approved_card_categories(task):
    from card_factory import CATALOG
    groups = {row['id']: str(row.get('category') or '') for row in CATALOG}
    source = task.get('incident_source') or {}
    return set(groups.get(class_id) for class_id in source.get('class_ids', [])) - {''}


def save_training(engine, data, identifier=None):
    previous = get(engine, identifier) if identifier else None
    if previous and previous['status'] != 'prepared':
        raise ValueError('Активную или завершённую тренировку менять нельзя.')
    scenarios = data.get('scenario_ids') or []
    direct_ids = data.get('task_ids') or []
    category_ids = data.get('categories') or []
    if not all(isinstance(v,list) for v in (scenarios,direct_ids,category_ids)):
        raise ValueError('Выберите конкретные карточки, категории или утверждённые сценарии.')
    if sum(bool(v) for v in (scenarios,direct_ids,category_ids)) != 1:
        raise ValueError('Выберите один источник: карточки, категории или сценарии.')
    if scenarios:
        if not 1 <= len(scenarios) <= 20 or len(set(scenarios)) != len(scenarios):
            raise ValueError('В тренировку входит от 1 до 20 разных сценариев.')
        for scenario_id in scenarios:
            if get(engine, scenario_id)['status'] != 'approved':
                raise ValueError('В тренировку входят только утверждённые сценарии.')
        selected_ids = []
        selection_mode = 'scenarios'
    else:
        from card_factory import CATEGORIES
        if category_ids:
            if len(category_ids) > len(CATEGORIES) or len(set(category_ids)) != len(category_ids) or any(c not in CATEGORIES or c == 'mixed' for c in category_ids):
                raise ValueError('Выберите категории из классификатора.')
            selected_ids = [task['id'] for task in engine.approved_tasks() if task.get('format') == 'incident-v1' and _approved_card_categories(task).intersection(category_ids)]
            selection_mode = 'categories'
        else:
            if not 1 <= len(direct_ids) <= 100 or len(set(direct_ids)) != len(direct_ids):
                raise ValueError('Выберите от 1 до 100 разных утверждённых карточек.')
            selected_ids = direct_ids
            selection_mode = 'cards'
        if not selected_ids or len(selected_ids) > 100:
            raise ValueError('Для выбранных категорий нет утверждённых карточек или их больше 100.')
        for task_id in selected_ids:
            task = engine.load(task_id)
            if not isinstance(task_id,str) or not task_id.startswith('t-') or task.get('status') != 'approved' or task.get('format') != 'incident-v1':
                raise ValueError('Выберите только утверждённые полные карточки.')
    seconds = data.get('seconds', 30)
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise ValueError('Время на карточку: от 0 до 86400 секунд.')
    mode = data.get('mode', 'training')
    if mode not in ('training', 'practice', 'testing'):
        raise ValueError('Режим: обучение, тренировка или тестирование.')
    item = previous or {'id': 'training-' + uuid.uuid4().hex[:12], 'status': 'prepared', 'created_at': now(), 'cards': [], 'room_code': uuid.uuid4().hex[:8].upper()}
    item.update(title=require_text(data.get('title'), 'Название тренировки', 100),
                description=str(data.get('description') or '')[:2000], mode=mode, seconds=seconds,
                scenario_ids=scenarios, task_ids=selected_ids, category_ids=category_ids, selection_mode=selection_mode,
                participants=_participants(data.get('participants') or [], item.get('participants', [])),
                teacher=require_text(data.get('teacher'), 'Преподаватель', 160),
                group=str(data.get('group') or '')[:160],
                difficulty=data.get('difficulty', 'medium'))
    if item['difficulty'] not in ('easy', 'medium', 'hard', 'adaptive'):
        raise ValueError('Неизвестная сложность тренировки.')
    return _write(engine, item)


def lobby(engine, identifier):
    item = get(engine, identifier)
    if not item.get('room_code') or any(not p.get('id') for p in item.get('participants', [])):
        item['room_code'] = item.get('room_code') or uuid.uuid4().hex[:8].upper()
        item['participants'] = _participants(item.get('participants', []), item.get('participants', []))
        _write(engine, item)
    from application import briefing_meta
    tasks = _training_task_ids(engine,item)
    banner = briefing_meta(engine.load(tasks[0])) if tasks else {}
    return {key:copy.deepcopy(item[key]) for key in ('id','title','description','status','mode','room_code','participants')} | {
        'card_count':len(tasks), 'banner_key':banner.get('banner_key','')}


def find_lobby(engine, room_code):
    code = require_text(room_code, 'Код комнаты', 8).upper()
    if not re.fullmatch(r'[A-F0-9]{8}', code):
        raise ValueError('Неверный код комнаты.')
    item = next((t for t in list_resources(engine,'training') if t.get('room_code') == code), None)
    if not item or item['status'] != 'prepared':
        raise ValueError('Комната не найдена или уже закрыта.')
    return lobby(engine, item['id'])


def join_lobby(engine, identifier, student):
    item = get(engine, identifier)
    if item['status'] != 'prepared':
        raise ValueError('Комната уже закрыта.')
    student = require_text(student, 'Обучающийся', 160)
    if student.casefold() == 'обучающийся':
        raise ValueError('Введите имя и фамилию.')
    if not any(p['student'].casefold() == student.casefold() for p in item['participants']):
        item['participants'] = _participants([*item['participants'], {'student':student,'role':'waiting'}], item['participants'])
        _write(engine, item)
    return lobby(engine, identifier)



def add_participants(engine, identifier, teacher, students):
    item = get(engine, identifier)
    if item['status'] != 'prepared' or item['teacher'] != teacher:
        raise ValueError('Приглашать участников может преподаватель до запуска.')
    if not isinstance(students, list) or not 1 <= len(students) <= 20:
        raise ValueError('Добавьте от 1 до 20 обучающихся за раз.')
    clean = [require_text(name, 'Обучающийся', 160) for name in students]
    if any(name.casefold() == 'обучающийся' for name in clean) or len({name.casefold() for name in clean}) != len(clean):
        raise ValueError('Укажите разные имена и фамилии обучающихся.')
    existing = {p['student'].casefold() for p in item['participants']}
    rows = [*item['participants'], *({'student':name, 'role':'waiting'} for name in clean if name.casefold() not in existing)]
    if len(rows) != len(item['participants']):
        item['participants'] = _participants(rows, item['participants'])
        _write(engine, item)
    return lobby(engine, identifier)


def assign_role(engine, identifier, participant_id, teacher, role, service=''):
    item = get(engine, identifier)
    if item['status'] != 'prepared' or item['teacher'] != teacher:
        raise ValueError('Роли может менять преподаватель до запуска.')
    person = next((p for p in item['participants'] if p.get('id') == participant_id), None)
    if person is None:
        raise ValueError('Участник не найден.')
    if role not in ROLES:
        raise ValueError('Неизвестная роль.')
    rows = [{**p, **({'role':role, 'service':service} if p is person else {})} for p in item['participants']]
    item['participants'] = _participants(rows, item['participants'])
    _write(engine, item)
    return lobby(engine, identifier)


def remove_participant(engine, identifier, participant_id, teacher):
    item = get(engine, identifier)
    if item['status'] != 'prepared' or item['teacher'] != teacher:
        raise ValueError('Состав может менять преподаватель до запуска.')
    rows = [p for p in item['participants'] if p.get('id') != participant_id]
    if len(rows) == len(item['participants']):
        raise ValueError('Участник не найден.')
    item['participants'] = rows
    _write(engine, item)
    return lobby(engine, identifier)


def activate(engine, identifier):
    item = get(engine, identifier)
    if item['status'] != 'prepared':
        raise ValueError('Тренировка уже запущена или завершена.')
    if not any(p['role'] == 'operator' for p in item['participants']) or any(p['role'] == 'waiting' for p in item['participants']):
        raise ValueError('Перед запуском назначьте оператора и роли всем участникам.')
    tasks = _training_task_ids(engine,item)
    task_levels = {tid: get(engine,sid).get('task_difficulties',{}).get(tid,3) for sid in item['scenario_ids'] for tid in get(engine,sid)['task_ids']}
    if item.get('selection_mode') != 'cards':
        random.shuffle(tasks)
        target={'easy':1,'medium':3,'hard':5,'adaptive':3}[item['difficulty']]
        tasks.sort(key=lambda tid:abs(task_levels.get(tid,3)-target))
    operators = [row for row in item['participants'] if row['role'] == 'operator']
    if len(tasks) * len(operators) > 5000:
        raise ValueError('Слишком много карточек для одного запуска.')
    for operator in operators:
        for index, task_id in enumerate(tasks, 1):
            session = engine.start(task_id, operator['student'], training={
                'plan_id': item['id'], 'training_id': item['id'], 'scenario_ids': item['scenario_ids'],
                'title': item['title'], 'group': item['group'], 'teacher': item['teacher'],
                'seconds': item['seconds'], 'mode': item['mode'], 'role': 'operator', 'handoff_to_dds': any(p['role'] == 'dds' for p in item['participants']),
                'difficulty': item['difficulty'], 'task_difficulty': task_levels.get(task_id,3),
                'coaching_delay_seconds': 10 if item['mode'] == 'training' else 0,
                'card_index': index, 'card_total': len(tasks)})
            if session['task'].get('format') == 'incident-v1':
                # Vary the first caller turn, preserving the approved incident facts.
                session['call_intro'] = 'greeting' if int(session['id'][-1], 16) % 2 else 'report'
                if session['call_intro'] == 'greeting':
                    session['history'][0]['text'] = 'Алло, алло, это 112?'
            session['status'] = 'awaiting_call' if index == 1 else 'queued'
            session['effective_level'] = {'easy':'easy','medium':'medium','hard':'hard','adaptive':'medium'}[item['difficulty']]
            session['activated_at'] = None
            engine.save(session)
            item['cards'].append({'id': 'card-' + uuid.uuid4().hex[:12], 'operator_session_id': session['id'],
                                  'task_id': task_id, 'student': operator['student'], 'status': 'awaiting_call',
                                  'service_actions': {}, 'services': [], 'callback_turns': [], 'card': None})
    item.update(status='active', started_at=now())
    return _write(engine, item)


def accept_call(engine, session):
    legacy_waiting = (session['status'] == 'active' and session['task'].get('workflow', 'caller') == 'caller'
                      and len(session.get('history', [])) == 1 and not session.get('activated_at')
                      and not session.get('call_answered_at'))
    if session['status'] != 'awaiting_call' and not legacy_waiting:
        raise ValueError('Нет ожидающего входящего вызова.')
    if legacy_waiting and session['task'].get('format') == 'incident-v1' and not session.get('call_intro'):
        session['call_intro'] = 'greeting' if int(session['id'][-1], 16) % 2 else 'report'
        if session['call_intro'] == 'greeting':
            session['history'][0]['text'] = 'Алло, алло, это 112?'
    training = session.get('training') or {}
    if training.get('training_id'):
        item = get(engine, training['training_id'])
        if item['status'] != 'active':
            raise ValueError('Тренировка не активна.')
    session.update(status='active', activated_at=now(), call_answered_at=now())
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


def _callback_number(card):
    return (card.get('phone_callback') or card.get('phone_aon') or '').strip()


def _phone_digits(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Введите номер телефона из карточки.')
    digits = re.sub(r'\D', '', value)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    return digits


def _dds_call_record(item, card_id, student):
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if (item['status'] != 'active' or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants'])
            or not record or record['status'] != 'dds_review'):
        raise ValueError('Обратный звонок доступен только назначенному диспетчеру 112 при проверке карточки.')
    return record


def dial_callback(engine, training_id, card_id, student, number):
    item = get(engine, training_id)
    record = _dds_call_record(item, card_id, student)
    expected = _phone_digits(_callback_number(record['card']))
    dialed = _phone_digits(number)
    if len(expected) < 7:
        raise ValueError('В карточке нет номера для обратного звонка.')
    if dialed != expected:
        raise ValueError('Номер не совпадает с номером обратного звонка в карточке. Проверьте цифры.')
    active = record.get('callback_call') or {}
    if active.get('status') == 'active':
        if active.get('number') == expected:
            return copy.deepcopy(active)
        raise ValueError('Завершите текущий учебный звонок.')
    call = {'id': uuid.uuid4().hex[:12], 'number': expected, 'status': 'active',
            'started_at': now(), 'student': student}
    record['callback_call'] = call
    _write(engine, item)
    return copy.deepcopy(call)


def hangup_callback(engine, training_id, card_id, student, call_id):
    item = get(engine, training_id)
    record = _dds_call_record(item, card_id, student)
    call = record.get('callback_call') or {}
    if call.get('id') != call_id or call.get('status') != 'active':
        raise ValueError('Этот звонок уже завершён или недоступен.')
    call.update(status='ended', ended_at=now())
    _write(engine, item)
    return copy.deepcopy(call)



def _demo_phone(exclude=''):
    """Return a deliberately fictional Russian-format number for training only."""
    while True:
        digits = f"{uuid.uuid4().int % 10_000_000:07d}"
        phone = f"+7 (000) {digits[:3]}-{digits[3:5]}-{digits[5:]}"
        if phone != exclude:
            return phone


def generate_dispatcher_examples(engine, training_id, student, count=4, topic='', location='Учебный город'):
    """Generate reference-quality demo cards directly into a DDS trainee inbox.

    This is a self-practice path for hackathon/demo use.  It never creates a fake
    operator learner/session and never exposes the hidden AI source to the browser.
    """
    item = get(engine, training_id)
    student = require_text(student, 'Обучающийся', 160)
    if item['status'] != 'active' or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants']):
        raise ValueError('ИИ-примеры может создавать только назначенный Диспетчер 112 в активной тренировке.')
    if type(count) is not int or not 1 <= count <= 4:
        raise ValueError('За один раз можно создать от 1 до 4 ИИ-примеров.')
    if not isinstance(topic, str) or len(topic) > 1000:
        raise ValueError('Описание примеров: не более 1000 символов.')
    if not isinstance(location, str) or not location.strip() or len(location) > 160:
        raise ValueError('Локация: от 1 до 160 символов.')
    existing = sum(1 for c in item.get('cards', []) if c.get('ai_demo') and c.get('generated_for') == student)
    if existing + count > 20:
        raise ValueError('Для одной тренировки доступно не более 20 ИИ-примеров на диспетчера.')

    import card_factory
    import incident_training
    osm_index, _ = card_factory.osm_addresses()
    # The dispatcher demo uses the same local OSM city as the card workshop.
    location = f"{osm_index['city']}, {osm_index['region']}"

    # Four visibly different common groups make a stronger dispatcher demo than
    # four neighbouring classifier entries from one section.
    preferred_categories = ['1', '2', '22', '13']
    generated = []
    recent_titles = []
    for index in range(1, count + 1):
        category = preferred_categories[(existing + index - 1) % len(preferred_categories)]
        options = [row for row in card_factory.CATALOG if str(row.get('category')) == category]
        if not options:
            options = card_factory.CATALOG
        selected = random.choice(options)
        result = card_factory.generate(engine.provider, {
            'topic': topic or 'Реалистичный вымышленный учебный пример для отработки работы Диспетчера 112.',
            'category': 'mixed',
            'classification': {'id': selected['id']},
            'location': location.strip(),
            'osm_address_id': 'auto',
            'index': index,
            'total': count,
            'recent_titles': recent_titles[-10:],
        })
        content = copy.deepcopy(result['content'])
        aon = _demo_phone()
        callback_phone = _demo_phone(aon)
        content['fields']['phone_aon'] = aon
        # The callback phone stays server-owned for the dialogue service, but the
        # incoming reference card legitimately contains it as an operator handoff.
        content['fields']['phone_callback'] = callback_phone
        scenario = {'version': 1, 'phone_callback': callback_phone}

        card = {key: '' for key in incident_training.LABELS}
        card.update(copy.deepcopy(content['fields']))
        card.update(
            external_number='AI-' + uuid.uuid4().hex[:10].upper(),
            registered_by='ИИ · эталонный оператор',
            _report=content['report'],
            _class_ids=json.dumps(content['class_ids'], ensure_ascii=False),
            _services=json.dumps(content['services'], ensure_ascii=False),
            _main_service=content['main_service'],
            _flags=json.dumps(content.get('flags', {}), ensure_ascii=False),
        )
        at = now()
        record = {
            'id': 'card-' + uuid.uuid4().hex[:12],
            'operator_session_id': None,
            'task_id': None,
            'student': 'ИИ · эталонный оператор',
            'status': 'dds_review',
            'service_actions': {},
            'services': [],
            'callback_turns': [],
            'card': card,
            'submitted_at': at,
            'ai_demo': True,
            'generated_for': student,
            'ai_title': content['title'],
            'voice_id': 'ru_RU-irina-medium',
            '_incident_source': content,
            '_caller_scenario': scenario,
            '_field_labels': copy.deepcopy(incident_training.LABELS),
        }
        generated.append(record)
        recent_titles.append(content['title'])

    # Commit only after all AI calls have succeeded so a transient model failure
    # does not leave the dispatcher with a half-created batch.
    item.setdefault('cards', []).extend(generated)
    _write(engine, item)
    return {
        'training_id': item['id'],
        'created': len(generated),
        'card_ids': [row['id'] for row in generated],
        'message': f'Создано ИИ-карточек: {len(generated)}. Они добавлены в очередь Диспетчера 112.',
    }

def desk(engine, student):
    student = require_text(student, 'Обучающийся', 160)
    result = []
    for item in list_resources(engine, 'training'):
        participant = next((p for p in item['participants'] if p['student'] == student), None)
        if not participant:
            continue
        role, service = participant['role'], participant['service']
        cards = []
        routed_cards = []
        for record in item['cards']:
            pending = role == 'dds' and record['status'] == 'dds_review'
            routed = role == 'dds' and record.get('dds_by') == student and record.get('routed_at')
            if pending or routed or role == 'service' and record['status'] == 'service_review' and service in record['services']:
                public = copy.deepcopy(record)
                if record.get('ai_demo'):
                    labels = copy.deepcopy(record.get('_field_labels', {}))
                    voice_id = record.get('voice_id', 'ru_RU-irina-medium')
                else:
                    task = engine.load(record['operator_session_id'])['task']
                    import incident_training
                    labels = incident_training.LABELS | task.get('field_labels', {})
                    voice_id = task.get('voice_id', 'ru_RU-irina-medium')
                # Hidden truth used by the callback AI must never be projected to the learner browser.
                public.pop('_incident_source', None)
                public.pop('_caller_scenario', None)
                public.pop('_field_labels', None)
                public['field_labels'] = labels
                public['voice_id'] = voice_id
                (routed_cards if routed else cards).append(public)
        result.append({'id': item['id'], 'title': item['title'], 'status': item['status'],
                       'role': role, 'service': service, 'cards': cards, 'routed_cards': routed_cards, 'total': len(item['cards']),
                       'completed': sum(c['status'] in ('done', 'service_review') for c in item['cards'])})
    return result


def route_card(engine, training_id, card_id, student, services, updates, main_service=''):
    item = get(engine, training_id)
    if item['status'] != 'active' or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants']):
        raise ValueError('Карточку может направить назначенный диспетчер ДДС.')
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not record or record['status'] != 'dds_review':
        raise ValueError('Карточка уже обработана или недоступна.')
    protected = {'phone_aon', 'external_number', 'registered_by', '_services', '_main_service'}
    if not isinstance(updates, dict) or not isinstance(record['card'], dict) or any(k not in record['card'] or k in protected or not isinstance(v, str) or len(v) > 3000 for k,v in updates.items()):
        raise ValueError('Некорректные исправления карточки.')
    if not isinstance(services, list) or len(services) != len(set(services)) or not services or any(not isinstance(v, str) for v in services):
        raise ValueError('Выберите службу для направления карточки.')
    from card_factory import SERVICES
    if not set(services) <= set(SERVICES):
        raise ValueError('Неизвестная служба.')
    if main_service and main_service not in services:
        raise ValueError('Главная служба должна входить в выбранный состав.')
    record['card'].update(updates)
    record['card']['_services'] = json.dumps(services, ensure_ascii=False)
    record['card']['_main_service'] = main_service or services[0]
    if record.get('callback_call', {}).get('status') == 'active':
        record['callback_call'].update(status='ended', ended_at=now())
    staffed = {p['service'] for p in item['participants'] if p['role'] == 'service'}
    record.update(status='service_review' if staffed.intersection(services) else 'done', services=services, dds_by=student, routed_at=now(),
                  dds_senior_calls={code: {'status': 'ringing'} for code in services})
    return _write(engine, item)


def answer_dds_senior_call(engine, training_id, card_id, student, service):
    item = get(engine, training_id)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if (not record or item['status'] != 'active' or record.get('dds_by') != student
            or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants'])
            or service not in record.get('services', [])):
        raise ValueError('Вызов старшего службы недоступен этому диспетчеру.')
    call = record.setdefault('dds_senior_calls', {}).setdefault(service, {'status': 'ringing'})
    if call['status'] != 'answered':
        call.update(status='answered', answered_at=now())
        _write(engine, item)
    return copy.deepcopy(call)


def dds_service_route(engine, training_id, card_id, student, service):
    item = get(engine, training_id)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if (not record or item['status'] != 'active' or record.get('dds_by') != student
            or not any(p['student'] == student and p['role'] == 'dds' for p in item['participants'])
            or service not in record.get('services', []) or
            record.get('dds_senior_calls', {}).get(service, {}).get('status') != 'answered'):
        raise ValueError('Маршрут доступен после ответа на вызов старшего направленной службы.')
    from dispatch_route import route
    return route(record['card'], service)


def open_service_card(engine, training_id, card_id, student):
    item = get(engine, training_id)
    participant = next((p for p in item['participants'] if p['student'] == student and p['role'] == 'service'), None)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not participant or not record or item['status'] != 'active' or record['status'] != 'service_review' or participant['service'] not in record['services']:
        raise ValueError('Карточка не направлена вашей службе.')
    detail = record.setdefault('service_progress', {}).setdefault(participant['service'], {})
    if not detail.get('opened_at'):
        detail['opened_at'] = now()
        detail['open_late'] = (datetime.fromisoformat(detail['opened_at']) -
                               datetime.fromisoformat(record['routed_at'])).total_seconds() > 30
        _write(engine, item)
    return copy.deepcopy(detail)


def answer_senior_call(engine, training_id, card_id, student):
    item = get(engine, training_id)
    participant = next((p for p in item['participants'] if p['student'] == student and p['role'] == 'service'), None)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not participant or not record or participant['service'] not in record['services']:
        raise ValueError('Карточка не направлена вашей службе.')
    detail = record.get('service_progress', {}).get(participant['service'], {})
    if not detail.get('first_entry_at'):
        raise ValueError('Сначала внесите первую запись.')
    if not detail.get('call_answered_at'):
        detail['call_answered_at'] = now()
        _write(engine, item)
    return copy.deepcopy(detail)



def service_route(engine, training_id, card_id, student):
    item = get(engine, training_id)
    participant = next((p for p in item['participants'] if p['student'] == student and p['role'] == 'service'), None)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not participant or not record or participant['service'] not in record['services']:
        raise ValueError('Маршрут доступен только назначенной службе.')
    if not record.get('service_progress', {}).get(participant['service'], {}).get('first_entry_at'):
        raise ValueError('Сначала внесите первую запись.')
    from dispatch_route import route
    return route(record['card'], participant['service'])


def service_action(engine, training_id, card_id, student, text, status=None):
    item = get(engine, training_id)
    participant = next((p for p in item['participants'] if p['student'] == student and p['role'] == 'service'), None)
    record = next((c for c in item['cards'] if c['id'] == card_id), None)
    if not participant or not record or item['status'] != 'active' or record['status'] != 'service_review' or participant['service'] not in record['services']:
        raise ValueError('Карточка не направлена вашей службе.')
    text = require_text(text, 'Действия службы', 2000)
    detail = record.get('service_progress', {}).get(participant['service'], {})
    if detail.get('first_entry_at') and not detail.get('call_answered_at') and status is None:
        raise ValueError('Сначала ответьте на входящий вызов старшего службы.')
    if status is not None:
        if status not in ('accepted', 'dispatched', 'on_scene'):
            raise ValueError('Выберите статус записи.')
        detail = record.setdefault('service_progress', {}).setdefault(participant['service'], {})
        if not detail.get('opened_at'):
            raise ValueError('Сначала откройте поступившую карточку.')
        entry = {'student': student, 'status': status, 'text': text, 'at': now()}
        detail.setdefault('entries', []).append(entry)
        if not detail.get('first_entry_at'):
            detail['first_entry_at'] = entry['at']
            detail['first_entry_late'] = (datetime.fromisoformat(entry['at']) -
                                          datetime.fromisoformat(detail['opened_at'])).total_seconds() > 180
        if not detail.get('call_answered_at'):
            return _write(engine, item)
    record['service_actions'][participant['service']] = {'student': student, 'text': text, 'at': now()}
    staffed = {p['service'] for p in item['participants'] if p['role'] == 'service'}
    if all(s in record['service_actions'] for s in record['services'] if s in staffed):
        record['status'] = 'done'
    return _write(engine, item)


def callback(engine, training_id, card_id, student, question, source='text', call_id=None, lock=None):
    from contextlib import nullcontext
    from dialogue_gateway import ask
    if source not in ('text', 'voice'):
        raise ValueError('Неизвестный источник вопроса.')
    question = require_text(question, 'Вопрос заявителю', 2000)
    guard = lock or nullcontext()
    with guard:
        item = get(engine, training_id)
        record = next((c for c in item['cards'] if c['id'] == card_id), None)
        record = _dds_call_record(item, card_id, student)
        call = record.get('callback_call') or {}
        if call.get('status') != 'active' or call.get('id') != call_id or call.get('number') != _phone_digits(_callback_number(record['card'])):
            raise ValueError('Сначала наберите номер обратного звонка из карточки и дождитесь соединения.')
        if record.get('ai_demo'):
            content = copy.deepcopy(record.get('_incident_source'))
            scenario = copy.deepcopy(record.get('_caller_scenario'))
            turns = copy.deepcopy(record.get('callback_turns', []))
        else:
            original = engine.load(record['operator_session_id'])
            content = copy.deepcopy(original['task']['incident_source'])
            scenario = copy.deepcopy(original['task']['caller_scenario'])
            turns = [{'role':h['role'], 'text':h['text']} for h in original.get('history', [])[1:] if h.get('role') in ('dispatcher','caller')]
            turns += copy.deepcopy(record.get('callback_turns', []))
        if len(turns) % 2:
            turns = turns[:-1]
        snapshot = len(record.get('callback_turns', []))
        card = copy.deepcopy(record['card'])
    result = ask(content=content, caller_scenario=scenario,
                 question=question, turns=turns, student_fields=card)
    with guard:
        item = get(engine, training_id)
        record = next((c for c in item['cards'] if c['id'] == card_id), None)
        if (not record or record['status'] != 'dds_review' or len(record.get('callback_turns', [])) != snapshot
                or record.get('callback_call', {}).get('status') != 'active' or record['callback_call'].get('id') != call_id
                or record['callback_call'].get('number') != _phone_digits(_callback_number(record['card']))):
            raise ValueError('Звонок завершён или карточка изменилась во время ответа. Обновите её.')
        at = now()
        record.setdefault('callback_turns', []).extend([
            {'role':'dispatcher','text':question,'call_id':call_id,'at':at},
            {'role':'caller','text':result['reply'],'call_id':call_id,'at':now()},
        ])
        record['callback_at'] = now()
        _write(engine,item)
        return {'reply':result['reply'], 'turns':copy.deepcopy(record['callback_turns'])}


def complete(engine, training_id, teacher):
    item = get(engine, training_id)
    if item['status'] != 'active' or item['teacher'] != teacher:
        raise ValueError('Тренировка не активна или назначена другому преподавателю.')
    for record in item['cards']:
        if not record.get('operator_session_id'):
            if record.get('ai_demo') and record['status'] == 'dds_review':
                record['status'] = 'stopped'
            continue
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
    if getattr(engine, 'store', None) is not None:
        engine.store.delete_curriculum(identifier)
    else:
        _path(engine, identifier).unlink()
    return {'deleted': True}
