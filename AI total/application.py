"""Transport-independent application operations and student/teacher projections."""
import json
from pathlib import Path
import re
from datetime import datetime
from ai_core import FIELDS, LEVELS, VERDICTS, validate_task, require_text
from schemas import obj, TEXT
from dds import WORKFLOWS, ACTION_LABELS
import card_factory
import card_reference
import card_caller
import dialogue_gateway
import ai_rest_client
import teacher_portal
import incident_training
import piper_tts
import training_progress
import curriculum
import materials
import auth_service
import catalog_service

ROOT = Path(__file__).resolve().parent

BANNER_DIR = ROOT / 'ui' / 'banners'
BANNER_FILES = {path.stem: path.name for path in BANNER_DIR.glob('*.png')}
_CLASS_BY_ID = {row['id']: row for row in card_factory.CATALOG}
_BANNER_MAP_PATH = ROOT / 'ui' / 'banners' / 'banner-map.json'


def _task_class_ids(task):
    source = task.get('incident_source') or {}
    ids = source.get('class_ids') if isinstance(source, dict) else None
    if isinstance(ids, list) and ids:
        return [str(value) for value in ids if str(value) in _CLASS_BY_ID]
    row = (task.get('fields') or {}).get('_class_ids') or {}
    raw = row.get('expected') or row.get('truth') if isinstance(row, dict) else ''
    if isinstance(raw, str) and raw:
        try:
            values = json.loads(raw)
            if isinstance(values, list):
                return [str(value) for value in values if str(value) in _CLASS_BY_ID]
        except (ValueError, TypeError):
            pass
    return []


