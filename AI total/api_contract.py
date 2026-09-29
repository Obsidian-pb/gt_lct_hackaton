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
    'full_form': BOOL, 'sample': BOOL, 'publish_training': BOOL, 'force': BOOL,
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
    'user_ids': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}},
    'seconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400},
    'grade': {'type': 'integer', 'minimum': 2, 'maximum': 5},
    'percent': {'type': 'integer', 'minimum': 0, 'maximum': 100},
    'index': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'total': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
    'comment': {'type': 'string', 'maxLength': 1999},
    'resource_id': {'type': 'string', 'pattern': '^(scenario|training)-[0-9a-f]{12}$'},
    'card_id': {'type': 'string', 'pattern': '^card-[0-9a-f]{12}$'},
    'scenario_ids': STRINGS, 'participants': {'type': 'array', 'items': OBJECT},
    'task_difficulties': OBJECT,
    'services': STRINGS, 'updates': OBJECT,
    'difficulty': {'type': 'string', 'enum': ['easy','medium','hard','adaptive']},
    # --- Этап 2.2: справочники (классификатор, службы, гео) ---
    'service_code': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'pattern': '^[0-9A-Za-z_-]+$'},
    'category_id': {'type': 'string', 'pattern': '^\\d+$'},
    'entry_id': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'entry_service_id': {'type': 'string', 'pattern': '^\\d+$'},
    'address_id': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'name': {'type': 'string', 'minLength': 1, 'maxLength': 255},
    'group_name': {'type': 'string', 'maxLength': 255},
    'statistical_group': {'type': 'string', 'maxLength': 255},
    'sign1': {'type': 'string', 'maxLength': 255},
    'sign2': {'type': 'string', 'maxLength': 255},
    'sign3': {'type': 'string', 'maxLength': 255},
    'extra_signs': {'type': 'string', 'maxLength': 255},
    'title': {'type': 'string', 'maxLength': 255},
    'ekp_type': {'type': 'string', 'maxLength': 255},
    'main_service_code': {'type': 'string', 'maxLength': 32},
    'condition_type': {'type': 'string', 'minLength': 1, 'maxLength': 32},
    'condition_text': {'type': 'string', 'maxLength': 1000},
    'value': {'type': 'string', 'maxLength': 1000},
    'is_main': BOOL,
    'street': {'type': 'string', 'maxLength': 255},
    'house': {'type': 'string', 'maxLength': 64},
    'kind': {'type': 'string', 'enum': ['building', 'street']},
    'lat': {'type': 'number'},
    'lon': {'type': 'number'},
    'point': OBJECT,
    'q': {'type': 'string', 'maxLength': 200},
    # --- Этап 2.1: пользователи и аутентификация ---
    'login': {'type': 'string', 'minLength': 3, 'maxLength': 64, 'pattern': '^[a-z0-9_.-]+$'},
    'password': {'type': 'string', 'minLength': 6, 'maxLength': 128},
    'refresh_token': {'type': 'string', 'minLength': 32, 'maxLength': 200},
    'full_name': {'type': 'string', 'minLength': 1, 'maxLength': 160},
    'role': {'type': 'string', 'enum': ['admin', 'teacher', 'student']},
    'is_active': BOOL,
    'display_name': {'type': 'string', 'maxLength': 160},
    'user_agent': {'type': 'string', 'maxLength': 256},
    'description': {'type': 'string', 'maxLength': 1999},
    'user_id': {'type': 'string', 'pattern': '^\\d+$'},
    'group_id': {'type': 'string', 'pattern': '^\\d+$'},
    'teacher_id': {'type': 'string', 'pattern': '^\\d+$'},
    # --- Этап 5: мастерская карточек (workshop) ---
    'workshop_ref': {'type': 'string', 'minLength': 1, 'maxLength': 64},
    'review': OBJECT, 'cards': {'type': 'array', 'items': OBJECT},
    'author_id': {'type': 'string', 'pattern': '^\\d+$'},
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
    # Required auth level for the route: '' = legacy tokens only,
    # 'user' = any authenticated JWT user, 'admin'/'teacher'/'student' = role.
    auth: str = ''

    @property
    def parameters(self):
        return tuple(re.findall(r'\{(\w+)\}', self.path))

    @property
    def operation_id(self):
        return self.action + ('_' + self.operation if self.operation else '')


