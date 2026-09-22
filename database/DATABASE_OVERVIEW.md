# Краткое описание базы данных тренажёра «Система-112»

База данных работает на PostgreSQL и разделена на пять прикладных схем.
Внутренние идентификаторы основных объектов имеют тип UUID. Карточка получает
официальный номер из классификатора, поэтому отдельный номер в содержимом
карточки не дублируется.

## Схемы и таблицы

### `auth` — пользователи и доступ

- `users` — администраторы, преподаватели и обучающиеся;
- `roles` — роли пользователей;
- `permissions` — разрешения;
- `user_roles` — назначение нескольких ролей пользователю;
- `role_permissions` — разрешения, входящие в роль.

### `catalog` — классификатор и службы

- `event_types` — верхний уровень классификатора, код `Г`;
- `event_features_1` — первый признак;
- `event_features_2` — второй признак;
- `event_features_3` — третий признак;
- `event_classes` — допустимые комбинации признаков и номера событий;
- `services` — справочник экстренных и городских служб;
- `event_class_services` — службы, привлекаемые к событию;
- `classifier_versions` — опубликованные версии классификатора;
- `classifier_version_events` — состав каждой версии классификатора.

Номер события рассчитывается автоматически:

```text
Г × 1 000 000 + признак 1 × 10 000 + признак 2 × 100 + признак 3
```

В `event_types.name` хранится расшифровка группы происшествия `Г`. Поля
`event_classes.feature_1_label`, `feature_2_label` и `feature_3_label`
сохраняют точные расшифровки признаков конкретного события. Они могут
отличаться у разных комбинаций кодов, поэтому не вычисляются по одному коду
признака. Отсутствующая расшифровка хранится как `NULL`.

### `content` — шаблоны и карточки

- `event_templates` — темы и инструкции для генерации карточек;
- `event_template_services` — службы шаблона;
- `exercises` — карточки банка заданий и уровень сложности;
- `exercise_services` — службы конкретной карточки;
- `exercise_revisions` — редакции, эталон, предложение GigaChat и проверка;
- `incident_card_details` — заявитель, три телефона, адрес, координаты,
  описание происшествия, сведения ВИС и контроль.

Одна редакция имеет не более одного набора `incident_card_details`. Номер
карточки получается через `exercise_revisions.event_class_id` и
`event_classes.event_number`.

### `training` — прохождение и оценка

- `scoring_profiles` — наборы правил оценки;
- `scoring_rules` — правила для каждого уровня сложности;
- `sessions` — учебные сессии;
- `session_cards` — карточки, выданные в сессии;
- `answers` — ответы обучающихся;
- `evaluations` — правильность, время, применённые правила и итоговый балл.

### `audit` — журнал действий

- `audit_log` — действия пользователей и изменения объектов. Записи журнала
  хранятся шесть месяцев.

### `public` — служебная схема

- `alembic_version` — текущая версия миграций. Таблицу нельзя изменять вручную.

## Связи пользователей и прав

```mermaid
erDiagram
    users ||--o{ user_roles : "получает роли"
    roles ||--o{ user_roles : "назначается пользователям"
    roles ||--o{ role_permissions : "содержит права"
    permissions ||--o{ role_permissions : "входит в роли"

    users {
        uuid id PK
        string username UK
        string display_name
        boolean is_active
    }
    roles {
        uuid id PK
        string code UK
        string name
    }
    permissions {
        uuid id PK
        string code UK
        string name
    }
    user_roles {
        uuid user_id PK, FK
        uuid role_id PK, FK
    }
    role_permissions {
        uuid role_id PK, FK
        uuid permission_id PK, FK
    }
```

## Связи классификатора и карточек

