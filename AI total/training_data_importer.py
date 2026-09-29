"""Pure parsing of the JSON learning-data files into DB-ready dictionaries.

Этап 3: данные, которые сейчас живут вне СУБД, переносятся в таблицы,
созданные Этапом 2.2. Этот модуль не обращается к БД: он сканирует каталог
data/ (t-*.json, s-*.json) и data/curriculum/ (scenario-*.json,
training-*.json, materials.json), разбирает файлы в семантические структуры
и собирает строковые имена студентов/преподавателей для маппинга на user.

File formats mirror the code that writes them:
- tasks: Engine.save / sample.json / sample_dds.json / incident_training.publish;
- sessions: Engine.start/submit/assess/finalize, training_progress, teacher_portal;
- scenarios/trainings: curriculum.save_scenario/save_training/activate;
- materials: materials.add.

Invalid records are skipped with a message appended to errors[]; broken JSON
is reported through the same list so the orchestrator can continue.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

TASK_ID = re.compile(r'^t-[0-9a-f]{12}$')
SESSION_ID = re.compile(r'^s-[0-9a-f]{12}$')
CURRICULUM_ID = re.compile(r'^(scenario|training)-[0-9a-f]{12}$')

FIELDS = {'address': 'Адрес', 'incident': 'Что произошло', 'people': 'Люди внутри',
          'injured': 'Пострадавшие', 'floors': 'Этажность', 'entrance': 'Подъезд / вход',
          'access': 'Как проехать'}

TASK_STATUSES = {'draft', 'approved'}
SCENARIO_STATUSES = {'draft', 'approved'}
TRAINING_STATUSES = {'prepared', 'active', 'completed'}
CARD_STATUSES = {'awaiting_call', 'operator_work', 'dds_review',
                 'service_review', 'done', 'stopped'}
SESSION_STATUSES = {'queued', 'awaiting_call', 'active', 'submitted',
                    'pending_teacher', 'reviewed'}
PARTICIPANT_ROLES = {'operator', 'dds', 'service'}
TURN_ROLES = {'caller', 'dispatcher', 'system', 'service'}
TURN_SOURCES = {'text', 'voice'}
VERDICTS = {'correct', 'partial', 'incorrect', 'missing', 'unavailable'}
DECISION_CHOICES = {'agree', 'reject', 'edit'}


# ------------------------------------------------------------------- helpers


def normalize_ts(value) -> Optional[str]:
    """Normalize an ISO timestamp to UTC ISO text (safe for timestamptz).

    Strings without an offset are assumed to be UTC (the app writes
    datetime.now(timezone.utc).isoformat() everywhere). Malformed values are
    returned unchanged and left to PostgreSQL to interpret or reject.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


def delivered_flag(row: dict) -> bool:
    """A turn is delivered unless the DDS engine marked it as lost."""
    if row.get('delivery') == 'lost':
        return False
    delivered = row.get('delivered')
    if isinstance(delivered, str):
        return bool(delivered.strip())
    return bool(delivered) if delivered is not None else True