ROUTES = [
    Route('GET', '/materials', 'materials_list', 'Методические материалы', auth='teacher'),
    Route('POST', '/materials', 'materials_add', 'Добавить ссылку на методический материал', ('title','url','teacher'), ('description',), status=201, auth='teacher'),
    Route('POST', '/reports/insights', 'reports_insights', 'Обезличенный разбор типичных ошибок группы', (), ('group', 'force'), auth='teacher'),
    Route('GET', '/scenarios', 'scenario_list', 'Утверждённые и черновые учебные сценарии', auth='teacher'),
    Route('POST', '/scenarios', 'scenario_save', 'Сохранить сценарий', ('title','teacher','task_ids'), ('description','task_difficulties'), status=201, auth='teacher'),
    Route('GET', '/scenarios/{resource_id}', 'scenario_get', 'Учебный сценарий', auth='teacher'),
    Route('PUT', '/scenarios/{resource_id}', 'scenario_save', 'Изменить сценарий', ('title','teacher','task_ids'), ('description','task_difficulties'), operation='update', auth='teacher'),
    Route('POST', '/scenarios/{resource_id}/approval', 'scenario_approve', 'Утвердить сценарий', ('teacher',), auth='teacher'),
    Route('DELETE', '/scenarios/{resource_id}', 'scenario_delete', 'Удалить неиспользуемый черновик сценария', auth='teacher'),
    Route('GET', '/trainings', 'training_list', 'Тренировки и статусы', auth='teacher'),
    Route('POST', '/trainings', 'training_save', 'Подготовить тренировку', ('title','teacher','scenario_ids','participants'), ('description','mode','seconds','group','difficulty'), status=201, auth='teacher'),
    Route('GET', '/trainings/{resource_id}', 'training_get', 'Тренировка и карточки', auth='teacher'),
    Route('PUT', '/trainings/{resource_id}', 'training_save', 'Изменить подготовленную тренировку', ('title','teacher','scenario_ids','participants'), ('description','mode','seconds','group','difficulty'), operation='update', auth='teacher'),
    Route('POST', '/trainings/{resource_id}/activation', 'training_activate', 'Активировать тренировку', auth='teacher'),
    Route('POST', '/trainings/{resource_id}/completion', 'training_complete', 'Завершить тренировку', ('teacher',), auth='teacher'),
    Route('DELETE', '/trainings/{resource_id}', 'training_delete', 'Удалить подготовленную тренировку', auth='teacher'),
    Route('GET', '/training-desks/{student}', 'training_desk', 'Рабочее место обучающегося', auth='student'),
    Route('POST', '/trainings/{resource_id}/cards/{card_id}/routing', 'training_route', 'Исправить и направить карточку службам', ('student','services'), ('updates',), auth='student'),
    Route('POST', '/trainings/{resource_id}/cards/{card_id}/actions', 'training_service_action', 'Действие диспетчера службы', ('student','text'), auth='student'),
    Route('GET', '/metadata', 'home', 'Общая информация и справочники', auth='user'),
    Route('GET', '/classifier', 'card_meta', 'Классификатор, службы и поля карточки', storage=False, auth='user'),
    Route('GET', '/services', 'services_list', 'Список доступных служб для учебных ролей', storage=False, auth='user'),
    Route('POST', '/ai/checks', 'ai_status', 'Проверка доступа к провайдеру ИИ', storage=False, auth='user'),
    Route('GET', '/speech/status', 'tts_status', 'Доступность локальной озвучки', storage=False, auth='user'),
    Route('POST', '/speech/syntheses', 'tts_synthesize', 'Озвучить текст', ('text',), ('voice',), storage=False, auth='user'),
    Route('POST', '/cards/generations', 'card_generate', 'Сгенерировать учебную карточку', (), ('topic','index','total','category','classification','flags','location','recent_titles','incident_class'), storage=False, extensible=True, auth='teacher'),
    Route('POST', '/cards/reference-previews', 'card_reference', 'Сформировать эталон карточки', ('content',), storage=False, extensible=True, auth='teacher'),
    Route('POST', '/cards/caller-replies', 'card_caller', 'Реплика заявителя для предпросмотра', ('content','caller_scenario','question'), ('turns','level'), storage=False, auth='teacher'),
    Route('POST', '/cards/validations', 'card_validate', 'Проверить поля карточки', ('content',), storage=False, auth='teacher'),
    Route('POST', '/cards/approvals', 'card_approve', 'Проверить и утвердить карточку', ('content','teacher'), ('reference','publish_training','reference_checked','caller_scenario','note','opening','level'), extensible=True, auth='teacher'),
    Route('POST', '/cards/publications', 'card_publish', 'Опубликовать карточку для тренировок', ('content','teacher','reference','caller_scenario'), ('reference_checked','note','opening','level'), extensible=True, auth='teacher'),
    Route('GET', '/tasks', 'tasks', 'Список заданий преподавателя', auth='teacher'),
    Route('POST', '/tasks', 'create', 'Создать черновик задания', ('level',), ('topic','workflow','sample'), status=201, auth='teacher'),
    Route('GET', '/tasks/{id}', 'teacher_task', 'Задание и эталон для преподавателя', auth='teacher'),
    Route('PUT', '/tasks/{id}', 'save_task', 'Сохранить редактируемые поля черновика', ('title','opening','persona','fields'), (), extensible=True, auth='teacher'),
    Route('POST', '/tasks/{id}/approvals', 'approve', 'Утвердить задание', ('teacher',), auth='teacher'),
    Route('GET', '/teacher/overview', 'teacher_overview', 'Краткий обзор преподавателя', auth='teacher'),
    Route('GET', '/teacher/dashboard', 'teacher_dashboard', 'Мониторинг учебных сессий', auth='teacher'),
    Route('GET', '/teacher/sessions/{id}', 'teacher_session', 'Полная работа для преподавателя', auth='teacher'),
    Route('PUT', '/teacher/sessions/{id}/note', 'teacher_note', 'Сохранить заметку преподавателя', ('teacher','comment'), auth='teacher'),
    Route('POST', '/teacher/sessions/{id}/completions', 'teacher_finish', 'Досрочно завершить работу', ('teacher','reason'), auth='teacher'),
    Route('POST', '/training-plans', 'teacher_launch', 'Назначить набор карточек обучающимся', ('plan_id','title','teacher','students','task_ids'), ('group','seconds','mode','scenario_id'), auth='teacher'),
    Route('GET', '/students/{student}', 'student_overview', 'Доступные задания и работы обучающегося', auth='student'),
    Route('POST', '/students/{student}/sessions', 'student_start', 'Начать или продолжить выбранное задание', ('task_id',), ('full_form',), auth='student'),
    Route('GET', '/students/{student}/sessions/{id}', 'student_action', 'Карточка и диалог обучающегося', (), ('full_form',), operation='student', auth='student'),
    Route('POST', '/students/{student}/sessions/{id}/messages', 'student_action', 'Задать вопрос заявителю', ('question',), ('source','full_form','card'), operation='ask', auth='student'),
    Route('POST', '/students/{student}/sessions/{id}/hints', 'student_action', 'Получить учебную подсказку', (), ('card','full_form'), operation='nudge', auth='student'),
    Route('PUT', '/students/{student}/sessions/{id}/card', 'student_action', 'Сохранить карточку обучающегося', ('card',), ('full_form',), operation='save_card', auth='student'),
    Route('POST', '/students/{student}/sessions/{id}/submissions', 'student_action', 'Сдать карточку и перейти к следующей', ('card',), ('full_form',), operation='submit', auth='student'),
    Route('POST', '/students/{student}/sessions/{id}/acceptance', 'student_action', 'Принять входящий учебный вызов', (), ('full_form',), operation='accept', auth='student'),
    Route('POST', '/students/{student}/sessions/{id}/connections', 'student_action', 'Подключить службу ДДС', (), ('full_form',), operation='connect', auth='student'),
    Route('PUT', '/students/{student}/sessions/{id}/channel', 'student_action', 'Выбрать канал ДДС', ('mode',), ('full_form',), operation='channel', auth='student'),
    # Existing prototype screens have simpler projections. Keep them distinct.
    Route('POST', '/sessions', 'start', 'Начать назначенное задание учебного прототипа', ('student',), ('workflow',), status=201, auth='student'),
    Route('GET', '/sessions', 'sessions', 'Работы обучающегося в учебном прототипе', ('student',), auth='student'),
    Route('GET', '/sessions/{id}', 'student', 'Карточка учебного прототипа', auth='student'),
    Route('POST', '/sessions/{id}/messages', 'ask', 'Вопрос в учебном прототипе', ('question',), ('source','card'), auth='student'),
    Route('POST', '/sessions/{id}/hints', 'hint', 'Подсказка в учебном прототипе', auth='student'),
    Route('PUT', '/sessions/{id}/card', 'save_card', 'Сохранить карточку прототипа', ('card',), ('full_form',), auth='student'),
    Route('POST', '/sessions/{id}/submissions', 'submit', 'Сдать карточку прототипа', ('card',), ('full_form',), auth='student'),
    Route('POST', '/sessions/{id}/connections', 'connect', 'Подключение к ДДС в прототипе', auth='student'),
    Route('PUT', '/sessions/{id}/channel', 'channel', 'Канал ДДС в прототипе', ('mode',), auth='student'),
    Route('POST', '/sessions/{id}/assessments', 'assess', 'Предварительная оценка ИИ', auth='student'),
    Route('GET', '/works', 'works', 'Сданные работы', auth='teacher'),
    Route('GET', '/works/{id}', 'review', 'Работа на проверку преподавателю', auth='teacher'),
    Route('PUT', '/works/{id}/decision', 'finalize', 'Итоговое решение преподавателя', ('teacher','grade','conclusion','decisions'), auth='teacher'),
    Route('PUT', '/works/{id}/percentage-decision', 'finalize_percent', 'Итоговая оценка преподавателя 0–100%, без обязательного вызова ИИ', ('teacher','percent','conclusion','decisions'), auth='teacher'),
    Route('GET', '/geo/addresses', 'geo_addresses', 'Локальные адреса OSM', (), ('q','limit'), storage=False),
    Route('GET', '/geo/map', 'geo_map', 'Локальные геоданные карты OSM', storage=False),
    # --- Этап 2.1: слой пользователей и аутентификации (JWT) ---
    Route('POST', '/auth/login', 'auth_login', 'Вход по логину и паролю', ('login','password'), ('user_agent',), storage=False),
    Route('POST', '/auth/refresh', 'auth_refresh', 'Обновить пару токенов', ('refresh_token',), ('user_agent',), storage=False),
    Route('POST', '/auth/logout', 'auth_logout', 'Завершить сессию (отозвать refresh-токен)', ('refresh_token',), storage=False),
    Route('GET', '/auth/me', 'auth_me', 'Текущий пользователь по JWT', auth='user', storage=False),
    Route('GET', '/auth/users', 'auth_users_list', 'Список пользователей', auth='admin', storage=False),
    Route('POST', '/auth/users', 'auth_users_create', 'Создать пользователя', ('login','password','full_name','role'), auth='admin', status=201, storage=False),
    Route('POST', '/auth/users/reset-passwords', 'auth_users_reset_passwords', 'Одноразово сбросить пароли обучающихся', (), ('user_ids','group_id','password'), auth='admin', storage=False),
    Route('PUT', '/auth/users/{user_id}', 'auth_users_update', 'Изменить пользователя', (), ('full_name','role','is_active','password','display_name'), auth='admin', storage=False),
    Route('DELETE', '/auth/users/{user_id}', 'auth_users_delete', 'Удалить пользователя', auth='admin', storage=False),
    Route('GET', '/auth/groups', 'auth_groups_list', 'Список учебных групп', auth='admin', storage=False),
    Route('POST', '/auth/groups', 'auth_groups_create', 'Создать учебную группу', ('name',), ('description','teacher_id'), auth='admin', status=201, storage=False),
    Route('PUT', '/auth/groups/{group_id}', 'auth_groups_update', 'Изменить группу', ('name',), ('description','teacher_id'), auth='admin', storage=False),
    Route('DELETE', '/auth/groups/{group_id}', 'auth_groups_delete', 'Удалить группу', auth='admin', storage=False),
    Route('GET', '/auth/groups/{group_id}/members', 'auth_groups_members', 'Состав учебной группы', auth='admin', storage=False),
    Route('POST', '/auth/groups/{group_id}/members', 'auth_groups_add_member', 'Добавить участника в группу', ('user_id',), auth='admin', status=201, storage=False),
    Route('DELETE', '/auth/groups/{group_id}/members/{user_id}', 'auth_groups_remove_member', 'Удалить участника из группы', auth='admin', storage=False),
    # --- Этап 2.2: справочники (JWT admin) ---
    Route('GET', '/catalog/services', 'catalog_services_list', 'Справочник служб', storage=False, auth='admin'),
    Route('POST', '/catalog/services', 'catalog_services_create', 'Добавить службу', ('code', 'name'), storage=False, auth='admin', status=201),
    Route('PUT', '/catalog/services/{service_code}', 'catalog_services_update', 'Изменить службу', ('name',), storage=False, auth='admin'),
    Route('DELETE', '/catalog/services/{service_code}', 'catalog_services_delete', 'Удалить службу', storage=False, auth='admin'),
    Route('GET', '/catalog/categories', 'catalog_categories_list', 'Категории классификатора', storage=False, auth='admin'),
    Route('POST', '/catalog/categories', 'catalog_categories_create', 'Добавить категорию', ('category_id', 'name'), storage=False, auth='admin', status=201),
    Route('PUT', '/catalog/categories/{category_id}', 'catalog_categories_update', 'Изменить категорию', ('name',), storage=False, auth='admin'),
    Route('DELETE', '/catalog/categories/{category_id}', 'catalog_categories_delete', 'Удалить категорию', storage=False, auth='admin'),
    Route('GET', '/catalog/entries', 'catalog_entries_list', 'Записи классификатора', (), ('category_id',), storage=False, auth='admin'),
    Route('POST', '/catalog/entries', 'catalog_entries_create', 'Добавить запись классификатора', ('entry_id', 'category_id', 'title'), ('group_name', 'statistical_group', 'sign1', 'sign2', 'sign3', 'extra_signs', 'ekp_type', 'main_service_code'), storage=False, auth='admin', status=201),
    Route('PUT', '/catalog/entries/{entry_id}', 'catalog_entries_update', 'Изменить запись классификатора', (), ('title', 'category_id', 'group_name', 'statistical_group', 'sign1', 'sign2', 'sign3', 'extra_signs', 'ekp_type', 'main_service_code'), storage=False, auth='admin'),
    Route('DELETE', '/catalog/entries/{entry_id}', 'catalog_entries_delete', 'Удалить запись классификатора', storage=False, auth='admin'),
    Route('GET', '/catalog/entry-services', 'catalog_entry_services_list', 'Связи записей классификатора со службами', (), ('entry_id', 'service_code'), storage=False, auth='admin'),
    Route('POST', '/catalog/entry-services', 'catalog_entry_services_create', 'Добавить связь записи и службы', ('entry_id', 'service_code'), ('condition_type', 'condition_text', 'value', 'is_main'), storage=False, auth='admin', status=201),
    Route('PUT', '/catalog/entry-services/{entry_service_id}', 'catalog_entry_services_update', 'Изменить связь записи и службы', (), ('service_code', 'condition_type', 'condition_text', 'value', 'is_main'), storage=False, auth='admin'),
    Route('DELETE', '/catalog/entry-services/{entry_service_id}', 'catalog_entry_services_delete', 'Удалить связь записи и службы', storage=False, auth='admin'),
    Route('GET', '/catalog/geo-addresses', 'catalog_geo_addresses_list', 'Гео-адреса OSM', (), ('kind', 'limit'), storage=False, auth='admin'),
    Route('POST', '/catalog/geo-addresses', 'catalog_geo_addresses_create', 'Добавить гео-адрес', ('address_id', 'street'), ('house', 'lat', 'lon', 'kind', 'point'), storage=False, auth='admin', status=201),
    Route('PUT', '/catalog/geo-addresses/{address_id}', 'catalog_geo_addresses_update', 'Изменить гео-адрес', (), ('street', 'house', 'lat', 'lon', 'kind', 'point'), storage=False, auth='admin'),
    Route('DELETE', '/catalog/geo-addresses/{address_id}', 'catalog_geo_addresses_delete', 'Удалить гео-адрес', storage=False, auth='admin'),
    # --- Этап 5: мастерская карточек (JWT teacher/admin) ---
    Route('GET', '/workshop/cards', 'workshop_cards_list', 'Список карточек мастерской', storage=False, auth='teacher'),
    Route('POST', '/workshop/cards', 'workshop_cards_create', 'Создать карточку', ('content',), ('author_id',), storage=False, auth='teacher', status=201, extensible=True),
    Route('GET', '/workshop/cards/{workshop_ref}', 'workshop_cards_get', 'Полная карточка мастерской', storage=False, auth='teacher'),
    Route('PUT', '/workshop/cards/{workshop_ref}', 'workshop_cards_update', 'Сохранить правки карточки', ('content',), ('author_id',), storage=False, auth='teacher', extensible=True),
    Route('DELETE', '/workshop/cards/{workshop_ref}', 'workshop_cards_delete', 'Удалить черновик карточки', storage=False, auth='teacher'),
    Route('POST', '/workshop/cards/{workshop_ref}/approvals', 'workshop_cards_approve', 'Утвердить карточку', ('review',), ('author_id',), storage=False, auth='teacher', extensible=True),
    Route('POST', '/workshop/cards/{workshop_ref}/reopening', 'workshop_cards_reopen', 'Вернуть карточку на доработку', (), ('author_id',), storage=False, auth='teacher'),
    Route('POST', '/workshop/imports', 'workshop_import', 'Импорт карточек из JSON (upsert по номеру)', ('cards',), ('author_id',), storage=False, auth='teacher', extensible=True),
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
