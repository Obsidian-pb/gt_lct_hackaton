"""Orchestrator for Этап 3: move learning data from JSON files into PostgreSQL.

Pipeline (single transaction after user resolution):
  1. ensure_schema() 2.3.0 (legacy_name_map);
  2. scan the data directory and parse every supported file;
  3. resolve string student/teacher names into user records (created once,
     promoted to teacher when needed, never deleted by the importer) and fill
     legacy_name_map;
  4. truncate the educational tables and re-insert tasks/scenarios/trainings/
     sessions/materials with FK-safe filtering (records referencing missing
     tasks are skipped with a warning);
  5. report row counts, created users, skipped records and warnings.

The application still works with JSON files on this stage, so a full rewrite
is idempotent. Reference tables and utility tables are never touched.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import auth_crypto
import training_data_importer as importer
from training_data_importer import ScanReport
from training_data_repository import (
    AI_ASSESSMENT_COLUMNS, AI_ASSESSMENT_FIELD_COLUMNS, LEGACY_NAME_MAP_COLUMNS,
    MATERIAL_COLUMNS, MACHINE_ASSESSMENT_COLUMNS, SCENARIO_COLUMNS,
    SCENARIO_TASK_COLUMNS, SESSION_CARD_EDIT_COLUMNS, SESSION_COLUMNS,
    SESSION_HINT_COLUMNS, SESSION_REVEAL_COLUMNS, SESSION_TURN_COLUMNS,
    TASK_COLUMNS, TASK_DDS_COLUMNS, TASK_INCIDENT_COLUMNS,
    TEACHER_DECISION_COLUMNS, TEACHER_DECISION_FIELD_COLUMNS,
    TRAINING_CARD_COLUMNS, TRAINING_COLUMNS, TRAINING_PARTICIPANT_COLUMNS,
    TRAINING_SCENARIO_COLUMNS, TRAINING_SERVICE_ACTION_COLUMNS,
    TrainingDataRepository,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / 'data'

# Simple Cyrillic -> Latin transcription for generated logins.
TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'u', 'я': 'ya',
}


class TrainingDataError(RuntimeError):
    """Import-level failure (missing data, database error, broken records)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _or_now(value) -> Optional[str]:
    return value or _now()


