"""Local teacher workspace. No database or production role authorization."""
import re
from datetime import datetime, timezone
from ai_core import FIELDS, VERDICTS, LEVELS, require_text, now
from dds import ACTION_LABELS
from incident_training import LABELS as INCIDENT_LABELS
from card_factory import CATALOG, CATEGORIES

CLASS_CATEGORIES = {row['id']: str(row.get('category') or '') for row in CATALOG}


def session(engine, identifier):
    value = engine.load(identifier)
    if not value['id'].startswith('s-'):
        raise ValueError('Выберите работу обучающегося.')
    return value


def overview(engine, teacher=None):
    repository = getattr(getattr(engine, 'storage', None), '_repo', None)
    if repository is not None and hasattr(repository, 'list_sessions_summary'):
        rows = []
        for summary in repository.list_sessions_summary(teacher=teacher):
            row = {key: summary.get(key) for key in (
                'id', 'student', 'title', 'task_id', 'status', 'level', 'workflow',
                'created_at', 'updated_at', 'duration_seconds', 'filled', 'total_fields',
                'grade', 'machine_percent', 'ai_percent', 'final_percent', 'ai_remarks',
                'training', 'comment')}
            class_ids = summary.get('category_class_ids') or []
            row['category'] = next(
                (CLASS_CATEGORIES.get(cid, '') for cid in class_ids
                 if CLASS_CATEGORIES.get(cid)), '')
            rows.append(row)
        return {'sessions': rows, 'fields': FIELDS,
                'labels': INCIDENT_LABELS | FIELDS | ACTION_LABELS,
                'verdicts': VERDICTS, 'categories': CATEGORIES,
                'tasks': [{'id': t['id'], 'title': t['title'], 'status': t['status'],
                           'level': t['level'], 'workflow': t['workflow'],
                           'format': t.get('format')}
                          for t in engine.list_items('t', teacher=teacher)]}
    rows = []
    for s in engine.list_items('s', teacher=teacher):
        end = datetime.fromisoformat(s['submitted_at']) if s.get('submitted_at') else datetime.now(timezone.utc)
        start = datetime.fromisoformat(s.get('activated_at') or s['created_at'])
        seconds = 0 if s.get('status') == 'queued' else max(0, int((end - start).total_seconds()))
        assessment = s.get('assessment')
        rows.append({
            'id': s['id'], 'student': s['student'], 'title': s['task']['title'],
            'task_id': s['task']['id'], 'status': s['status'], 'level': s.get('effective_level', s['task']['level']),
            'category': next((CLASS_CATEGORIES.get(cid,'') for cid in (s['task'].get('incident_source') or {}).get('class_ids',[]) if CLASS_CATEGORIES.get(cid)), ''),
            'workflow': s['task'].get('workflow', 'caller'), 'created_at': s['created_at'],
            'updated_at': s.get('updated_at'), 'duration_seconds': seconds,
            'filled': sum(bool(v.strip()) for v in s['card'].values()), 'total_fields': len(s['card']),
            'grade': (s.get('teacher_decision') or {}).get('grade'),
            'machine_percent': (s.get('machine_assessment') or {}).get('percent'),
            'ai_percent': (s.get('assessment') or {}).get('percent'),
            'final_percent': (s.get('teacher_decision') or {}).get('percent'),
            'ai_remarks': (sum(r['verdict'] in ('partial', 'incorrect', 'missing')
                               for r in assessment['fields'].values()) if assessment else None),
            'training': s.get('training'), 'comment': s.get('teacher_note', ''),
        })
    return {'sessions': rows, 'fields': FIELDS, 'labels': INCIDENT_LABELS | FIELDS | ACTION_LABELS, 'verdicts': VERDICTS,
            'categories': CATEGORIES,
            'tasks': [{k: t.get(k) for k in ('id', 'title', 'status', 'level', 'workflow', 'format')}
                      for t in engine.list_items('t', teacher=teacher)]}


def dispatch(engine, action, p):
    if action == 'teacher_dashboard':
        auth_user = p.get('_auth_user')
        teacher_id = (p.get('_owner_id') or (auth_user.get('id') if auth_user
                                             and auth_user.get('role') == 'teacher'
                                             else None))
        return overview(engine, teacher=teacher_id)
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
        if p.get('_owner_id') is not None:
            s['teacher_note_by_id'] = p['_owner_id']
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
        from scoring import compare
        s['machine_assessment'] = compare(s)
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
        teacher_id = p.get('_owner_id')
        repository = getattr(getattr(engine, 'storage', None), '_repo', None)
        if teacher_id is not None:
            if repository is None or not hasattr(repository, 'resolve_students'):
                raise ValueError('Для назначения по JWT требуется база пользователей.')
            assigned = list(zip(students, repository.resolve_students(students)))
            if len({user_id for _, user_id in assigned}) != len(assigned):
                raise ValueError('Обучающийся указан повторно.')
        else:
            assigned = [(student, None) for student in students]
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
        existing = {(s['task']['id'], s.get('student_id') if teacher_id is not None else s['student']): s['id']
                    for s in engine.list_items('s', teacher=teacher_id)
                    if (s.get('training') or {}).get('plan_id') == key}
        result = []
        for index, task in enumerate(tasks, 1):
            for student, student_id in assigned:
                pair = (task['id'], student_id if teacher_id is not None else student)
                if pair in existing:
                    result.append(existing[pair])
                    continue
                s = engine.start(task['id'], student, training={
                    'plan_id': key, 'scenario_id': scenario_id, 'title': title, 'group': group,
                    'seconds': limit, 'teacher': teacher, 'teacher_id': teacher_id, 'mode': mode,
                    'coaching_delay_seconds': 10 if mode == 'training' else 0,
                    'card_index': index, 'card_total': len(tasks)}, student_id=student_id)
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
