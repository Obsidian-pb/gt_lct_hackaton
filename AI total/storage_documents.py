"""Pure converters between the Engine JSON document format and DB row tuples.

Shared by Этап 3 (training_data_importer / training_data_service) and Этап 5
(storage_adapter): documents are the in-memory dictionaries produced/consumed
by ai_core.Engine.save/load/list_items and curriculum/material modules; row
tuples follow the column orders declared in training_data_repository.

The module never touches the database, so every conversion is unit-testable.
Direction conventions:
- *_to_rows(doc, resolve_name)    document -> row tuples (upsert inputs)
- *_from_row(row, ..., name_of)   DB rows (dicts with column names) -> document

`resolve_name(name_or_none, kind)` maps a legacy string name to user_id
(kind = 'student' | 'teacher'); `name_of(user_id_or_none)` maps back to the
string kept in user.display_name. Both are injected by the repository/adapter.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import training_data_importer as importer
from training_data_importer import (
    TASK_ID, SESSION_ID, CURRICULUM_ID,
    normalize_ts, delivered_flag, _as_bool, _as_int,
)

# ------------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonb(value):
    """Serialize a Python value for a jsonb column (None -> NULL).

    Strings that are already valid JSON pass through untouched; plain strings
    are wrapped so the server never rejects a jsonb literal.
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


_PG_OFFSET = re.compile(r'^(.*?)([+-]\d\d)$')


def load_ts(value):
    """Normalize a timestamp read back from PostgreSQL to UTC ISO text.

    The Simple Query protocol returns timestamptz as 'YYYY-MM-DD HH:MM:SS.fff+00';
    the file format uses 'T' and '+00:00', which the application code relies on.
    """
    if value is None:
        return None
    text = str(value)
    if ' ' in text:
        text = text.replace(' ', 'T', 1)
    match = _PG_OFFSET.match(text)
    if match and len(match.group(2)) == 3:
        text = match.group(1) + match.group(2) + ':00'
    return normalize_ts(text)


def _bool(value, default=False) -> bool:
    """PostgreSQL booleans arrive as text 't'/'f' over the wire protocol."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('t', 'true', '1', 'yes', 'да')


def _json_value(value):
    """Parse a jsonb value read back from PostgreSQL (arrives as JSON text)."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _dict(value) -> dict:
    if isinstance(value, str):
        parsed = _json_value(value)
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    if isinstance(value, str):
        parsed = _json_value(value)
        return parsed if isinstance(parsed, list) else []
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------- task rows


def task_to_rows(doc: dict, resolve_name: Callable) -> dict:
    """task document -> (task, task_dds, task_incident_source) row tuples."""
    parsed = importer.parse_task(doc)
    if parsed is None:
        raise ValueError('Неверный формат задания.')
    task = (
        parsed['id'], parsed['title'], parsed['status'], parsed['workflow'],
        parsed['level'], parsed['format'], parsed['opening'], parsed['persona'],
        jsonb(parsed['fields']), jsonb(parsed['field_labels']), parsed['source'],
        parsed['identity_hash'],
        doc.get('owner_id') or resolve_name(parsed['approved_by'], 'teacher'),
        parsed['approved_at'],
        parsed['created_at'] or _now(), parsed['updated_at'] or _now(),
    )
    dds = None
    if parsed['dds'] is not None:
        value = parsed['dds']
        dds = (
            parsed['id'], jsonb(value['incoming_card']),
            value['verification_notes'], value['faults'],
            value['service_name'], value['service_role'],
            value['service_knowledge'], jsonb(value['actions']),
        )
    incident = None
    if parsed['incident'] is not None:
        value = parsed['incident']
        incident = (
            parsed['id'], jsonb(value['content']), jsonb(value['reference']),
            jsonb(value['caller_scenario']), value['opening'],
        )
    return {'task': task, 'task_dds': dds, 'task_incident': incident}