def _jsonb(value):
    """Serialize a Python value for a jsonb column (None -> NULL).

    Strings that are already valid JSON documents pass through untouched;
    plain strings are wrapped so the server never rejects a jsonb literal.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except ValueError:
            return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def translit(text: str) -> str:
    """Lowercase latin slug of a Cyrillic/Latin name."""
    parts = []
    for char in str(text or '').lower():
        parts.append(TRANSLIT.get(char, char if char.isalnum() else '_'))
    slug = re.sub(r'_+', '_', ''.join(parts)).strip('_')
    slug = re.sub(r'[^a-z0-9_]+', '', slug)[:40]
    return slug or 'user'


# ------------------------------------------------------------------- parsing


def parse_all(report: ScanReport) -> dict:
    """Parse every scanned file into semantic records + errors."""
    parsed = {'tasks': [], 'sessions': [], 'scenarios': [], 'trainings': [],
              'materials': [], 'errors': []}
    root = report.directory

    for filename in report.task_files:
        value, error = importer.load_json(root / filename)
        if error is not None:
            parsed['errors'].append(f'{filename}: {error}')
            continue
        task = importer.parse_task(value)
        if task is None:
            parsed['errors'].append(f'{filename}: не распознан формат задания')
            continue
        parsed['tasks'].append(task)

    for filename in report.session_files:
        value, error = importer.load_json(root / filename)
        if error is not None:
            parsed['errors'].append(f'{filename}: {error}')
            continue
        session = importer.parse_session(value)
        if session is None:
            parsed['errors'].append(f'{filename}: не распознан формат сессии')
            continue
        parsed['sessions'].append(session)

    curriculum = root / 'curriculum'
    for filename in report.scenario_files:
        value, error = importer.load_json(curriculum / filename)
        if error is not None:
            parsed['errors'].append(f'{filename}: {error}')
            continue
        scenario = importer.parse_scenario(value)
        if scenario is None:
            parsed['errors'].append(f'{filename}: не распознан формат сценария')
            continue
        parsed['scenarios'].append(scenario)

    for filename in report.training_files:
        value, error = importer.load_json(curriculum / filename)
        if error is not None:
            parsed['errors'].append(f'{filename}: {error}')
            continue
        training = importer.parse_training(value)
        if training is None:
            parsed['errors'].append(f'{filename}: не распознан формат тренировки')
            continue
        parsed['trainings'].append(training)

    if report.materials_file:
        value, error = importer.load_json(curriculum / report.materials_file)
        if error is not None:
            parsed['errors'].append(f'{report.materials_file}: {error}')
        else:
            parsed['materials'] = importer.parse_materials(value)
    return parsed


# --------------------------------------------------------------- user mapping


def _make_unique_login(connection, repo, name: str, role: str) -> str:
    base = translit(name) or ('teacher' if role == 'teacher' else 'student')
    base = base[:40]
    if len(base) < 3:
        base = (base + 'xxx')[:40]
    candidate, suffix = base, 2
    while repo.user_by_login(connection, candidate) is not None:
        candidate = f'{base[:37]}{suffix}'
        suffix += 1
    return candidate


def resolve_users(connection, repo, names: Dict[str, set]) -> tuple:
    """Create/find user records for every legacy name. Returns (map, created)."""
    name_map: Dict[str, int] = {}
    created: List[dict] = []
    for name in sorted(names):
        kinds = names[name]
        desired = 'teacher' if 'teacher' in kinds else 'student'
        existing = repo.find_user_by_display_name(connection, name)
        if existing is not None:
            if desired == 'teacher' and existing['role'] == 'student':
                repo.promote_user_to_teacher(connection, existing['id'])
                existing['role'] = 'teacher'
            name_map[name] = existing['id']
            continue
        login = _make_unique_login(connection, repo, name, desired)
        password = secrets.token_urlsafe(9)
        user_id = repo.create_user(connection, login,
                                   auth_crypto.hash_password(password),
                                   name, desired, display_name=name)
        name_map[name] = user_id
        created.append({'name': name, 'login': login, 'role': desired})
    return name_map, created


# --------------------------------------------------------------- row building


def _uid(name, name_map, warnings, where):
    if name is None:
        return None
    key = str(name).strip()
    user_id = name_map.get(key)
    if user_id is None:
        warnings.append(f'{where}: имя «{key}» не сопоставлено пользователю')
    return user_id


def build_rowsets(parsed: dict, name_map: Dict[str, int],
                  warnings: List[str]) -> dict:
    """Convert parsed records into ordered INSERT tuples for every table."""
    sets = {'tasks': [], 'task_dds': [], 'task_incident': [],
            'scenarios': [], 'scenario_tasks': [],
            'trainings': [], 'training_scenarios': [], 'participants': [],
            'cards': [], 'service_actions': [],
            'sessions': [], 'turns': [], 'hints': [], 'edits': [], 'reveals': [],
            'machines': [], 'assessments': [], 'decisions': [], 'materials': []}

    available_tasks = {task['id'] for task in parsed['tasks']}

    # ---------------------------------------------------------------- tasks
    for task in parsed['tasks']:
        sets['tasks'].append((
            task['id'], task['title'], task['status'], task['workflow'],
            task['level'], task['format'], task['opening'], task['persona'],
            _jsonb(task['fields']), _jsonb(task['field_labels']), task['source'],
            task['identity_hash'],
            _uid(task['approved_by'], name_map, warnings, f"задание {task['id']}"),
            task['approved_at'],
            _or_now(task['created_at']), _or_now(task['updated_at'])))
        if task['dds'] is not None:
            dds = task['dds']
            sets['task_dds'].append((
                task['id'], _jsonb(dds['incoming_card']),
                dds['verification_notes'], dds['faults'],
                dds['service_name'], dds['service_role'],
                dds['service_knowledge'], _jsonb(dds['actions'])))
        if task['incident'] is not None:
            inc = task['incident']
            sets['task_incident'].append((
                task['id'], _jsonb(inc['content']), _jsonb(inc['reference']),
                _jsonb(inc['caller_scenario']), inc['opening']))

    # ------------------------------------------------------------- scenarios
    for scenario in parsed['scenarios']:
        sets['scenarios'].append((
            scenario['id'], scenario['title'], scenario['description'],
            scenario['status'],
            _uid(scenario['created_by'], name_map, warnings,
                 f"сценарий {scenario['id']}"),
            _uid(scenario['approved_by'], name_map, warnings,
                 f"сценарий {scenario['id']}"),
            scenario['approved_at'],
            _or_now(scenario['created_at']), _or_now(scenario['updated_at'])))
        for task_id, difficulty in scenario['tasks']:
            if task_id not in available_tasks:
                warnings.append(
                    f"сценарий {scenario['id']}: задача {task_id} не найдена")
                continue
            sets['scenario_tasks'].append((scenario['id'], task_id, difficulty))

    # ------------------------------------------------------------- trainings
    available_scenarios = {sc['id'] for sc in parsed['scenarios']}
    for training in parsed['trainings']:
        sets['trainings'].append((
            training['id'], training['title'], training['description'],
            training['status'], training['mode'], training['seconds'],
            training['difficulty'],
            _uid(training['teacher'], name_map, warnings,
                 f"тренировка {training['id']}"),
            training['group_name'],
            _or_now(training['created_at']), training['started_at'],
            training['completed_at'], _or_now(training['updated_at'])))
        for scenario_id in training['scenario_ids']:
            if scenario_id not in available_scenarios:
                warnings.append(
                    f"тренировка {training['id']}: сценарий {scenario_id} не найден")
                continue
            sets['training_scenarios'].append((training['id'], scenario_id))
        seen_users = set()
        for name, role, service in training['participants']:
            user_id = _uid(name, name_map, warnings,
                           f"тренировка {training['id']}")
            if user_id is None or (training['id'], user_id) in seen_users:
                continue
            seen_users.add((training['id'], user_id))
            sets['participants'].append(
                (training['id'], user_id, role, service))
        for card in training['cards']:
            task_id = card['task_id']
            if not isinstance(task_id, str) or task_id not in available_tasks:
                warnings.append(
                    f"тренировка {training['id']}: карточка {card['id']}:"
                    f" задача {task_id} не найдена")
                continue
            sets['cards'].append((
                card['id'], training['id'], task_id,
                card['operator_session_id'], card['status'],
                _jsonb(card['card_snapshot']), _jsonb(card['services']),
                card['submitted_at'],
                _uid(card['dds_by'], name_map, warnings,
                     f"карточка {card['id']}"),
                card['routed_at']))
            for service_code, text, at in card['service_actions']:
                sets['service_actions'].append(
                    (card['id'], service_code, text, _or_now(at)))

    # -------------------------------------------------------------- sessions
    for session in parsed['sessions']:
        if session['task_id'] not in available_tasks:
            warnings.append(
                f"сессия {session['id']}: задача {session['task_id']} не найдена —"
                ' сессия пропущена')
            continue
        student_id = _uid(session['student'], name_map, warnings,
                          f"сессия {session['id']}")
        if student_id is None:
            warnings.append(
                f"сессия {session['id']}: нет обучающегося — сессия пропущена")
            continue
        created_at = _or_now(session['created_at'])
        sets['sessions'].append((
            session['id'], session['task_id'], _jsonb(session['task_snapshot']),
            session['reference_hash'], student_id, session['status'],
            session['effective_level'], _jsonb(session['card']),
            _jsonb(session['training_meta']), session['callback_disclosed'],
            session['connection'], session['call_attempts'],
            session['next_channel'], session['timed_out'],
            _jsonb(session['forced_finish']), session['teacher_note'],
            _uid(session['teacher_note_by'], name_map, warnings,
                 f"сессия {session['id']}"),
            session['teacher_note_at'], created_at,
            session['activated_at'], session['submitted_at'],
            _or_now(session['updated_at'])))

        seen_turns = set()
        for turn in session['turns']:
            if turn[1] in seen_turns:
                continue
            seen_turns.add(turn[1])
            sets['turns'].append((session['id'],) + turn)

        for hint in session['hints']:
            sets['hints'].append((session['id'], hint['text'],
                                  _or_now(hint['at'])))
        for edit in session['edits']:
            sets['edits'].append((session['id'],) + edit)
        for reveal in session['reveals']:
            sets['reveals'].append((session['id'],) + reveal)

        if session['machine'] is not None:
            m = session['machine']
            sets['machines'].append((session['id'], m['percent'],
                                     _jsonb(m['compared']), m['method'],
                                     _jsonb(m['fields']), _or_now(m['at'])))
        if session['assessment'] is not None:
            a = session['assessment']
            sets['assessments'].append({
                'session_id': session['id'],
                'row': (session['id'], a['summary'], a['percent'],
                        a['reference_hash'], 'ready', _or_now(a['created_at'])),
                'fields': [(f[0], f[1], f[2], f[3], f[4], _jsonb(f[5]))
                           for f in a['fields']],
            })
        if session['decision'] is not None:
            d = session['decision']
            grade = d['grade']
            if not isinstance(grade, int) or not 2 <= grade <= 5:
                warnings.append(
                    f"сессия {session['id']}: оценка преподавателя {grade!r}"
                    ' вне диапазона 2..5 — сохранено NULL')
                grade = None
            sets['decisions'].append({
                'session_id': session['id'],
                'row': (session['id'],
                        _uid(d['teacher'], name_map, warnings,
                             f"решение по сессии {session['id']}"),
                        grade, d['percent'], d['conclusion'],
                        _or_now(d['created_at'])),
                'fields': d['fields'],
            })

    # ------------------------------------------------------------- materials
    for material in parsed['materials']:
        sets['materials'].append((
            material['id'], material['title'], material['url'],
            material['description'],
            _uid(material['teacher'], name_map, warnings,
                 f"материал {material['id']}"),
            _or_now(material['created_at'])))
    return sets


# ------------------------------------------------------------------ pipeline


def import_all(directory=None, config=None) -> dict:
    """Run the full import: schema -> parse -> users -> rewrite -> counts."""
    repo = TrainingDataRepository(config)
    repo.ensure_schema()

    root = Path(directory) if directory else DEFAULT_DATA_DIR
    report = importer.scan(root)
    if not report.available:
        raise TrainingDataError(
            'Учебные данные не найдены: каталог ' + str(root)
            + ' не содержит t-*.json / s-*.json / curriculum/*.json')

    parsed = parse_all(report)
    warnings: List[str] = list(parsed['errors'])
    names = importer.collect_names(parsed)

    with repo._connect() as connection:
        with connection.transaction():
            repo.truncate_all(connection)
            name_map, created_users = resolve_users(connection, repo, names)
            legacy_rows = [
                (name, name_map[name],
                 'teacher' if 'teacher' in kinds else 'student')
                for name, kinds in sorted(names.items())]
            repo.insert_legacy_names(connection, legacy_rows)
            rowsets = build_rowsets(parsed, name_map, warnings)
            repo.insert_many(connection, 'task', TASK_COLUMNS, rowsets['tasks'])
            repo.insert_many(connection, 'task_dds', TASK_DDS_COLUMNS,
                             rowsets['task_dds'])
            repo.insert_many(connection, 'task_incident_source',
                             TASK_INCIDENT_COLUMNS, rowsets['task_incident'])
            repo.insert_many(connection, 'scenario', SCENARIO_COLUMNS,
                             rowsets['scenarios'])
            repo.insert_many(connection, 'scenario_task', SCENARIO_TASK_COLUMNS,
                             rowsets['scenario_tasks'])
            repo.insert_many(connection, 'training', TRAINING_COLUMNS,
                             rowsets['trainings'])
            repo.insert_many(connection, 'training_scenario',
                             TRAINING_SCENARIO_COLUMNS,
                             rowsets['training_scenarios'])
            repo.insert_many(connection, 'training_participant',
                             TRAINING_PARTICIPANT_COLUMNS, rowsets['participants'])
            repo.insert_many(connection, 'training_card', TRAINING_CARD_COLUMNS,
                             rowsets['cards'])
            repo.insert_many(connection, 'training_service_action',
                             TRAINING_SERVICE_ACTION_COLUMNS,
                             rowsets['service_actions'])
            repo.insert_many(connection, 'session', SESSION_COLUMNS,
                             rowsets['sessions'])
            repo.insert_many(connection, 'session_turn', SESSION_TURN_COLUMNS,
                             rowsets['turns'])
            repo.insert_many(connection, 'session_hint', SESSION_HINT_COLUMNS,
                             rowsets['hints'])
            repo.insert_many(connection, 'session_card_edit',
                             SESSION_CARD_EDIT_COLUMNS, rowsets['edits'])
            repo.insert_many(connection, 'session_reveal', SESSION_REVEAL_COLUMNS,
                             rowsets['reveals'])
            repo.insert_many(connection, 'machine_assessment',
                             MACHINE_ASSESSMENT_COLUMNS, rowsets['machines'])
            for assessment in rowsets['assessments']:
                assessment_id = repo.insert_one_returning(
                    connection, 'ai_assessment', AI_ASSESSMENT_COLUMNS,
                    assessment['row'])
                field_rows = [(assessment_id,) + f for f in assessment['fields']]
                repo.insert_many(connection, 'ai_assessment_field',
                                 AI_ASSESSMENT_FIELD_COLUMNS, field_rows)
            for decision in rowsets['decisions']:
                decision_id = repo.insert_one_returning(
                    connection, 'teacher_decision', TEACHER_DECISION_COLUMNS,
                    decision['row'])
                field_rows = [(decision_id,) + f for f in decision['fields']]
                repo.insert_many(connection, 'teacher_decision_field',
                                 TEACHER_DECISION_FIELD_COLUMNS, field_rows)
            repo.insert_many(connection, 'material', MATERIAL_COLUMNS,
                             rowsets['materials'])

    counts = repo.counts()
    issues = repo.integrity_issues()
    return {'counts': counts, 'created_users': created_users,
            'warnings': warnings, 'integrity_issues': issues,
            'files': {'tasks': len(report.task_files),
                      'sessions': len(report.session_files),
                      'scenarios': len(report.scenario_files),
                      'trainings': len(report.training_files),
                      'materials': bool(report.materials_file)}}


def check_state(directory=None, config=None) -> dict:
    """Read-only state: scanned files vs database counts and integrity."""
    repo = TrainingDataRepository(config)
    report = importer.scan(Path(directory) if directory else DEFAULT_DATA_DIR)
    version = repo.migration_version()
    counts = repo.counts() if version else {}
    issues = repo.integrity_issues() if version else []
    return {'report': report, 'version': version, 'counts': counts,
            'issues': issues}