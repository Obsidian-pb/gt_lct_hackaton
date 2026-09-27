"""Local teacher workspace. No database or production role authorization."""
import re
from datetime import datetime, timezone
from ai_core import FIELDS, VERDICTS, LEVELS, require_text, now
from dds import ACTION_LABELS
from incident_training import LABELS as INCIDENT_LABELS


def session(engine, identifier):
    value = engine.load(identifier)
    if not value['id'].startswith('s-'):
        raise ValueError('Выберите работу обучающегося.')
    return value


def overview(engine):
    rows = []
    for s in engine.list_items('s'):
        end = datetime.fromisoformat(s['submitted_at']) if s.get('submitted_at') else datetime.now(timezone.utc)
        start = datetime.fromisoformat(s.get('activated_at') or s['created_at'])
        seconds = 0 if s.get('status') == 'queued' else max(0, int((end - start).total_seconds()))
        assessment = s.get('assessment')
        rows.append({
            'id': s['id'], 'student': s['student'], 'title': s['task']['title'],
            'task_id': s['task']['id'], 'status': s['status'], 'level': s.get('effective_level', s['task']['level']),
            'workflow': s['task'].get('workflow', 'caller'), 'created_at': s['created_at'],
            'updated_at': s.get('updated_at'), 'duration_seconds': seconds,
            'filled': sum(bool(v.strip()) for v in s['card'].values()), 'total_fields': len(s['card']),
            'grade': (s.get('teacher_decision') or {}).get('grade'),
            'ai_remarks': (sum(r['verdict'] in ('partial', 'incorrect', 'missing')
                               for r in assessment['fields'].values()) if assessment else None),
            'training': s.get('training'), 'comment': s.get('teacher_note', ''),
        })
    return {'sessions': rows, 'fields': FIELDS, 'labels': INCIDENT_LABELS | FIELDS | ACTION_LABELS, 'verdicts': VERDICTS,
            'tasks': [{k: t.get(k) for k in ('id', 'title', 'status', 'level', 'workflow', 'format')}
                      for t in engine.list_items('t')]}


def dispatch(engine, action, p):
    if action == 'teacher_dashboard':
        return overview(engine)
    if action == 'teacher_session':
        return session(engine, p['id'])
    if action == 'teacher_task':
        task = engine.load(p['id'])
        if not task['id'].startswith('t-'):
            raise ValueError('Выберите сценарий.')
        return task
    if action == 'teacher_note':
        s = session(engine, p['id'])
        note = p.get('comment')
        if not isinstance(note, str) or len(note) > 1999:
            raise ValueError('Комментарий: не более 1999 символов.')
        s.update(teacher_note=note, teacher_note_by=require_text(p.get('teacher'), 'Преподаватель', 160),
                 teacher_note_at=now())
        engine.save(s)
        return {'saved': True}
    if action == 'teacher_finish':
        s = session(engine, p['id'])
        reason = require_text(p.get('reason'), 'Причина завершения', 1999)
        teacher = require_text(p.get('teacher'), 'Преподаватель', 160)
        if s['status'] != 'active':
            raise ValueError('Работа уже завершена.')
        # Submit the last saved card; never fabricate missing learner answers.
        s.update(status='submitted', submitted_at=now(),
                 forced_finish={'teacher': teacher, 'reason': reason, 'at': now()})
        engine.save(s)
        return {'status': 'submitted'}
    if action == 'teacher_launch':
        key = p.get('plan_id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,80}', key):
            raise ValueError('Неверный номер плана.')
        title = require_text(p.get('title'), 'Название', 160)
        group = p.get('group', '')
        if not isinstance(group, str) or len(group) > 160:
            raise ValueError('Название группы: не более 160 символов.')
        teacher = require_text(p.get('teacher'), 'Преподаватель', 160)
        limit = p.get('seconds', 0)
        mode = p.get('mode', 'training')
        if mode not in ('training', 'testing'):
            raise ValueError('Неизвестный режим тренировки.')
        if type(limit) is not int or not 0 <= limit <= 86400:
            raise ValueError('Ориентир времени: от 0 до 86400 секунд.')
        ids, students = p.get('task_ids'), p.get('students')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids):
            raise ValueError('Выберите от 1 до 100 карточек.')
        if len(set(ids)) != len(ids):
            raise ValueError('Карточки не должны повторяться.')
        if not isinstance(students, list) or not 1 <= len(students) <= 100:
            raise ValueError('Укажите от 1 до 100 обучающихся.')
        students = list(dict.fromkeys(require_text(x, 'Обучающийся', 160) for x in students))
        if len(ids) * len(students) > 5000:
            raise ValueError('За одно назначение можно создать не более 5000 работ.')
        tasks = [engine.load(i) for i in ids]
        if any(not t['id'].startswith('t-') or t['status'] != 'approved' for t in tasks):
            raise ValueError('Сначала утвердите каждую карточку и её эталон.')
        scenario_id = p.get('scenario_id', key)
        if not isinstance(scenario_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{8,80}', scenario_id):
            raise ValueError('Неверный номер сценария.')
        # Learner difficulty settings were removed. Training now has only two modes:
        # training (automatic inactivity nudges) and testing (no hints).
        # Validate the complete request before starting any session. Retrying a launch
        # reuses its sessions, even if the first response was lost.
        existing = {(s['task']['id'], s['student']): s['id'] for s in engine.list_items('s')
                    if (s.get('training') or {}).get('plan_id') == key}
        result = []
        for index, task in enumerate(tasks, 1):
            for student in students:
                pair = (task['id'], student)
                if pair in existing:
                    result.append(existing[pair])
                    continue
                s = engine.start(task['id'], student, training={
                    'plan_id': key, 'scenario_id': scenario_id, 'title': title, 'group': group,
                    'seconds': limit, 'teacher': teacher, 'mode': mode,
                    'coaching_delay_seconds': 10 if mode == 'training' else 0,
                    'card_index': index, 'card_total': len(tasks)})
                s['effective_level'] = 'medium'
                s['training_reveals'] = []
                if index > 1:
                    s['status'] = 'queued'
                else:
                    s['activated_at'] = now()
                engine.save(s)
                result.append(s['id'])
        return {'session_ids': result, 'scenario_id': scenario_id, 'card_total': len(tasks), 'mode': mode}
    raise ValueError('Неизвестное действие преподавателя.')