def task_from_row(row: dict, dds_row: Optional[dict] = None,
                  incident_row: Optional[dict] = None,
                  name_of: Optional[Callable] = None) -> dict:
    """task + optional task_dds/task_incident_source rows -> task document.

    Rows are dicts with column names; missing optional rows are ignored.
    """
    doc = {
        'id': row['id'],
        'title': row.get('title') or '',
        'status': row.get('status', 'draft'),
        'workflow': row.get('workflow', 'caller'),
        'level': row.get('level'),
        'opening': row.get('opening'),
        'persona': row.get('persona'),
        'fields': _dict(row.get('fields')),
        'field_labels': _dict(row.get('field_labels')),
        'source': row.get('source'),
        'created_at': load_ts(row.get('created_at')),
        'updated_at': load_ts(row.get('updated_at')),
    }
    if row.get('approved_by_id') is not None:
        doc['owner_id'] = int(row['approved_by_id'])
        doc['approved_by'] = name_of(row['approved_by_id']) if name_of else None
        doc['approved_at'] = load_ts(row.get('approved_at'))
    if dds_row and doc['workflow'] == 'dds':
        doc.update(
            incoming_card=_dict(dds_row.get('incoming_card')),
            verification_notes=dds_row.get('verification_notes'),
            faults=dds_row.get('faults'),
            service={
                'name': dds_row.get('service_name'),
                'role': dds_row.get('service_role'),
                'knowledge': dds_row.get('service_knowledge'),
            },
            actions=_dict(dds_row.get('actions')),
        )
    if row.get('format') == 'incident-v1' and incident_row:
        doc.update(
            format='incident-v1',
            incident_source=_dict(incident_row.get('content')),
            incident_reference=_dict(incident_row.get('reference')),
            caller_scenario=_dict(incident_row.get('caller_scenario')),
            opening=incident_row.get('opening'),
        )
    return doc


# ------------------------------------------------------------- session rows


def session_to_rows(doc: dict, resolve_name: Callable) -> dict:
    """session document -> row tuples for session + all child tables."""
    parsed = importer.parse_session(doc)
    if parsed is None:
        raise ValueError('Неверный формат сессии.')
    created = parsed['created_at'] or _now()

    def _ts(value):
        """Child timestamps fall back to the session creation time (NOT NULL)."""
        return value or created

    session = (
        parsed['id'], parsed['task_id'], jsonb(parsed['task_snapshot']),
        parsed['reference_hash'], doc.get('student_id') or resolve_name(parsed['student'], 'student'),
        parsed['status'], parsed['effective_level'], jsonb(parsed['card']),
        jsonb(parsed['training_meta']), parsed['callback_disclosed'],
        parsed['connection'], parsed['call_attempts'], parsed['next_channel'],
        parsed['timed_out'], jsonb(parsed['forced_finish']),
        parsed['teacher_note'],
        (doc.get('teacher_note_by_id') or resolve_name(parsed['teacher_note_by'], 'teacher'))
        if parsed['teacher_note_by'] else None,
        parsed['teacher_note_at'], created,
        parsed['activated_at'], parsed['submitted_at'],
        parsed['updated_at'] or _now(),
    )
    turns = [(parsed['id'],) + (*turn[:-1], _ts(turn[-1]))
             for turn in parsed['turns']]
    hints = [(parsed['id'], hint['text'], _ts(hint['at']))
             for hint in parsed['hints']]
    edits = [(parsed['id'],) + (*edit[:-1], _ts(edit[-1]))
             for edit in parsed['edits']]
    reveals = [(parsed['id'],) + (*reveal[:-1], _ts(reveal[-1]))
               for reveal in parsed['reveals']]
    machine = None
    if parsed['machine'] is not None:
        m = parsed['machine']
        machine = (parsed['id'], m['percent'], jsonb(m['compared']),
                   m['method'], jsonb(m['fields']), m['at'] or _now())
    assessment = None
    if parsed['assessment'] is not None:
        a = parsed['assessment']
        assessment = {
            'row': (parsed['id'], a['summary'], a['percent'],
                    a['reference_hash'], 'ready', a['created_at'] or _now()),
            'fields': [(f[0], f[1], f[2], f[3], f[4], jsonb(f[5]))
                       for f in a['fields']],
        }
    decision = None
    if parsed['decision'] is not None:
        d = parsed['decision']
        grade = d['grade']
        if not isinstance(grade, int) or not 2 <= grade <= 5:
            grade = None
        decision = {
            'row': (parsed['id'], doc['teacher_decision'].get('teacher_id') or
                    resolve_name(d['teacher'], 'teacher'),
                    grade, d['percent'], d['conclusion'],
                    d['created_at'] or _now()),
            'fields': d['fields'],
        }
    return {'session': session, 'turns': turns, 'hints': hints, 'edits': edits,
            'reveals': reveals, 'machine': machine,
            'assessment': assessment, 'decision': decision}


