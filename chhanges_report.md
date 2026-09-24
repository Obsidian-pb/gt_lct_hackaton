# Отчет об изменениях

**Дата:** 24.09.2026

## Проблема

При запуске `npm run dev` в `frontend/` падал с ошибкой:

```
Error: Cannot find native binding.
Cannot find module '@rolldown/binding-win32-x64-msvc'
```

Причина — известный баг npm [#4828](https://github.com/npm/cli/issues/4828) с опциональными зависимостями. Vite 8 использует движок rolldown, который подгружает нативный бинарник `@rolldown/binding-win32-x64-msvc` как опциональный пакет. npm «потерял» этот пакет: в `node_modules\@rolldown` присутствовала только папка `pluginutils`, а биндинга не было. При этом `npm i` и `npm ci` считали дерево зависимостей «up to date» и не доустанавливали пакет (запись в lock-файле была, на диске — нет).

## Выполненные действия

1. Удалены `frontend/node_modules` и `frontend/package-lock.json`, выполнен `npm install` — проблема не решилась (та же особенность npm 10.8.2).
2. Явно доустановлен нативный биндинг:
   ```
   npm install @rolldown/binding-win32-x64-msvc@1.2.10
   ```
   Файл `rolldown-binding.win32-x64-msvc.node` (~20 МБ) размещен в `node_modules\@rolldown\binding-win32-x64-msvc\`.
3. Проверен запуск: `npm run dev` — сервер стартует (`VITE v8.3.0 ready in 1403 ms`), доступен на `http://localhost:5173/`.

## Изменения в файлах

| Файл | Изменение |
|---|---|
| `frontend/package.json` | Без изменений |
| `frontend/package-lock.json` | Обновлен при перегенерации lock-файла: rolldown 1.2.8 → 1.2.10, oxlint 1.83.0 → 1.85.0 и т.п. Рекомендуется закоммитить |

## Рекомендации

- **Обновить Node.js**: текущая версия 20.17.0 ниже минимально требуемой для Vite 8 (`^20.19.0 || >=22.12.0`). Рекомендуется LTS-версия 22.x — это также снизит риск повторения подобных сбоев установки опциональных зависимостей.
