"""REST v1 route and input contract, shared with the generated browser client/OpenAPI."""
from dataclasses import dataclass, field
import re

PREFIX = '/api/v1'
TEXT = {'type': 'string'}
OBJECT = {'type': 'object'}
BOOL = {'type': 'boolean'}
STRINGS = {'type': 'array', 'items': TEXT}
COMMON = {
    'student': {'type': 'string', 'minLength': 1, 'maxLength': 160},
    'teacher': {'type': 'string', 'minLength': 1, 'maxLength': 160},
    'id': {'type': 'string', 'pattern': '^[ts]-[0-9a-f]{12}$'},
    'task_id': {'type': 'string', 'pattern': '^t-[0-9a-f]{12}$'},
    'full_form': BOOL, 'sample': BOOL, 'publish_training': BOOL,
    'level': {'type': 'string', 'enum': ['easy', 'medium', 'hard']},
    'workflow': {'type': 'string', 'enum': ['caller', 'dds']},
    'question': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
    'source': {'type': 'string', 'enum': ['text', 'voice']},
    'card': {'type': 'object', 'additionalProperties': TEXT},
    'fields': OBJECT, 'content': OBJECT, 'reference': OBJECT, 'decisions': OBJECT,
    'caller_scenario': OBJECT, 'flags': OBJECT, 'classification': OBJECT,
    'reference_checked': BOOL, 'note': {'type':'string','maxLength':1999},
    'text': {'type':'string','minLength':1,'maxLength':1200},
    'turns': {'type': 'array', 'items': OBJECT},
    'task_ids': STRINGS, 'students': STRINGS, 'recent_titles': STRINGS,
    'seconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400},
    'grade': {'type': 'integer', 'minimum': 2, 'maximum': 5},
    'index': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'total': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'comment': {'type': 'string', 'maxLength': 1999},
}


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    action: str
    summary: str
    required: tuple = ()
    optional: tuple = ()
    operation: str = ''
    status: int = 200
    storage: bool = True
    # Complex workshop/task payloads retain extensible fields; domain validators
    # still enforce their full schemas before modifying stored training data.
    extensible: bool = False

    @property
    def parameters(self):
        return tuple(re.findall(r'\{(\w+)\}', self.path))

    @property
    def operation_id(self):
        return self.action + ('_' + self.operation if self.operation else '')


ROUTES = [
    Route('GET', '/metadata', 'home', 'Общая информация и справочники'),
    Route('GET', '/classifier', 'card_meta', 'Классификатор, службы и поля карточки', storage=False),
    Route('POST', '/ai/checks', 'ai_status', 'Проверка доступа к провайдеру ИИ', storage=False),
    Route('GET', '/speech/status', 'tts_status', 'Доступность локальной озвучки', storage=False),
    Route('POST', '/speech/syntheses', 'tts_synthesize', 'Озвучить текст', ('text',), ('voice',), storage=False),
    Route('POST', '/cards/generations', 'card_generate', 'Сгенерировать учебную карточку', (), ('topic','index','total','category','classification','flags','location','recent_titles','incident_class'), storage=False, extensible=True),
    Route('POST', '/cards/reference-previews', 'card_reference', 'Сформировать эталон карточки', ('content',), storage=False, extensible=True),
    Route('POST', '/cards/caller-replies', 'card_caller', 'Реплика заявителя для предпросмотра', ('content','caller_scenario','question'), ('turns','level'), storage=False),
    Route('POST', '/cards/validations', 'card_validate', 'Проверить поля карточки', ('content',), storage=False),
    Route('POST', '/cards/approvals', 'card_approve', 'Проверить и утвердить карточку', ('content','teacher'), ('reference','publish_training','reference_checked','caller_scenario','note','opening','level'), extensible=True),
    Route('POST', '/cards/publications', 'card_publish', 'Опубликовать карточку для тренировок', ('content','teacher','reference','caller_scenario'), ('reference_checked','note','opening','level'), extensible=True),
    Route('GET', '/tasks', 'tasks', 'Список заданий преподавателя'),
    Route('POST', '/tasks', 'create', 'Создать черновик задания', ('level',), ('topic','workflow','sample'), status=201),
    Route('GET', '/tasks/{id}', 'teacher_task', 'Задание и эталон для преподавателя'),
    Route('PUT', '/tasks/{id}', 'save_task', 'Сохранить редактируемые поля черновика', ('title','opening','persona','fields'), (), extensible=True),
    Route('POST', '/tasks/{id}/approvals', 'approve', 'Утвердить задание', ('teacher',)),
    Route('GET', '/teacher/overview', 'teacher_overview', 'Краткий обзор преподавателя'),
    Route('GET', '/teacher/dashboard', 'teacher_dashboard', 'Мониторинг учебных сессий'),
    Route('GET', '/teacher/sessions/{id}', 'teacher_session', 'Полная работа для преподавателя'),
    Route('PUT', '/teacher/sessions/{id}/note', 'teacher_note', 'Сохранить заметку преподавателя', ('teacher','comment')),
    Route('POST', '/teacher/sessions/{id}/completions', 'teacher_finish', 'Досрочно завершить работу', ('teacher','reason')),
    Route('POST', '/training-plans', 'teacher_launch', 'Назначить набор карточек обучающимся', ('plan_id','title','teacher','students','task_ids'), ('group','seconds','mode','scenario_id')),
    Route('GET', '/students/{student}', 'student_overview', 'Доступные задания и работы обучающегося'),
    Route('POST', '/students/{student}/sessions', 'student_start', 'Начать или продолжить выбранное задание', ('task_id',), ('full_form',)),
    Route('GET', '/students/{student}/sessions/{id}', 'student_action', 'Карточка и диалог обучающегося', (), ('full_form',), operation='student'),
    Route('POST', '/students/{student}/sessions/{id}/messages', 'student_action', 'Задать вопрос заявителю', ('question',), ('source','full_form'), operation='ask'),
    Route('POST', '/students/{student}/sessions/{id}/hints', 'student_action', 'Получить учебную подсказку', (), ('card','full_form'), operation='nudge'),
    Route('PUT', '/students/{student}/sessions/{id}/card', 'student_action', 'Сохранить карточку обучающегося', ('card',), ('full_form',), operation='save_card'),
    Route('POST', '/students/{student}/sessions/{id}/submissions', 'student_action', 'Сдать карточку и перейти к следующей', ('card',), ('full_form',), operation='submit'),
    Route('POST', '/students/{student}/sessions/{id}/connections', 'student_action', 'Подключить службу ДДС', (), ('full_form',), operation='connect'),
    Route('PUT', '/students/{student}/sessions/{id}/channel', 'student_action', 'Выбрать канал ДДС', ('mode',), ('full_form',), operation='channel'),
    # Existing prototype screens have simpler projections. Keep them distinct.
    Route('POST', '/sessions', 'start', 'Начать назначенное задание учебного прототипа', ('student',), ('workflow',), status=201),
    Route('GET', '/sessions', 'sessions', 'Работы обучающегося в учебном прототипе', ('student',)),
    Route('GET', '/sessions/{id}', 'student', 'Карточка учебного прототипа'),
    Route('POST', '/sessions/{id}/messages', 'ask', 'Вопрос в учебном прототипе', ('question',), ('source',)),
    Route('POST', '/sessions/{id}/hints', 'hint', 'Подсказка в учебном прототипе'),
    Route('PUT', '/sessions/{id}/card', 'save_card', 'Сохранить карточку прототипа', ('card',), ('full_form',)),
    Route('POST', '/sessions/{id}/submissions', 'submit', 'Сдать карточку прототипа', ('card',), ('full_form',)),
    Route('POST', '/sessions/{id}/connections', 'connect', 'Подключение к ДДС в прототипе'),
    Route('PUT', '/sessions/{id}/channel', 'channel', 'Канал ДДС в прототипе', ('mode',)),
    Route('POST', '/sessions/{id}/assessments', 'assess', 'Предварительная оценка ИИ'),
    Route('GET', '/works', 'works', 'Сданные работы'),
    Route('GET', '/works/{id}', 'review', 'Работа на проверку преподавателю'),
    Route('PUT', '/works/{id}/decision', 'finalize', 'Итоговое решение преподавателя', ('teacher','grade','conclusion','decisions')),
    Route('GET', '/geo/addresses', 'geo_addresses', 'Локальные адреса OSM', (), ('q','limit'), storage=False),
    Route('GET', '/geo/map', 'geo_map', 'Локальные геоданные карты OSM', storage=False),
]


