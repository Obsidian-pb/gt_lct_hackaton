# Тренажёр оператора ДДС «Система-112» — база данных

Репозиторий содержит PostgreSQL-схему и SQLAlchemy 2.0 модели для учебного
тренажёра операторов ДДС.

## Состав

- `schema.sql` — автономный SQL-файл для PostgreSQL 12+;
- `src/trainer_db/models/` — модели SQLAlchemy 2.0;
- `alembic/versions/0001_initial_schema.py` — начальная миграция;
- `scripts/export_schema.py` — повторная генерация SQL-файла из миграции.

Модель поддерживает динамические JSONB-карточки, проверяемые преподавателем,
адаптивную сложность, пороги правильности по уровням и снижение оценки по
экспоненциальной формуле времени.

Формула реализована функцией `training.calculate_total_score`, а переход уровня
сложности — функцией `training.next_difficulty`.

## Установка и миграция

```powershell
cd database
python -m pip install -e .
$env:DATABASE_URL = "postgresql+asyncpg://user:password@localhost/system112_trainer"
python -m alembic upgrade head
```

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