def _turn_document(turn: dict) -> dict:
    """session_turn row -> one history[] entry (minimal keys like the app writes)."""
    item = {'id': _as_int(turn.get('turn_no'), 1),
            'role': turn.get('role', 'caller'),
            'text': turn.get('text') or ''}
    if turn.get('source') not in (None, 'text'):
        item['source'] = turn['source']
    if turn.get('event'):
        item['event'] = turn['event']
    delivered = turn.get('delivered')
    if delivered is not None:
        item['delivered'] = _bool(delivered)
    if turn.get('at'):
        item['at'] = load_ts(turn['at'])
    return item


def session_from_row(row: dict, turns: Optional[List[dict]] = None,
                     hints: Optional[List[dict]] = None,
                     edits: Optional[List[dict]] = None,
                     reveals: Optional[List[dict]] = None,
                     machine: Optional[dict] = None,
                     assessment: Optional[dict] = None,
                     assessment_fields: Optional[List[dict]] = None,
                     decision: Optional[dict] = None,
                     decision_fields: Optional[List[dict]] = None,
                     name_of: Optional[Callable] = None) -> dict:
    """session row + child rows (dicts with column names) -> session document."""
    student = name_of(row.get('student_id')) if name_of else None
    doc = {
        'id': row['id'],
        'student': student or '',
        'student_id': int(row['student_id']) if row.get('student_id') is not None else None,
        'task': _dict(row.get('task_snapshot')),
        'reference_hash': row.get('reference_hash'),
        'status': row.get('status', 'active'),
        'effective_level': row.get('effective_level'),
        'card': _dict(row.get('card')),
        'history': [_turn_document(t) for t in (turns or [])],
        'hints': [{'text': h.get('text') or '', 'at': load_ts(h.get('at'))}
                  for h in (hints or [])],
        'card_edits': [{'field': e.get('field') or '', 'before': e.get('before'),
                        'after': e.get('after'), 'at': load_ts(e.get('at'))}
                       for e in (edits or [])],
        'training_reveals': [{'field': r.get('field') or '',
                              'label': r.get('label') or '',
                              'value': r.get('value'),
                              'number': _as_int(r.get('number')),
                              'at': load_ts(r.get('at'))}
                             for r in (reveals or [])],
        'callback_disclosed': _bool(row.get('callback_disclosed')),
        'connection': row.get('connection'),
        'call_attempts': _as_int(row.get('call_attempts')),
        'next_channel': row.get('next_channel'),
        'timed_out': _bool(row.get('timed_out')),
        'forced_finish': _dict(row.get('forced_finish')),
        'teacher_note': row.get('teacher_note'),
        'teacher_note_by': name_of(row.get('teacher_note_by_id')) if name_of else None,
        'teacher_note_by_id': (int(row['teacher_note_by_id'])
                               if row.get('teacher_note_by_id') is not None else None),
        'teacher_note_at': load_ts(row.get('teacher_note_at')),
        'created_at': load_ts(row.get('created_at')),
        'activated_at': load_ts(row.get('activated_at')),
        'submitted_at': load_ts(row.get('submitted_at')),
        'updated_at': load_ts(row.get('updated_at')),
        'training': _dict(row.get('training_meta')) or None,
        'machine_assessment': None,
        'assessment': None,
        'teacher_decision': None,
    }
    if machine is not None:
        doc['machine_assessment'] = {
            'percent': machine.get('percent'),
            'compared': _json_value(machine.get('compared')),
            'method': machine.get('method'),
            'fields': _dict(machine.get('fields')),
            'at': load_ts(machine.get('at')),
        }
    if assessment is not None:
        fields = {}
        for field_row in (assessment_fields or []):
            fields[field_row['field']] = {
                'verdict': field_row.get('verdict', 'unavailable'),
                'comment': field_row.get('comment'),
                'clarification': field_row.get('clarification'),
                'evidence': _list(field_row.get('evidence')),
                'citation_warning': _bool(field_row.get('citation_warning')),
            }
        doc['assessment'] = {
            'summary': assessment.get('summary'),
            'percent': assessment.get('percent'),
            'reference_hash': assessment.get('reference_hash'),
            'at': load_ts(assessment.get('created_at')),
            'fields': fields,
        }
    if decision is not None:
        fields = {}
        for field_row in (decision_fields or []):
            fields[field_row['field']] = {
                'decision': field_row.get('decision', 'agree'),
                'comment': field_row.get('comment'),
            }
        doc['teacher_decision'] = {
            'teacher': name_of(decision.get('teacher_id')) if name_of else None,
            'teacher_id': (int(decision['teacher_id'])
                           if decision.get('teacher_id') is not None else None),
            'grade': decision.get('grade'),
            'percent': decision.get('percent'),
            'conclusion': decision.get('conclusion'),
            'at': load_ts(decision.get('created_at')),
            'fields': fields,
        }
    return doc


