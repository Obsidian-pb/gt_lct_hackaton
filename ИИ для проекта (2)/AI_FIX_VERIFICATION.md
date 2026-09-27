# Проверка исправления ИИ

Дата: 27.09.2026.

## Результат

- Python unittest: 83 теста; 77 прошли, 6 Windows-тестов пропущены.
- Дополнительно проверен UTF-8 BOM в PowerShell-файлах с русским текстом.
- React пересобран esbuild 0.25.10; синтаксис готового JS проверен node --check.
- Учебные данные, классификатор, карта/адреса и инструменты из исходного ZIP сохранены без изменений (побайтовое сравнение).
- Имена двух русскоязычных файлов восстановлены из некорректной ZIP-кодировки.
- Ключей пользователя и config.local.json в архиве нет.

## Ограничения проверки

Живые запросы к ИИ не выполнялись: использованы искусственные ключи и подставные ответы API. Не проверены баланс, региональная доступность и права конкретного ключа. В Linux нет Windows PowerShell; окно ввода и запись настроек необходимо проверить на Windows.

Для проверки на своём компьютере: START.cmd → OpenAI → свой API-ключ → auto → сохранить. При замене настроек: CHANGE_AI_KEY.cmd, затем RESTART.cmd. После CHECK_AI.cmd создайте одну учебную карточку, чтобы проверить генерацию.

## Изменённые файлы

- `AI_PORTABILITY_FIX.md`
- `CHANGE_AI_KEY.cmd`
- `setup_key.ps1`
- `START.cmd`
- `START_CONSOLE.cmd`
- `CHECK_AI.cmd`
- `tests/test_provider.py`
- `tests/test_key_setup.py`
- `ui/react/app.js`
- `frontend/src/Admin.jsx`
- `PREPARE_AI_CONNECTION.ps1`
- `provider.py`
- `check_ai.py`
- `ВСТАВИТЬ_КЛЮЧ.cmd`
- `FIRST_RUN_KEY.ps1`
- `README.md`

Добавлены tests/test_multi_provider.py и этот отчёт.

Лог unittest:

```text
Ran 83 tests in 1.233s
OK (skipped=6)
```
