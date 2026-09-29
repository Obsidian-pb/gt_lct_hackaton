"""Bridge approved workshop cards to the existing file-based training engine.

No reference material is included in the student projection before teacher review.
"""
import copy
import hashlib
import json
import re
from ai_core import now, require_text
import card_factory as cards
import card_caller
import dialogue_gateway

FORMAT = 'incident-v1'
VOICE_IDS = {'ru_RU-irina-medium', 'ru_RU-denis-medium', 'ru_RU-dmitri-medium'}
EXTRA = {'_report': 'Описание со слов заявителя', '_class_ids': 'Типы происшествия',
         '_services': 'Привлекаемые службы', '_main_service': 'Главная служба', '_flags': 'Признаки происшествия'}
LABELS = cards.LABELS | EXTRA
LEGACY_MAP = {'address_text': 'address', 'description': 'incident', 'people': 'people',
              'injured': 'injured', 'floors': 'floors', 'entrance': 'entrance', 'access': 'access'}


def is_full(task):
    return task.get('format') == FORMAT


def publish(engine, request):
    approved = cards.approve(request)
    scenario = card_caller.validate_scenario(request.get('caller_scenario'))
    # The legacy dialogue engine still expects a profile token, but difficulty is
    # no longer a teacher/learner setting. Keep one neutral internal profile.
    level = 'medium'
    content, ref = approved['content'], approved['reference']
    opening = request.get('opening') or re.split(r'(?<=[.!?…])\s+', content['report'].strip())[0][:500]
    opening = require_text(opening, 'Первая реплика заявителя', 2000)
    voice_id = request.get('voice_id') or 'ru_RU-irina-medium'
    if voice_id not in VOICE_IDS:
        raise ValueError('Выберите доступный голос заявителя.')
    # Stable content identity: retries never duplicate tasks; sessions retain their own snapshot.
    identity = json.dumps([content, ref, scenario, opening, level, voice_id], ensure_ascii=False, sort_keys=True)
    identifier = 't-' + hashlib.sha256(identity.encode()).hexdigest()[:12]
    if engine.exists(identifier):
        return {'task_id': identifier}
    expected = {key: row['value'] for key, row in ref['answer']['expected_fields'].items()}
    expected.update(_class_ids=json.dumps(content['class_ids'], ensure_ascii=False),
                    _services=json.dumps(content['services'], ensure_ascii=False),
                    _main_service=content['main_service'], _flags=json.dumps(content.get('flags', {}), ensure_ascii=False))
    task = {'id': identifier, 'format': FORMAT, 'title': content['title'], 'status': 'approved',
            'workflow': 'caller', 'level': level, 'created_at': now(), 'approved_at': now(),
            'approved_by': approved['review']['teacher'], 'opening': opening,
            'persona': 'Заявитель учебного звонка 112', 'source': 'approved-workshop-card', 'voice_id': voice_id,
            'field_labels': {k: LABELS[k] for k in expected},
            'fields': {k: {'truth': value, 'known': value, 'expected': value,
                           'criterion': 'Сохранить смысл утверждённого эталона и неопределённость. Не выдумывать неизвестные сведения.', 'weight': 1}
                       for k, value in expected.items()},
            'incident_source': copy.deepcopy(content), 'incident_reference': copy.deepcopy(ref),
            'caller_scenario': scenario}
    engine.save(task)
    return {'task_id': identifier}


def initialize(session):
    task = session['task']
    session['card'] = {key: '' for key in LABELS}
    session['card'].update(phone_aon=task['incident_source']['fields']['phone_aon'],
                           external_number=session['id'], registered_by=session['student'],
                           _class_ids='[]', _services='[]', _flags='{}')
    session['callback_disclosed'] = False


def ask(engine, session, question, source, student_fields=None):
    turns = [{'role': row['role'], 'text': row['text']} for row in session['history'][1:]]
    task = session['task']
    # The browser may send unsaved learner edits so the caller can react to the
    # learner's current context. They are never trusted facts and are never saved
    # by this operation. If an older client omits them, use the last saved card.
    current_fields = session['card'] if student_fields is None else student_fields
    result = dialogue_gateway.ask(
        content=task['incident_source'],
        caller_scenario=task['caller_scenario'],
        turns=turns,
        question=question,
        student_fields=current_fields,
    )
    session['history'].extend([{'id': len(session['history'])+1, 'role': 'dispatcher', 'text': question, 'source': source},
                               {'id': len(session['history'])+2, 'role': 'caller', 'text': result['reply']}])
    session['callback_disclosed'] = session['callback_disclosed'] or result['callback_disclosed']
    engine.save(session)
    return result['reply']