# ------------------------------------------------------------ scenario rows


def scenario_to_rows(doc: dict, resolve_name: Callable) -> dict:
    """scenario document -> scenario row + scenario_task rows."""
    parsed = importer.parse_scenario(doc)
    if parsed is None:
        raise ValueError('Неверный формат сценария.')
    row = (
        parsed['id'], parsed['title'], parsed['description'], parsed['status'],
        doc.get('owner_id') or resolve_name(parsed['created_by'], 'teacher'),
        (doc.get('owner_id') or resolve_name(parsed['approved_by'], 'teacher')) if parsed['approved_by'] else None,
        parsed['approved_at'],
        parsed['created_at'] or _now(), parsed['updated_at'] or _now(),
    )
    return {'scenario': row, 'tasks': parsed['tasks']}


def scenario_from_row(row: dict, tasks: Optional[List[dict]] = None,
                      name_of: Optional[Callable] = None) -> dict:
    """scenario row + scenario_task rows -> scenario document."""
    task_rows = tasks or []
    doc = {
        'id': row['id'],
        'title': row.get('title') or '',
        'description': row.get('description') or '',
        'status': row.get('status', 'draft'),
        'task_ids': [t['task_id'] for t in task_rows],
        'task_difficulties': {t['task_id']: _as_int(t.get('difficulty'), 3)
                              for t in task_rows},
        'created_at': load_ts(row.get('created_at')),
        'updated_at': load_ts(row.get('updated_at')),
    }
    if row.get('created_by_id') is not None:
        doc['owner_id'] = int(row['created_by_id'])
        doc['created_by'] = name_of(row['created_by_id']) if name_of else None
    if row.get('approved_by_id') is not None:
        doc['approved_by'] = name_of(row['approved_by_id']) if name_of else None
        doc['approved_at'] = load_ts(row.get('approved_at'))
    return doc


# ------------------------------------------------------------ training rows


def training_to_rows(doc: dict, resolve_name: Callable) -> dict:
    """training document -> training/training_scenario/participant/card rows."""
    parsed = importer.parse_training(doc)
    if parsed is None:
        raise ValueError('Неверный формат тренировки.')
    row = (
        parsed['id'], parsed['title'], parsed['description'], parsed['status'],
        parsed['mode'], parsed['seconds'], parsed['difficulty'],
        doc.get('teacher_id') or resolve_name(parsed['teacher'], 'teacher'), parsed['group_name'],
        parsed['created_at'] or _now(), parsed['started_at'],
        parsed['completed_at'], parsed['updated_at'] or _now(),
    )
    sources = [source for source in doc.get('participants') or []
               if isinstance(source, dict) and source.get('role') in ('operator', 'dds', 'service')]
    participants = [
        (parsed['id'], source.get('user_id') or resolve_name(name, 'student'), role, service)
        for source, (name, role, service) in zip(sources, parsed['participants'])]
    cards = []
    source_cards = {card['id']: card for card in doc.get('cards') or []
                    if isinstance(card, dict) and isinstance(card.get('id'), str)}
    for card in parsed['cards']:
        cards.append({
            'row': (card['id'], parsed['id'], card['task_id'],
                    card['operator_session_id'], card['status'],
                    jsonb(card['card_snapshot']), jsonb(card['services']),
                    card['submitted_at'],
                    source_cards[card['id']].get('dds_by_id') or resolve_name(card['dds_by'], 'student'), card['routed_at']),
            'actions': [(card['id'], code, text, at or _now())
                        for code, text, at in card['service_actions']],
        })
    return {'training': row, 'scenarios': parsed['scenario_ids'],
            'participants': participants, 'cards': cards}


