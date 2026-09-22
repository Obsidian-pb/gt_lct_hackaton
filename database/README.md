# Тренажёр оператора ДДС «Система-112» — база данных

Репозиторий содержит PostgreSQL-схему и SQLAlchemy 2.0 модели для учебного
тренажёра операторов ДДС.

## Состав

- `schema.sql` — автономный SQL-файл для PostgreSQL 12+;
- `DATABASE_OVERVIEW.md` — краткое описание таблиц и диаграммы связей;
- `src/trainer_db/models/` — модели SQLAlchemy 2.0;
- `alembic/versions/0001_initial_schema.py` — начальная миграция;
- `alembic/versions/0002_classifier_structure.py` — классификатор происшествий;
- `alembic/versions/0003_incident_card_details.py` — обязательные поля карточки;
- `alembic/versions/0004_rename_event_feature_1.py` — первый признак классификатора;
- `alembic/versions/0005_classifier_import_fields.py` — поля расшифровок и диапазон групп;
- `scripts/import_classifier.py` — проверка и импорт классификатора из Excel;
- `scripts/export_schema.py` — повторная генерация SQL-файла из миграции.

Модель поддерживает динамические JSONB-карточки, проверяемые преподавателем,
адаптивную сложность, пороги правильности по уровням и снижение оценки по
экспоненциальной формуле времени.

Формула реализована функцией `training.calculate_total_score`, а переход уровня
сложности — функцией `training.next_difficulty`.

## Классификатор происшествий

Классификатор хранится как иерархия `event_types → event_features_1 →
event_features_2 → event_features_3`. Итоговый `event_number` в
`event_classes` база рассчитывает автоматически по формуле
`Г × 1 000 000 + признак 1 × 10 000 + признак 2 × 100 + признак 3`.
После создания номер и определяющая его комбинация неизменяемы.

Название группы происшествий хранится в `event_types.name`. Точные
расшифровки признаков конкретного события из столбцов G–I исходного
классификатора хранятся в `event_classes.feature_1_label`,
`feature_2_label` и `feature_3_label`. Пустая расшифровка сохраняется как
`NULL`.

Таблица `classifier_versions` и связь `classifier_version_events` позволяют
зафиксировать полную версию справочника, которая действовала во время учебной
сессии. Сама сессия ссылается на неё через `classifier_version_id`.

GigaChat-предложение хранится в `exercise_revisions.classification_proposal`,
а подтверждённый преподавателем результат — в `event_class_id`. Сценарий,
главную службу и список служб можно переопределить только для конкретной
редакции карточки, не изменяя классификатор.

## Содержимое карточки происшествия

`content.incident_card_details` хранит структурированное содержимое карточки и
связана с `exercise_revisions` один-к-одному. Таблица содержит ФИО сотрудников,
три раздельных телефона (АОН, заявителя и на месте), одного заявителя, один
формализованный адрес, широту и долготу, сведения ВИС и отметки контроля.

Номер карточки в этой таблице не дублируется. Он определяется через
`exercise_revisions.event_class_id → catalog.event_classes.event_number`.

## Установка и миграция

```powershell
cd database
python -m pip install -e .
$env:DATABASE_URL = "postgresql+asyncpg://user:password@localhost/system112_trainer"
python -m alembic upgrade head
```

Перед импортом файл проверяется без записи в базу:

```powershell
python scripts/import_classifier.py
```

Для загрузки проверенных данных:

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://user:password@localhost/database"
python scripts/import_classifier.py --apply
```

Если PostgreSQL доступен только из Docker-контейнера, можно сформировать
повторно запускаемый SQL-файл:

```powershell
python scripts/import_classifier.py --sql-output classifier_import.sql
```

Импортёр использует только коды A–D, названия групп происшествий и
расшифровки G–I. Строки с пометкой `Не отображается оператору 112` не
загружаются. Повторный запуск обновляет существующие записи и не создаёт
дубликаты.

Для автономного создания базы можно выполнить `schema.sql` через
`psql`. Схемы `auth`, `catalog`, `content`, `training` и `audit` создаются
автоматически.

## Отложенное физическое удаление

Удаляемые сущности сначала получают `deleted_at`. База автоматически назначает
`purge_after = deleted_at + 6 месяцев`. Окончательная каскадная очистка запускается
регламентным вызовом:

```sql
SELECT * FROM audit.purge_expired_data(1000);
```

Журналы аудита также удаляются только после окончания собственного периода
хранения в шесть месяцев.

Учётные записи и системные роли начальной миграцией не создаются.