def compute_identity_hash(task: dict) -> Optional[str]:
    """Full SHA-256 over the published incident-v1 payload.

    Mirrors incident_training.publish (where the task id is the 12-char hex
    prefix of this hash): only incident-v1 tasks get an identity hash.
    """
    if task.get('format') != 'incident-v1':
        return None
    identity = json.dumps(
        [task.get('incident_source'), task.get('incident_reference'),
         task.get('caller_scenario'), task.get('opening'),
         task.get('level') or 'medium'],
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def compute_reference_hash(task: dict) -> str:
    """Same digest as ai_core.digest() used for session.reference_hash."""
    return hashlib.sha256(
        json.dumps(task, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('t', 'true', '1', 'yes', 'да')


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _citation_warning(value) -> Optional[str]:
    """Boolean-ish citation warning stored as a text column."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    text = str(value).strip().lower()
    if text in ('t', 'true', '1', 'yes', 'да'):
        return 'true'
    if text in ('f', 'false', '0', 'no', 'нет'):
        return 'false'
    return str(value)


# ------------------------------------------------------------------- scan


@dataclass
class ScanReport:
    """Result of scanning the data directory."""
    directory: Path
    data_exists: bool = False
    curriculum_exists: bool = False
    task_files: List[str] = field(default_factory=list)
    session_files: List[str] = field(default_factory=list)
    scenario_files: List[str] = field(default_factory=list)
    training_files: List[str] = field(default_factory=list)
    materials_file: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self.task_files or self.session_files or self.scenario_files
                    or self.training_files or self.materials_file)


def scan(directory) -> ScanReport:
    """List the learning-data files present under directory."""
    root = Path(directory)
    report = ScanReport(directory=root)
    if not root.is_dir():
        return report
    report.data_exists = True
    report.task_files = [p.name for p in sorted(root.glob('t-*.json'))]
    report.session_files = [p.name for p in sorted(root.glob('s-*.json'))]
    curriculum = root / 'curriculum'
    if curriculum.is_dir():
        report.curriculum_exists = True
        report.scenario_files = [p.name for p in sorted(curriculum.glob('scenario-*.json'))]
        report.training_files = [p.name for p in sorted(curriculum.glob('training-*.json'))]
        materials = curriculum / 'materials.json'
        if materials.is_file():
            report.materials_file = materials.name
    return report


def load_json(path: Path) -> tuple:
    """Return (value, error_text). error_text is None on success."""
    try:
        return json.loads(path.read_text(encoding='utf-8')), None
    except OSError as exc:
        return None, f'не удалось прочитать: {exc}'
    except ValueError as exc:
        return None, f'повреждённый JSON: {exc}'


# --------------------------------------------------------------- task parser


def parse_task(data: dict) -> Optional[dict]:
    """Parse a t-*.json file into a semantic task dict (plus dds/incident rows).

    Returns None when the record is fundamentally broken (id/status/workflow);
    malformed optional pieces are silently defaulted.
    """
    if not isinstance(data, dict):
        return None
    identifier = data.get('id')
    if not isinstance(identifier, str) or not TASK_ID.fullmatch(identifier):
        return None
    status = data.get('status', 'draft')
    if status not in TASK_STATUSES:
        return None
    workflow = data.get('workflow', 'caller')
    if workflow not in ('caller', 'dds'):
        workflow = 'caller'
    fmt = 'incident-v1' if data.get('format') == 'incident-v1' else 'legacy'
    fields = data.get('fields') if isinstance(data.get('fields'), dict) else {}
    labels = data.get('field_labels')
    if not isinstance(labels, dict):
        labels = dict(FIELDS)

    task = {
        'id': identifier,
        'title': str(data.get('title') or ''),
        'status': status,
        'workflow': workflow,
        'level': data.get('level'),
        'format': fmt,
        'opening': data.get('opening'),
        'persona': data.get('persona'),
        'fields': fields,
        'field_labels': labels,
        'source': data.get('source'),
        'identity_hash': compute_identity_hash(data),
        'approved_by': data.get('approved_by'),
        'approved_at': normalize_ts(data.get('approved_at')),
        'created_at': normalize_ts(data.get('created_at')),
        'updated_at': normalize_ts(data.get('updated_at')),
    }
    if workflow == 'dds':
        service = data.get('service') if isinstance(data.get('service'), dict) else {}
        task['dds'] = {
            'incoming_card': data.get('incoming_card')
            if isinstance(data.get('incoming_card'), dict) else None,
            'verification_notes': data.get('verification_notes'),
            'faults': data.get('faults'),
            'service_name': service.get('name'),
            'service_role': service.get('role'),
            'service_knowledge': service.get('knowledge'),
            'actions': data.get('actions') if isinstance(data.get('actions'), dict) else None,
        }
    else:
        task['dds'] = None
    if fmt == 'incident-v1':
        task['incident'] = {
            'content': data.get('incident_source')
            if isinstance(data.get('incident_source'), dict) else None,
            'reference': data.get('incident_reference')
            if isinstance(data.get('incident_reference'), dict) else None,
            'caller_scenario': data.get('caller_scenario')
            if isinstance(data.get('caller_scenario'), dict) else None,
            'opening': data.get('opening'),
        }
    else:
        task['incident'] = None
    return task


# ------------------------------------------------------------- session parser


def _parse_history(history, created_at: Optional[str]) -> List[tuple]:
    """history[] -> session_turn tuples (turn_no, role, text, source, event, delivered, at)."""
    turns = []
    fallback_no = 1
    if not isinstance(history, list):
        return turns
    for row in history:
        if not isinstance(row, dict):
            continue
        turn_no = _as_int(row.get('id'), fallback_no)
        fallback_no = turn_no + 1
        role = row.get('role')
        if role not in TURN_ROLES:
            continue
        text = row.get('text')
        if not isinstance(text, str):
            text = ''
        source = row.get('source', 'text')
        if source not in TURN_SOURCES:
            source = 'text'
        at = normalize_ts(row.get('at')) or created_at
        turns.append((turn_no, role, text, source, row.get('event'),
                      delivered_flag(row), at))
    return turns


def _parse_assessment(value) -> Optional[dict]:
    """session.assessment -> ai_assessment dict + ai_assessment_field tuples."""
    if not isinstance(value, dict):
        return None
    fields = []
    raw_fields = value.get('fields') if isinstance(value.get('fields'), dict) else {}
    for field, row in raw_fields.items():
        if not isinstance(row, dict):
            continue
        verdict = row.get('verdict')
        if verdict not in VERDICTS:
            verdict = 'unavailable'
        evidence = row.get('evidence')
        fields.append((field, verdict, row.get('comment'),
                       row.get('clarification'),
                       _citation_warning(row.get('citation_warning')),
                       evidence if isinstance(evidence, list) else None))
    return {'summary': value.get('summary'),
            'percent': _as_int(value.get('percent')),
            'reference_hash': value.get('reference_hash'),
            'created_at': normalize_ts(value.get('at')),
            'fields': fields}


def _parse_decision(value) -> Optional[dict]:
    """session.teacher_decision -> teacher_decision dict + field tuples."""
    if not isinstance(value, dict):
        return None
    fields = []
    raw_fields = value.get('fields') if isinstance(value.get('fields'), dict) else {}
    for field, row in raw_fields.items():
        if not isinstance(row, dict):
            continue
        decision = row.get('decision')
        if decision not in DECISION_CHOICES:
            decision = 'agree'
        fields.append((field, decision, row.get('comment')))
    return {'teacher': value.get('teacher'),
            'grade': value.get('grade'),
            'percent': _as_int(value.get('percent')),
            'conclusion': value.get('conclusion'),
            'created_at': normalize_ts(value.get('at')),
            'fields': fields}


def parse_session(data: dict) -> Optional[dict]:
    """Parse an s-*.json file into a semantic session dict + child collections."""
    if not isinstance(data, dict):
        return None
    identifier = data.get('id')
    if not isinstance(identifier, str) or not SESSION_ID.fullmatch(identifier):
        return None
    task = data.get('task')
    if not isinstance(task, dict) or not isinstance(task.get('id'), str) \
            or not TASK_ID.fullmatch(task.get('id', '')):
        return None
    status = data.get('status')
    if status not in SESSION_STATUSES:
        return None
    created_at = normalize_ts(data.get('created_at'))
    machine = data.get('machine_assessment')
    assessment = _parse_assessment(data.get('assessment'))
    decision = _parse_decision(data.get('teacher_decision'))

    session = {
        'id': identifier,
        'task_id': task['id'],
        'task_snapshot': task,
        'reference_hash': data.get('reference_hash') or compute_reference_hash(task),
        'student': data.get('student'),
        'status': status,
        'effective_level': data.get('effective_level'),
        'card': data.get('card') if isinstance(data.get('card'), dict) else {},
        'training_meta': data.get('training') if isinstance(data.get('training'), dict) else None,
        'callback_disclosed': _as_bool(data.get('callback_disclosed')),
        'connection': data.get('connection'),
        'call_attempts': _as_int(data.get('call_attempts')),
        'next_channel': data.get('next_channel'),
        'timed_out': _as_bool(data.get('timed_out')),
        'forced_finish': data.get('forced_finish')
        if isinstance(data.get('forced_finish'), dict) else None,
        'teacher_note': data.get('teacher_note'),
        'teacher_note_by': data.get('teacher_note_by'),
        'teacher_note_at': normalize_ts(data.get('teacher_note_at')),
        'created_at': created_at,
        'activated_at': normalize_ts(data.get('activated_at')),
        'submitted_at': normalize_ts(data.get('submitted_at')),
        'updated_at': normalize_ts(data.get('updated_at')),
        'turns': _parse_history(data.get('history'), created_at),
        'hints': [{'text': row.get('text'), 'at': normalize_ts(row.get('at')) or created_at}
                  for row in data.get('hints') or [] if isinstance(row, dict)],
        'edits': [(row.get('field'), row.get('before'), row.get('after'),
                   normalize_ts(row.get('at')) or created_at)
                  for row in data.get('card_edits') or [] if isinstance(row, dict)],
        'reveals': [(row.get('field'), row.get('label'), row.get('value'),
                     _as_int(row.get('number')), normalize_ts(row.get('at')) or created_at)
                    for row in data.get('training_reveals') or [] if isinstance(row, dict)],
        'machine': {
            'percent': _as_int(machine.get('percent')),
            'compared': machine.get('compared'),
            'method': machine.get('method'),
            'fields': machine.get('fields') if isinstance(machine.get('fields'), dict) else None,
            'at': normalize_ts(machine.get('at')) or created_at,
        } if isinstance(machine, dict) else None,
        'assessment': assessment,
        'decision': decision,
    }
    return session


# ---------------------------------------------------------- curriculum parsers


def parse_scenario(data: dict) -> Optional[dict]:
    """scenario-*.json -> semantic scenario dict + (task_id, difficulty) rows."""
    if not isinstance(data, dict):
        return None
    identifier = data.get('id')
    if not isinstance(identifier, str) or not CURRICULUM_ID.fullmatch(identifier) \
            or not identifier.startswith('scenario-'):
        return None
    status = data.get('status', 'draft')
    if status not in SCENARIO_STATUSES:
        return None
    task_ids = data.get('task_ids')
    if not isinstance(task_ids, list):
        task_ids = []
    difficulties = data.get('task_difficulties')
    if not isinstance(difficulties, dict):
        difficulties = {}
    tasks = []
    for task_id in task_ids:
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            continue
        difficulty = _as_int(difficulties.get(task_id), 3)
        tasks.append((task_id, difficulty))
    return {
        'id': identifier,
        'title': str(data.get('title') or ''),
        'description': str(data.get('description') or ''),
        'status': status,
        'created_by': data.get('created_by'),
        'approved_by': data.get('approved_by'),
        'approved_at': normalize_ts(data.get('approved_at')),
        'created_at': normalize_ts(data.get('created_at')),
        'updated_at': normalize_ts(data.get('updated_at')),
        'tasks': tasks,
    }


def parse_training(data: dict) -> Optional[dict]:
    """training-*.json -> semantic training dict with scenarios/participants/cards."""
    if not isinstance(data, dict):
        return None
    identifier = data.get('id')
    if not isinstance(identifier, str) or not CURRICULUM_ID.fullmatch(identifier) \
            or not identifier.startswith('training-'):
        return None
    status = data.get('status', 'prepared')
    if status not in TRAINING_STATUSES:
        return None
    mode = data.get('mode', 'training')
    if mode not in ('training', 'testing'):
        mode = 'training'
    difficulty = data.get('difficulty', 'easy')
    if difficulty not in ('easy', 'medium', 'hard', 'adaptive'):
        difficulty = 'easy'

    scenario_ids = [sid for sid in (data.get('scenario_ids') or [])
                    if isinstance(sid, str) and CURRICULUM_ID.fullmatch(sid)
                    and sid.startswith('scenario-')]

    participants = []
    for row in data.get('participants') or []:
        if not isinstance(row, dict):
            continue
        role = row.get('role')
        if role not in PARTICIPANT_ROLES:
            continue
        participants.append((str(row.get('student') or '').strip(), role,
                             row.get('service') if role == 'service' else None))

    cards = []
    for record in data.get('cards') or []:
        if not isinstance(record, dict):
            continue
        card_id = record.get('id')
        if not isinstance(card_id, str) or not card_id.startswith('card-'):
            continue
        card_status = record.get('status')
        if card_status not in CARD_STATUSES:
            continue
        actions = []
        service_actions = record.get('service_actions')
        if isinstance(service_actions, dict):
            for service_code, action in service_actions.items():
                if isinstance(action, dict):
                    actions.append((str(service_code), str(action.get('text') or ''),
                                    normalize_ts(action.get('at'))))
        cards.append({
            'id': card_id,
            'task_id': record.get('task_id'),
            'operator_session_id': record.get('operator_session_id'),
            'status': card_status,
            'card_snapshot': record.get('card')
            if isinstance(record.get('card'), dict) else None,
            'services': record.get('services') if isinstance(record.get('services'), list) else None,
            'submitted_at': normalize_ts(record.get('submitted_at')),
            'dds_by': record.get('dds_by'),
            'routed_at': normalize_ts(record.get('routed_at')),
            'service_actions': actions,
        })

    return {
        'id': identifier,
        'title': str(data.get('title') or ''),
        'description': str(data.get('description') or ''),
        'status': status,
        'mode': mode,
        'seconds': _as_int(data.get('seconds')),
        'difficulty': difficulty,
        'teacher': data.get('teacher'),
        'group_name': data.get('group'),
        'created_at': normalize_ts(data.get('created_at')),
        'started_at': normalize_ts(data.get('started_at')),
        'completed_at': normalize_ts(data.get('completed_at')),
        'updated_at': normalize_ts(data.get('updated_at')),
        'scenario_ids': scenario_ids,
        'participants': participants,
        'cards': cards,
    }


def parse_materials(data) -> List[dict]:
    """materials.json (a JSON array) -> semantic material dicts."""
    if not isinstance(data, list):
        return []
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        result.append({
            'id': row.get('id'),
            'title': str(row.get('title') or ''),
            'url': str(row.get('url') or ''),
            'description': str(row.get('description') or ''),
            'teacher': row.get('teacher'),
            'created_at': normalize_ts(row.get('created_at')),
        })
    return result


# ------------------------------------------------------------------- names


def collect_names(parsed) -> Dict[str, set]:
    """Collect {name -> {kind, ...}} from every parsed record.

    kind is 'student' or 'teacher'; one name may appear in both roles.
    """
    names: Dict[str, set] = {}

    def add(name, kind):
        if not isinstance(name, str) or not name.strip():
            return
        names.setdefault(name.strip(), set()).add(kind)

    for task in parsed.get('tasks') or []:
        add(task.get('approved_by'), 'teacher')
    for scenario in parsed.get('scenarios') or []:
        add(scenario.get('created_by'), 'teacher')
        add(scenario.get('approved_by'), 'teacher')
    for training in parsed.get('trainings') or []:
        add(training.get('teacher'), 'teacher')
        for name, _role, _service in training.get('participants') or []:
            add(name, 'student')
    for session in parsed.get('sessions') or []:
        add(session.get('student'), 'student')
        add(session.get('teacher_note_by'), 'teacher')
        if session.get('decision') is not None:
            add(session['decision'].get('teacher'), 'teacher')
    for material in parsed.get('materials') or []:
        add(material.get('teacher'), 'teacher')
    return names