def input_schema(route):
    names = (*route.required, *route.optional)
    return {'type': 'object', 'properties': {name: COMMON.get(name, TEXT) for name in names},
            'required': list(route.required), 'additionalProperties': route.extensible}


def openapi():
    error = {'description': 'Ошибка запроса', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'}}}}
    paths = {}
    for r in ROUTES:
        params = [{'name': n, 'in': 'path', 'required': True, 'schema': COMMON[n]} for n in r.parameters]
        operation = {'operationId': r.operation_id, 'summary': r.summary,
                     'tags': [r.path.split('/')[1]], 'parameters': params,
                     'responses': {str(r.status): {'description': 'Успешно; data содержит результат операции', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Success'}}}},
                                   **{str(code): error for code in (400,401,403,404,405,409,413,415,422,500,502)}}}
        if r.method == 'GET':
            params.extend({'name': n, 'in': 'query', 'required': n in r.required, 'schema': COMMON.get(n, TEXT)} for n in (*r.required,*r.optional))
        else:
            operation['requestBody'] = {'required': bool(r.required), 'content': {'application/json': {'schema': input_schema(r)}}}
        paths.setdefault(r.path,{})[r.method.lower()] = operation
    paths['/health'] = {'get': {'operationId':'health', 'summary':'Проверка сервера без обращения к ИИ', 'security':[], 'responses':{'200':{'description':'API запущен','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Success'}}}}}}}
    paths['/openapi.json'] = {'get': {'operationId':'openapi_document', 'summary':'Документ OpenAPI', 'security':[], 'responses':{'200':{'description':'Спецификация OpenAPI без оболочки data','content':{'application/json':{'schema':{'type':'object'}}}}}}}
    return {'openapi':'3.1.1', 'info':{'title':'Учебный симулятор 112 — REST API','version':'1.0.0',
            'description':'Локальный интеграционный API. Ключ ИИ остаётся на сервере. Ролевая авторизация команды подключается отдельно; общий токен не удостоверяет личность обучающегося.'},
            'servers':[{'url':PREFIX}], 'security':[{'LocalUIToken':[]},{'IntegrationToken':[]}],
            'paths':paths,'components':{'securitySchemes':{
                'LocalUIToken':{'type':'apiKey','in':'header','name':'X-UI-Token','description':'Временный токен локального интерфейса.'},
                'IntegrationToken':{'type':'http','scheme':'bearer','description':'Отдельный TRAINING_API_TOKEN, не ключ AITUNNEL/OpenAI.'}},
                'schemas':{'Success':{'type':'object','required':['data','request_id'],'properties':{'data':{},'request_id':TEXT}},
                           'Error':{'type':'object','required':['error','request_id'],'properties':{'request_id':TEXT,'error':{'type':'object','required':['code','message'],'properties':{'code':TEXT,'message':TEXT,'details':OBJECT}}}}}}}