def save_card(engine, session, value, submit=False):
    if not isinstance(value, dict) or set(value) != set(LABELS) or any(not isinstance(v, str) or len(v)>3000 for v in value.values()):
        raise ValueError('Неверная структура полной карточки. Обновите страницу.')
    for key in ('phone_aon', 'external_number', 'registered_by'):
        if value[key] != session['card'][key]:
            raise ValueError('Автоматические регистрационные поля изменять нельзя.')
    revealed = {row.get('field') for row in session.get('training_reveals', []) if isinstance(row, dict)}
    if value['phone_callback'] and not session['callback_disclosed'] and 'phone_callback' not in revealed:
        raise ValueError('Сначала спросите у заявителя номер для обратного звонка.')
    try:
        content = {'title': session['task']['title'], 'report': value['_report'],
            'fields': {k: value[k] for k in cards.LABELS}, 'class_ids': json.loads(value['_class_ids']),
            'services': json.loads(value['_services']), 'main_service': value['_main_service'], 'flags': json.loads(value['_flags'])}
        if submit:
            cards.validate_content(content)
        else:
            # A learner must be able to save an incomplete card during a call.
            # Structure, codes and size are checked here; completeness is checked
            # on submission so the server retains useful timeout drafts.
            if any(code not in cards.SERVICES for code in content['services']):
                raise ValueError('Выбрана неизвестная служба.')
            if any(code not in {r['id'] for r in cards.CATALOG + cards.LEGACY_CATALOG} for code in content['class_ids']):
                raise ValueError('Выбран неизвестный тип происшествия.')
            if content['main_service'] and content['main_service'] not in content['services']:
                raise ValueError('Основная служба должна входить в состав привлекаемых.')
            cards.validate_flags(content['flags'])
    except (ValueError, TypeError, KeyError):
        raise ValueError('Проверьте поля, координаты, тип происшествия и службы.') from None
    for key, text in value.items():
        if text != session['card'][key]:
            session['card_edits'].append({'field': key, 'before': session['card'][key], 'after': text, 'at': now()})
    session['card'] = copy.deepcopy(value)
    if submit:
        session.update(status='submitted', submitted_at=now())
        from scoring import compare
        session['machine_assessment'] = compare(session)
    engine.save(session)


def public_metadata(session):
    return {'format': FORMAT, 'field_labels': LABELS, 'callback_disclosed': session['callback_disclosed'], 'service_labels': cards.SERVICES,
            'voice_id': session['task'].get('voice_id', 'ru_RU-irina-medium')}


def legacy_projection(session, view):
    """Old exercises retain their seven approved criteria but use the full worksheet.

    New supplemental learner notes are stored separately, never promoted into an
    allegedly teacher-approved reference. No splitting/guessing of an old address.
    """
    values = {key: '' for key in LABELS}
    values.update(_class_ids='[]', _services='[]', _flags='{}')
    values.update(session.get('incident_draft', {}))
    values.update({key: session['card'][old] for key, old in LEGACY_MAP.items()})
    view.update(format=FORMAT, card=values, field_labels=LABELS, callback_disclosed=True,
                service_labels=cards.SERVICES, legacy_map=LEGACY_MAP,
                legacy_notice='Ранее созданный сценарий: эталон охватывает семь исходных полей. Дополнительные поля сохраняются для просмотра преподавателем.')
    if view.get('reference'):
        view['reference'] = {key: view['reference'][old] for key, old in LEGACY_MAP.items()}
    if view.get('result'):
        view['result']['fields'] = {key: view['result']['fields'][old] for key, old in LEGACY_MAP.items()}
    return view


def save_legacy_card(engine, session, value, submit=False):
    # Validate with the same catalog and coordinate rules as new full cards.
    temporary = copy.deepcopy(session)
    temporary['card'] = {k: '' for k in LABELS}
    temporary['card'].update(session.get('incident_draft', {}))
    temporary['callback_disclosed'] = True
    # save_card performs one atomic save; restore the original seven-field shape
    # through a small in-memory writer before writing the complete session.
    class Sink:
        def save(self, item):
            pass
    save_card(Sink(), temporary, value, submit)
    session['incident_draft'] = copy.deepcopy(value)
    session['card'] = {old: value[key] for key, old in LEGACY_MAP.items()}
    session['card_edits'] = temporary['card_edits']
    if submit:
        session.update(status='submitted', submitted_at=temporary['submitted_at'])
        from scoring import compare
        session['machine_assessment'] = compare(session)
        if session['task'].get('workflow') == 'dds':
            session.update(connection='ended', next_channel='clear')
    engine.save(session)