```mermaid
erDiagram
    event_types ||--o{ event_features_1 : "содержит"
    event_features_1 ||--o{ event_features_2 : "уточняется"
    event_features_2 ||--o{ event_features_3 : "уточняется"

    event_types ||--o{ event_classes : "определяет"
    event_features_1 ||--o{ event_classes : "определяет"
    event_features_2 ||--o{ event_classes : "определяет"
    event_features_3 ||--o{ event_classes : "определяет"

    classifier_versions ||--o{ classifier_version_events : "включает"
    event_classes ||--o{ classifier_version_events : "входит в версии"

    event_classes ||--o{ event_class_services : "привлекает"
    services ||--o{ event_class_services : "назначается"
    services o|--o{ event_classes : "главная служба"

    event_types o|--o{ event_templates : "ограничивает тему"
    event_classes o|--o{ event_templates : "задаёт событие"
    event_templates ||--o{ event_template_services : "содержит службы"
    services ||--o{ event_template_services : "назначается шаблону"

    event_templates ||--o{ exercises : "генерирует"
    exercises ||--o{ exercise_services : "содержит службы"
    services ||--o{ exercise_services : "назначается карточке"
    exercises ||--o{ exercise_revisions : "имеет редакции"
    event_classes o|--o{ exercise_revisions : "классифицирует"
    exercise_revisions ||--o| incident_card_details : "имеет содержимое"

    event_types {
        uuid id PK
        smallint code UK
        string name
    }
    event_features_1 {
        uuid id PK
        uuid event_type_id FK
        smallint code
    }
    event_features_2 {
        uuid id PK
        uuid event_feature_1_id FK
        smallint code
    }
    event_features_3 {
        uuid id PK
        uuid event_feature_2_id FK
        smallint code
    }
    event_classes {
        uuid id PK
        bigint event_number UK
        uuid event_type_id FK
        uuid event_feature_1_id FK
        uuid event_feature_2_id FK
        uuid event_feature_3_id FK
        string feature_1_label
        string feature_2_label
        string feature_3_label
        uuid main_service_id FK
    }
    classifier_versions {
        uuid id PK
        int version_number UK
        boolean is_active
    }
    classifier_version_events {
        uuid classifier_version_id PK, FK
        uuid event_class_id PK, FK
    }
    services {
        uuid id PK
        string code UK
        string name
    }
    event_class_services {
        uuid event_class_id PK, FK
        uuid service_id PK, FK
    }
    event_templates {
        uuid id PK
        uuid event_type_id FK
        uuid event_class_id FK
        string topic
        string status
    }
    event_template_services {
        uuid event_template_id PK, FK
        uuid service_id PK, FK
    }
    exercises {
        uuid id PK
        uuid event_template_id FK
        string difficulty
        uuid active_revision_id FK
    }
    exercise_services {
        uuid exercise_id PK, FK
        uuid service_id PK, FK
    }
    exercise_revisions {
        uuid id PK
        uuid exercise_id FK
        uuid event_class_id FK
        int revision_number
        jsonb trainee_card
        jsonb ethalon_payload
    }
    incident_card_details {
        uuid id PK
        uuid exercise_revision_id UK, FK
        string applicant_full_name
        string aon_phone
        decimal latitude
        decimal longitude
    }
```

## Связи учебного процесса и аудита

```mermaid
erDiagram
    users o|--o{ classifier_versions : "публикует"
    users o|--o{ event_templates : "создаёт"
    users o|--o{ exercises : "создаёт и утверждает"
    users o|--o{ exercise_revisions : "создаёт и проверяет"
    users o|--o{ scoring_profiles : "создаёт"

    scoring_profiles ||--o{ scoring_rules : "содержит"
    scoring_profiles o|--o{ sessions : "оценивает"
    classifier_versions o|--o{ sessions : "фиксируется в"
    users ||--o{ sessions : "проходит или контролирует"

    sessions ||--o{ session_cards : "содержит"
    exercise_revisions ||--o{ session_cards : "выдаётся в сессии"
    session_cards ||--o| answers : "получает ответ"
    answers ||--o| evaluations : "оценивается"
    users o|--o{ audit_log : "совершает действие"

    scoring_profiles {
        uuid id PK
        string name UK
        boolean is_default
    }
    scoring_rules {
        uuid id PK
        uuid profile_id FK
        string difficulty
        decimal correctness_threshold
        int half_life_seconds
    }
    sessions {
        uuid id PK
        uuid trainee_id FK
        uuid teacher_id FK
        uuid scoring_profile_id FK
        uuid classifier_version_id FK
        string status
    }
    session_cards {
        uuid id PK
        uuid session_id FK
        uuid exercise_revision_id FK
        int sequence_number
        string status
    }
    answers {
        uuid id PK
        uuid session_card_id UK, FK
        jsonb payload
    }
    evaluations {
        uuid id PK
        uuid answer_id UK, FK
        decimal accuracy_percent
        decimal total_score
        string next_difficulty
    }
    audit_log {
        uuid id PK
        uuid actor_id FK
        string action
        string entity_type
        uuid entity_id
    }
    users {
        uuid id PK
    }
    classifier_versions {
        uuid id PK
    }
    event_templates {
        uuid id PK
    }
    exercises {
        uuid id PK
    }
    exercise_revisions {
        uuid id PK
    }
}
```

## Удаление и история

Пользователи, события, службы, шаблоны, карточки, профили оценки и учебные
сессии сначала помечаются удалёнными. Поле `purge_after` назначает физическое
удаление через шесть месяцев. Зависимые записи удаляются каскадно только после
окончательного удаления родительского объекта.
