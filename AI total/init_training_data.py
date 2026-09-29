"""Initialize the training data layer: schema 2.3.0 and the JSON->DB import.

Этап 3: переносит учебные данные из data/ (t-*.json, s-*.json,
data/curriculum/scenario-*.json, training-*.json, materials.json) в таблицы,
созданные Этапом 2.2, и создаёт legacy_name_map (схема 2.3.0). Строковые
имена студентов/преподавателей разрешаются в user.

Run manually (TEST_DATA.cmd) or by START_ALL.ps1 (--check only).
Exit codes: 0 = ok, 2 = failure (same convention as init_auth/init_catalog).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import training_data_repository
import training_data_service
from training_data_importer import scan

KEY_TABLES = ('task', 'session', 'scenario', 'training', 'material',
              'legacy_name_map')


def _files_text(report) -> str:
    parts = [
        f'tasks={len(report.task_files)}', f'sessions={len(report.session_files)}',
        f'scenarios={len(report.scenario_files)}',
        f'trainings={len(report.training_files)}',
        f'materials={"да" if report.materials_file else "нет"}']
    return ', '.join(parts)


def run_init(directory) -> tuple:
    """Scan, parse, resolve users and rewrite the educational tables."""
    try:
        result = training_data_service.import_all(directory)
    except training_data_service.TrainingDataError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f'Не удалось импортировать учебные данные: {exc}'
    counts = result['counts']
    counts_text = ', '.join(f'{key}={counts[key]}' for key in KEY_TABLES)
    message = (f'Импорт выполнен (схема {training_data_repository.SCHEMA_VERSION}); '
               f'{counts_text}; '
               f'users_created={len(result["created_users"])}, '
               f'warnings={len(result["warnings"])}.')
    return True, message


def run_check(directory) -> tuple:
    """Verify that data files exist and the DB state matches them."""
    try:
        state = training_data_service.check_state(directory)
    except Exception as exc:
        return False, f'Ошибка проверки учебных данных: {exc}'
    report = state['report']
    if not report.available:
        return False, 'Учебные данные не найдены: ' + _files_text(report)
    version = state['version']
    if version is None:
        return False, (f'Схема {training_data_repository.SCHEMA_VERSION} '
                       'не инициализирована (запустите --init).')
    counts = state['counts']
    problems = []
    if report.task_files and counts['task'] == 0:
        problems.append('task пуст при наличии t-*.json')
    if report.session_files and counts['session'] == 0:
        problems.append('session пуст при наличии s-*.json')
    if report.scenario_files and counts['scenario'] == 0:
        problems.append('scenario пуст при наличии scenario-*.json')
    if report.training_files and counts['training'] == 0:
        problems.append('training пуст при наличии training-*.json')
    if report.materials_file and counts['material'] == 0:
        problems.append('material пуст при наличии materials.json')
    problems += list(state['issues'])
    counts_text = ', '.join(f'{key}={counts[key]}' for key in KEY_TABLES)
    if problems:
        return False, (f'Учебные данные найдены ({_files_text(report)}), схема '
                       f'{version}, но: ' + '; '.join(problems))
    return True, (f'Учебные данные готовы: файлы ({_files_text(report)}); '
                  f'{counts_text}; целостность OK.')


def run_self_test(directory) -> tuple:
    """Read a small sample from key tables and verify FK integrity."""
    try:
        repository = training_data_repository.TrainingDataRepository()
        counts = repository.counts()
        issues = repository.integrity_issues()
        samples = []
        with repository._connect() as connection:
            for table in KEY_TABLES:
                row = connection.fetchone(
                    'SELECT count(*) FROM ' + table)
                samples.append((table, int(row[0]) if row else 0))
    except Exception as exc:
        return False, f'Самопроверка учебных данных не пройдена: {exc}'
    empty = [label for label, value in samples if value == 0]
    message = 'Самопроверка: ' + ', '.join(f'{k}={v}' for k, v in samples)
    if issues:
        return False, message + '; нарушения целостности: ' + '; '.join(issues)
    if empty:
        return False, message + '; пустые таблицы: ' + ', '.join(empty)
    return True, message + '; целостность OK.'


def main(argv) -> int:
    parser = argparse.ArgumentParser(
        description='Перенос учебных данных из JSON в PostgreSQL (Этап 3)')
    parser.add_argument('--init', action='store_true',
                        help='Полный импорт: схема 2.3.0 + перезапись учебных таблиц')
    parser.add_argument('--check', action='store_true',
                        help='Проверить наличие данных и состояние БД')
    parser.add_argument('--self-test', action='store_true',
                        help='Выборки из таблиц и проверка целостности')
    parser.add_argument('--dir', default=None,
                        help='Каталог с учебными данными (по умолчанию ./data)')
    parser.add_argument('--pause', action='store_true',
                        help='Ждать Enter перед выходом (для отдельного окна)')
    args = parser.parse_args(argv)

    steps = []
    if args.check:
        steps.append(('Проверка', lambda: run_check(args.dir)))
    if args.init:
        steps.append(('Инициализация', lambda: run_init(args.dir)))
    if args.self_test:
        steps.append(('Самопроверка', run_self_test))
    if not (args.init or args.check or args.self_test):
        steps.append(('Инициализация', lambda: run_init(args.dir)))

    ok_all = True
    for label, step in steps:
        ok, message = step()
        ok_all = ok_all and ok
        print(f'[DATA] {label}: {message}' if ok
              else f'[DATA] {label}: ОШИБКА: {message}')

    if args.pause:
        try:
            input('\nНажмите Enter для выхода...')
        except EOFError:
            pass
    return 0 if ok_all else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))