def _banner_map():
    """Load editable classifier-to-banner bindings without hard-coding every photo in React."""
    try:
        data = json.loads(_BANNER_MAP_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _norm_text(value):
    value = str(value or '').lower().replace('ё', 'е')
    return re.sub(r'\s+', ' ', value).strip()


def _mapped_banner(row, mapping):
    title = _norm_text(row.get('title') or row.get('ekp_type') or '')
    group = _norm_text(row.get('group') or '')
    exact = mapping.get('class_ids') if isinstance(mapping.get('class_ids'), dict) else {}
    title_keywords = mapping.get('title_keywords') if isinstance(mapping.get('title_keywords'), dict) else {}
    group_keywords = mapping.get('group_keywords') if isinstance(mapping.get('group_keywords'), dict) else {}
    categories = mapping.get('categories') if isinstance(mapping.get('categories'), dict) else {}

    class_id = str(row.get('id') or '')
    if class_id in exact:
        return exact[class_id]
    for needle, banner in sorted(title_keywords.items(), key=lambda item: len(_norm_text(item[0])), reverse=True):
        if _norm_text(needle) and _norm_text(needle) in title:
            return banner
    for needle, banner in sorted(group_keywords.items(), key=lambda item: len(_norm_text(item[0])), reverse=True):
        if _norm_text(needle) and _norm_text(needle) in group:
            return banner
    category_banner = categories.get(str(row.get('category', '')))
    if category_banner:
        return category_banner
    return None


def _legacy_banner_for_row(row):
    category = str(row.get('category', ''))
    text = ' '.join(str(row.get(key, '')) for key in
                    ('group', 'statistical_group', 'sign1', 'sign2', 'sign3', 'extra_signs', 'title', 'ekp_type')).lower()
    if category == '2' and 'пострадав' in text:
        return 'road-injured'
    if category == '13':
        return 'gas-leak'
    if category == '17':
        return 'person-danger'
    if category == '1' and any(word in text for word in ('производств', 'цех', 'завод', 'промышлен', 'производственно-склад')):
        return 'industrial-fire'
    if category == '1' and any(word in text for word in ('жилой дом', 'квартир', 'частный дом', 'балкон', 'подъезд', 'лестничн', 'мусоропровод', 'подвал')):
        return 'residential-fire'
    if category == '15' and any(word in text for word in ('массов', 'скопление людей', 'толпа', 'давка', 'митинг', 'шествие', 'пикет')):
        return 'mass-event'
    return None


def briefing_meta(task):
    """Return classifier-derived preparation text and the configured illustration key."""
    class_ids = _task_class_ids(task)
    rows = [_CLASS_BY_ID[class_id] for class_id in class_ids if class_id in _CLASS_BY_ID]
    mapping = _banner_map()
    exact = mapping.get('class_ids') if isinstance(mapping.get('class_ids'), dict) else {}
    categories = mapping.get('categories') if isinstance(mapping.get('categories'), dict) else {}

    banner = None
    for class_id, row in zip(class_ids, rows):
        banner = exact.get(class_id)
        if banner:
            break
        banner = _mapped_banner(row, mapping)
        if banner:
            break
        banner = _legacy_banner_for_row(row)
        if banner:
            break
    if not banner:
        for row in rows:
            banner = categories.get(str(row.get('category', ''))) or mapping.get('default')
            if banner:
                break

    if rows:
        # The selected classifier is authoritative for what is shown before the card opens.
        titles = []
        for row in rows:
            title = str(row.get('title') or row.get('ekp_type') or row.get('group') or '').strip()
            if title and title not in titles:
                titles.append(title)
        incident_label = '; '.join(titles) if titles else str(task.get('title', '')).strip()
        group_label = '; '.join(dict.fromkeys(str(row.get('group', '')).strip() for row in rows if str(row.get('group', '')).strip()))
        return {'banner_key': banner, 'incident_label': incident_label,
                'incident_group': group_label, 'classifier_ids': class_ids}

    # Compatibility for old exercises that do not contain classifier ids.
    title = str(task.get('title', '')).strip()
    low = title.lower()
    if not banner:
        if 'дтп' in low and 'пострадав' in low:
            banner = 'road-injured'
        elif any(word in low for word in ('запах газа', 'утечка газа', 'газопровод')):
            banner = 'gas-leak'
        elif any(word in low for word in ('человек в опасности', 'крики о помощи', 'человека зажало', 'падение с высоты')):
            banner = 'person-danger'
        elif any(word in low for word in ('массовое мероприят', 'массовые беспоряд', 'скопление людей', 'толпа', 'давка', 'митинг', 'концерт')):
            banner = 'mass-event'
        elif 'пожар' in low and any(word in low for word in ('производств', 'цех', 'завод', 'промышлен', 'склад')):
            banner = 'industrial-fire'
        elif 'пожар' in low and any(word in low for word in ('жилой дом', 'квартир', 'частный дом', 'балкон', 'подъезд', 'лестничн', 'подвал')):
            banner = 'residential-fire'
    return {'banner_key': banner or _banner_map().get('default'), 'incident_label': title or 'Учебное происшествие',
            'incident_group': '', 'classifier_ids': []}


def briefing_banner(task):
    """Backward-compatible banner-only helper."""
    return briefing_meta(task)['banner_key']


def student_portal_view(engine, identifier, full_form=False):
    view = engine.student_view(identifier)
    session = engine.load(identifier)
    if curriculum.expire(engine, session):
        session = engine.load(identifier)
        view = engine.student_view(identifier)
    view['training'] = session.get('training')
    view['activated_at'] = session.get('activated_at')
    view['machine_assessment'] = session.get('machine_assessment') if session['status'] == 'reviewed' else None
    view['ai_percent'] = (session.get('assessment') or {}).get('percent') if session['status'] == 'reviewed' else None
    view['timed_out'] = bool(session.get('timed_out'))
    view['training_reveals'] = session.get('training_reveals', [])
    view.update(briefing_meta(session['task']))
    if incident_training.is_full(session['task']):
        view.update(incident_training.public_metadata(session))
    view['reference'] = ({key: row['expected'] for key, row in session['task']['fields'].items()}
                         if session['status'] == 'reviewed' else None)
    view['duration_seconds'] = (max(0, int((datetime.fromisoformat(session['submitted_at']) -
                                           datetime.fromisoformat(session.get('activated_at') or session['created_at'])).total_seconds()))
                                if session.get('submitted_at') else None)
    if full_form and not incident_training.is_full(session['task']):
        return incident_training.legacy_projection(session, view)
    return view


def dispatch(engine, action, p):
    if action == 'materials_list':
        return materials.items(engine)
    if action == 'materials_add':
        return materials.add(engine, p)
    if action == 'reports_insights':
        rows = [s for s in engine.list_items('s') if s.get('assessment') and
                (not p.get('group') or (s.get('training') or {}).get('group') == p['group'])]
        counts = {}
        for s in rows:
            for field, verdict in s['assessment']['fields'].items():
                if verdict['verdict'] in ('incorrect','missing','partial'):
                    label = (s['task'].get('field_labels') or {}).get(field, field)
                    counts[label] = counts.get(label, 0) + 1
        if not rows:
            raise ValueError('Для аналитики сначала проверьте работы обучающихся.')
        result = engine.provider.generate('Ты анализируешь только обезличенные агрегаты учебной группы. Не называй имена. JSON: {"summary":"типичные ошибки", "recommendations":"что отработать на следующем занятии"}. Не приписывай отсутствующие причины.',
            {'works':len(rows), 'errors_by_field':counts}, .2, schema=obj(summary=TEXT,recommendations=TEXT))
        return {'works':len(rows), 'counts':counts, 'summary':result['summary'], 'recommendations':result['recommendations']}
    if action == 'scenario_list':
        return curriculum.list_resources(engine, 'scenario')
    if action == 'scenario_get':
        return curriculum.get(engine, p['resource_id'])
    if action == 'scenario_save':
        return curriculum.save_scenario(engine, p, p.get('resource_id'))
    if action == 'scenario_approve':
        return curriculum.approve_scenario(engine, p['resource_id'], p['teacher'])
    if action == 'scenario_delete':
        return curriculum.delete_scenario(engine, p['resource_id'])
    if action == 'training_list':
        return curriculum.list_resources(engine, 'training')
    if action == 'training_get':
        return curriculum.get(engine, p['resource_id'])
    if action == 'training_save':
        return curriculum.save_training(engine, p, p.get('resource_id'))
    if action == 'training_activate':
        return curriculum.activate(engine, p['resource_id'])
    if action == 'training_complete':
        return curriculum.complete(engine, p['resource_id'], p['teacher'])
    if action == 'training_delete':
        return curriculum.delete_training(engine, p['resource_id'])
    if action == 'training_desk':
        return curriculum.desk(engine, p['student'])
    if action == 'training_route':
        return curriculum.route_card(engine, p['resource_id'], p['card_id'], p['student'], p['services'], p.get('updates', {}))
    if action == 'training_service_action':
        return curriculum.service_action(engine, p['resource_id'], p['card_id'], p['student'], p['text'])
    if action in ('teacher_dashboard', 'teacher_session', 'teacher_task', 'teacher_note', 'teacher_finish', 'teacher_launch'):
        return teacher_portal.dispatch(engine, action, p)
    if action == 'student_overview':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        sessions = [s for s in engine.list_items('s') if s['student'] == student]
        bound_ids = {task_id for scenario in curriculum.list_resources(engine, 'scenario')
                     if scenario['status'] == 'approved' for task_id in scenario['task_ids']}
        for candidate in sessions:
            if curriculum.expire(engine, candidate):
                candidate.update(engine.load(candidate['id']))
        return {'fields': FIELDS,
                'tasks': [{'id': t['id'], 'title': t['title'],
                           'workflow': t.get('workflow', 'caller'), 'teacher': t.get('approved_by', ''),
                           'created_at': t.get('approved_at', t['created_at']),
                           **briefing_meta(t)} for t in engine.approved_tasks() if t['id'] not in bound_ids],
                'sessions': [{'id': s['id'], 'task_id': s['task']['id'], 'title': s['task']['title'],
                              'workflow': s['task'].get('workflow', 'caller'),
                              'status': s['status'], 'created_at': s['created_at'], 'activated_at': s.get('activated_at'),
                              'teacher': (s.get('training') or {}).get('teacher') or s['task'].get('approved_by', ''),
                              'training': s.get('training'), **briefing_meta(s['task']),
                              'duration_seconds': (int((datetime.fromisoformat(s['submitted_at']) - datetime.fromisoformat(s.get('activated_at') or s['created_at'])).total_seconds()) if s.get('submitted_at') else None),
                              'final_percent': (s.get('teacher_decision') or {}).get('percent') if s['status'] == 'reviewed' else None,
                              'grade': s['teacher_decision']['grade'] if s['status'] == 'reviewed' else None}
                             for s in sessions]}
    if action == 'student_start':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        task_id = p.get('task_id')
        for s in engine.list_items('s'):
            if s['student'] == student and s['task']['id'] == task_id and s['status'] == 'active':
                return student_portal_view(engine, s['id'], p.get('full_form', False))
        if any(task_id in scenario['task_ids'] for scenario in curriculum.list_resources(engine, 'scenario') if scenario['status'] == 'approved'):
            raise ValueError('Задание выполняется в назначенной активной тренировке. Примите входящий вызов в списке.')
        return student_portal_view(engine, engine.start(task_id, student)['id'], p.get('full_form', False))
    if action == 'student_action':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        current = engine.load(p.get('id'))
        if current['student'] != student:
            raise ValueError('Эта тренировка относится к другому обучающемуся.')
        operation = p.get('operation')
        if operation not in ('student', 'accept', 'ask', 'nudge', 'save_card', 'submit', 'connect', 'channel'):
            raise ValueError('Действие недоступно в панели обучающегося.')
        if operation == 'accept':
            curriculum.accept_call(engine, current)
            return student_portal_view(engine, p['id'], p.get('full_form', False))
        if current.get('status') == 'queued':
            raise ValueError('Сначала завершите предыдущую карточку этого сценария.')
        if curriculum.expire(engine, current):
            if operation != 'student':
                raise ValueError('Время карточки истекло. Сохранена последняя версия.')
            return student_portal_view(engine, p['id'], p.get('full_form', False))
        if operation == 'nudge':
            training_progress.coaching_nudge(engine, p['id'], p.get('card'))
            return student_portal_view(engine, p['id'], p.get('full_form', False))
        if operation == 'ask':
            engine.ask(p['id'], p['question'], p.get('source', 'text'), p.get('card'))
        else:
            dispatch(engine, operation, p)
        if operation == 'submit':
            curriculum.on_submission(engine, engine.load(p['id']))
            progression = training_progress.advance(engine, p['id'])
            if progression['next_id']:
                view = student_portal_view(engine, progression['next_id'], p.get('full_form', False))
                view.update(auto_advanced=True, previous_session_id=p['id'],
                            scenario_complete=False, adaptation=progression['adaptation'])
                return view
            view = student_portal_view(engine, p['id'], p.get('full_form', False))
            view.update(auto_advanced=False,
                        scenario_complete=bool((engine.load(p['id']).get('training') or {}).get('plan_id')),
                        adaptation=progression['adaptation'])
            return view
        return student_portal_view(engine, p['id'], p.get('full_form', False))
    if action == 'teacher_overview':
        return {
            'sessions': [{'id': s['id'], 'title': s['task']['title'], 'student': s['student'],
                          'status': s['status'], 'workflow': s['task'].get('workflow', 'caller'),
                          'created_at': s.get('created_at'),
                          'grade': (s.get('teacher_decision') or {}).get('grade') if s['status'] == 'reviewed' else None}
                         for s in engine.list_items('s')],
            'tasks': [{key: t.get(key) for key in ('id', 'title', 'status', 'workflow', 'level')}
                      for t in engine.list_items('t')],
        }
    if action == 'card_publish':
        return incident_training.publish(engine, p)
    if action == 'card_meta':
        return card_factory.metadata()
    if action == 'services_list':
        return card_factory.SERVICES
    if action == 'ai_status':
        # Keep the existing provider status for authoring features, and also
        # expose the dedicated dialogue service used by learner/teacher caller chat.
        result = engine.provider.status()
        try:
            result = {**result, 'dialogue_rest': ai_rest_client.health()}
        except RuntimeError as exc:
            result = {**result, 'dialogue_rest': {'state': 'error', 'message': str(exc)}}
        return result
    if action == 'tts_status':
        return piper_tts.status()
    if action == 'tts_synthesize':
        return piper_tts.synthesize(p.get('text'), p.get('voice'))
    if action == 'card_generate':
        return card_factory.generate(engine.provider, p)
    if action == 'card_reference':
        return card_reference.generate(engine.provider, p)
    if action == 'card_caller':
        return dialogue_gateway.ask(content=p.get('content'), caller_scenario=p.get('caller_scenario'),
                                    turns=p.get('turns'), question=p.get('question'), student_fields={})
    if action == 'card_approve':
        result = card_factory.approve(p)
        if p.get('publish_training'):
            result.update(incident_training.publish(engine, p))
        return result
    if action == 'card_validate':
        return card_factory.validate_content(p.get('content'))
    if action == 'home':
        return {'count': len(engine.approved_tasks()), 'fields': FIELDS, 'levels': LEVELS, 'verdicts': VERDICTS,
                'workflows': WORKFLOWS, 'action_labels': ACTION_LABELS,
                'counts': {key: len(engine.approved_tasks(key)) for key in WORKFLOWS}}
    if action == 'tasks':
        return engine.list_items('t')
    if action == 'create':
        return engine.sample(p['level'], p.get('workflow', 'caller')) if p.get('sample') else engine.draft(p['topic'], p['level'], p.get('workflow', 'caller'))
    if action == 'save_task':
        task = engine.load(p['id'])
        if not task['id'].startswith('t-') or task['status'] != 'draft':
            raise ValueError('Изменять можно только черновик задания.')
        for key in ('title', 'opening', 'persona', 'fields'):
            task[key] = p[key]
        if task.get('workflow') == 'dds':
            for key in ('incoming_card', 'verification_notes', 'service', 'faults', 'actions'):
                task[key] = p[key]
        validate_task(task)
        return engine.save(task)
    if action == 'approve':
        return engine.approve(p['id'], p['teacher'])
    if action == 'start':
        return engine.start_assigned(p['student'], p.get('workflow'))
    if action == 'connect':
        return engine.connect_service(p['id'])
    if action == 'channel':
        return engine.set_channel(p['id'], p['mode'])
    if action == 'sessions':
        return [engine.student_view(s['id']) for s in engine.list_items('s') if s['student'] == p['student']]
    if action == 'student':
        return engine.student_view(p['id'])
    if action == 'ask':
        engine.ask(p['id'], p['question'], p.get('source', 'text'), p.get('card'))
        return engine.student_view(p['id'])
    if action == 'hint':
        engine.hint(p['id'])
        return engine.student_view(p['id'])
    if action in ('save_card', 'submit'):
        s = engine._active(p['id'])
        card = p['card']
        if incident_training.is_full(s['task']):
            incident_training.save_card(engine, s, card, action == 'submit')
            return student_portal_view(engine, p['id'], p.get('full_form', False))
        if p.get('full_form'):
            incident_training.save_legacy_card(engine, s, card, action == 'submit')
            return student_portal_view(engine, p['id'], True)
        if not isinstance(card, dict) or set(card) != set(FIELDS) or any(not isinstance(v, str) or len(v) > 2000 for v in card.values()):
            raise ValueError('Проверьте поля карточки: не более 2000 символов в каждом.')
        # Validate the entire card before changing any fields.
        for key, value in card.items():
            if value != s['card'][key]:
                engine.set_field(p['id'], key, value)
        if action == 'submit':
            engine.submit(p['id'])
        return engine.student_view(p['id'])
    if action == 'assess':
        engine.assess(p['id'])
        return {'status': 'pending_teacher'}
    if action == 'works':
        return [{'id': s['id'], 'title': s['task']['title'], 'student': s['student'], 'status': s['status']} for s in engine.list_items('s') if s['status'] != 'active']
    if action == 'review':
        s = engine.load(p['id'])
        if not s['id'].startswith('s-') or s['status'] == 'active':
            raise ValueError('Эта работа ещё не сдана.')
        return s
    if action == 'finalize':
        return engine.finalize(p['id'], p['teacher'], p['grade'], p['conclusion'], p['decisions'])
    if action == 'finalize_percent':
        return engine.finalize_percent(p['id'], p['teacher'], p['percent'], p['conclusion'], p['decisions'])
    # --- Этап 2.1: слой пользователей и аутентификации (JWT) ---
    if action == 'auth_login':
        return auth_service.login(p.get('login', ''), p.get('password', ''), p.get('user_agent', ''))
    if action == 'auth_refresh':
        return auth_service.refresh(p.get('refresh_token', ''), p.get('user_agent', ''))
    if action == 'auth_logout':
        auth_service.logout(p.get('refresh_token', ''))
        return {'ok': True}
    if action == 'auth_me':
        return auth_service.me(p['_auth_user']['id'])
    if action == 'auth_users_list':
        return auth_service.list_users()
    if action == 'auth_users_create':
        return auth_service.create_user(p['login'], p['password'], p['full_name'], p['role'])
    if action == 'auth_users_update':
        return auth_service.update_user(
            int(p['user_id']), full_name=p.get('full_name'), role=p.get('role'),
            is_active=p.get('is_active'), password=p.get('password'),
            display_name=p.get('display_name'))
    if action == 'auth_users_delete':
        auth_service.delete_user(int(p['user_id']))
        return {'ok': True}
    if action == 'auth_groups_list':
        return auth_service.list_groups()
    if action == 'auth_groups_create':
        teacher_id = int(p['teacher_id']) if p.get('teacher_id') else None
        return auth_service.create_group(p['name'], p.get('description', ''), teacher_id)
    if action == 'auth_groups_update':
        teacher_id = int(p['teacher_id']) if p.get('teacher_id') else None
        return auth_service.update_group(int(p['group_id']), name=p.get('name'),
                                         description=p.get('description'),
                                         teacher_id=teacher_id)
    if action == 'auth_groups_delete':
        auth_service.delete_group(int(p['group_id']))
        return {'ok': True}
    if action == 'auth_groups_members':
        return auth_service.list_group_members(int(p['group_id']))
    if action == 'auth_groups_add_member':
        auth_service.add_group_member(int(p['group_id']), int(p['user_id']))
        return {'ok': True}
    if action == 'auth_groups_remove_member':
        auth_service.remove_group_member(int(p['group_id']), int(p['user_id']))
        return {'ok': True}
    # --- Этап 2.2: справочники (JWT admin) ---
    if action == 'catalog_services_list':
        return catalog_service.list_services()
    if action == 'catalog_services_create':
        return catalog_service.create_service(p['code'], p['name'])
    if action == 'catalog_services_update':
        return catalog_service.update_service(p['service_code'], p['name'])
    if action == 'catalog_services_delete':
        catalog_service.delete_service(p['service_code'])
        return {'ok': True}
    if action == 'catalog_categories_list':
        return catalog_service.list_categories()
    if action == 'catalog_categories_create':
        return catalog_service.create_category(p['category_id'], p['name'])
    if action == 'catalog_categories_update':
        return catalog_service.update_category(p['category_id'], p['name'])
    if action == 'catalog_categories_delete':
        catalog_service.delete_category(p['category_id'])
        return {'ok': True}
    if action == 'catalog_entries_list':
        return catalog_service.list_entries(p.get('category_id'))
    if action == 'catalog_entries_create':
        return catalog_service.create_entry(p)
    if action == 'catalog_entries_update':
        return catalog_service.update_entry(p['entry_id'], p)
    if action == 'catalog_entries_delete':
        catalog_service.delete_entry(p['entry_id'])
        return {'ok': True}
    if action == 'catalog_entry_services_list':
        return catalog_service.list_entry_services(p.get('entry_id'), p.get('service_code'))
    if action == 'catalog_entry_services_create':
        return catalog_service.create_entry_service(p)
    if action == 'catalog_entry_services_update':
        return catalog_service.update_entry_service(p['entry_service_id'], p)
    if action == 'catalog_entry_services_delete':
        catalog_service.delete_entry_service(p['entry_service_id'])
        return {'ok': True}
    if action == 'catalog_geo_addresses_list':
        return catalog_service.list_geo_addresses(p.get('kind'), p.get('limit'))
    if action == 'catalog_geo_addresses_create':
        return catalog_service.create_geo_address(p)
    if action == 'catalog_geo_addresses_update':
        return catalog_service.update_geo_address(p['address_id'], p)
    if action == 'catalog_geo_addresses_delete':
        catalog_service.delete_geo_address(p['address_id'])
        return {'ok': True}
    # --- Этап 5: мастерская карточек (JWT teacher/admin) ---
    import workshop_service
    if action == 'workshop_cards_list':
        return workshop_service.list_cards()
    if action == 'workshop_cards_create':
        return workshop_service.create_card(p.get('content'), _workshop_author(p))
    if action == 'workshop_cards_get':
        return workshop_service.get_card(p['workshop_ref'])
    if action == 'workshop_cards_update':
        return workshop_service.update_card(p['workshop_ref'], p.get('content'),
                                            _workshop_author(p))
    if action == 'workshop_cards_delete':
        return workshop_service.delete_card(p['workshop_ref'])
    if action == 'workshop_cards_approve':
        return workshop_service.approve_card(p['workshop_ref'], p.get('review'),
                                             _workshop_author(p))
    if action == 'workshop_cards_reopen':
        return workshop_service.reopen_card(p['workshop_ref'], _workshop_author(p))
    if action == 'workshop_import':
        return workshop_service.import_cards(p.get('cards'), _workshop_author(p))
    raise ValueError('Неизвестное действие.')


def _workshop_author(payload: dict):
    """Author id: authenticated JWT user, else the explicit author_id field."""
    user = payload.get('_auth_user')
    if isinstance(user, dict) and user.get('id') is not None:
        return int(user['id'])
    try:
        return int(payload['author_id']) if payload.get('author_id') else None
    except (TypeError, ValueError):
        return None