def training_from_row(row: dict, scenarios: Optional[List[dict]] = None,
                      participants: Optional[List[dict]] = None,
                      cards: Optional[List[dict]] = None,
                      actions: Optional[List[dict]] = None,
                      name_of: Optional[Callable] = None) -> dict:
    """training row + child rows -> training document (file format)."""
    participant_rows = participants or []
    card_rows = cards or []
    action_rows = {(a.get('training_card_id'), a.get('service_code')): a
                   for a in (actions or [])}
    card_docs = []
    for card in card_rows:
        service_actions = {}
        for code in sorted({a.get('service_code') for a in action_rows.values()
                            if a.get('training_card_id') == card['id']}):
            action = action_rows.get((card['id'], code))
            if action:
                service_actions[code] = {'text': action.get('text') or '',
                                         'at': load_ts(action.get('at'))}
        item = {
            'id': card['id'],
            'task_id': card.get('task_id'),
            'operator_session_id': card.get('operator_session_id'),
            'status': card.get('status', 'awaiting_call'),
            'card': _dict(card.get('card_snapshot')) or None,
            'services': _list(card.get('services')),
            'submitted_at': load_ts(card.get('submitted_at')),
            'routed_at': load_ts(card.get('routed_at')),
            'service_actions': service_actions,
        }
        if card.get('dds_by_id') is not None:
            item['dds_by_id'] = int(card['dds_by_id'])
            item['dds_by'] = name_of(card['dds_by_id']) if name_of else None
        card_docs.append(item)

    doc = {
        'id': row['id'],
        'title': row.get('title') or '',
        'description': row.get('description') or '',
        'status': row.get('status', 'prepared'),
        'mode': row.get('mode', 'training'),
        'seconds': _as_int(row.get('seconds')),
        'difficulty': row.get('difficulty', 'easy'),
        'teacher': name_of(row.get('teacher_id')) if name_of else None,
        'teacher_id': int(row['teacher_id']) if row.get('teacher_id') is not None else None,
        'group': row.get('group_name'),
        'scenario_ids': [s['scenario_id'] for s in (scenarios or [])],
        'participants': [
            {'student': name_of(p.get('user_id')) if name_of else None,
             'user_id': int(p['user_id']) if p.get('user_id') is not None else None,
             'role': p.get('role', 'operator'),
             'service': p.get('service_code') or ''}
            for p in participant_rows],
        'cards': card_docs,
        'created_at': load_ts(row.get('created_at')),
        'started_at': load_ts(row.get('started_at')),
        'completed_at': load_ts(row.get('completed_at')),
        'updated_at': load_ts(row.get('updated_at')),
    }
    return doc


# ------------------------------------------------------------ material rows


def material_to_rows(doc: dict, resolve_name: Callable) -> tuple:
    """material document -> material row tuple."""
    identifier = doc.get('id')
    if not isinstance(identifier, str) or not identifier.startswith('material-'):
        raise ValueError('Неверный идентификатор материала.')
    return (identifier, str(doc.get('title') or ''),
            str(doc.get('url') or ''), str(doc.get('description') or ''),
            doc.get('teacher_id') or resolve_name(doc.get('teacher'), 'teacher'),
            doc.get('created_at') or _now())


def material_from_row(row: dict, name_of: Optional[Callable] = None) -> dict:
    """material row -> material document."""
    doc = {
        'id': row['id'],
        'title': row.get('title') or '',
        'url': row.get('url') or '',
        'description': row.get('description') or '',
        'teacher': name_of(row.get('teacher_id')) if name_of else None,
        'created_at': load_ts(row.get('created_at')),
    }
    if row.get('teacher_id') is not None:
        doc['teacher_id'] = int(row['teacher_id'])
    return doc