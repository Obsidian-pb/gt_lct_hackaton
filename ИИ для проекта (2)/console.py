"""Thin console client. All exercise behavior lives in ai_core.Engine."""
import argparse
import sys
from ai_core import Engine, FIELDS, LEVELS, VERDICTS
from provider import AIProvider
from voice import capture
from dds import WORKFLOWS, ACTION_LABELS

ROLE_LABELS = {'caller': 'Заявитель', 'service': 'Служба', 'dispatcher': 'Диспетчер', 'system': 'Событие'}


def choose_workflow():
    return {'1': 'caller', '2': 'dds'}.get(input('Вариант: 1 — оператор 112; 2 — диспетчер ДДС: ').strip(), 'caller')

STATUS = {'draft': 'Черновик', 'approved': 'Утверждено', 'active': 'В работе', 'submitted': 'Сдано, нужна проверка ИИ',
          'pending_teacher': 'Ожидает преподавателя', 'reviewed': 'Проверено преподавателем'}


def choose(items, label):
    if not items:
        print('Пока нет подходящих записей.'); return None
    for i, item in enumerate(items, 1):
        print(f"{i}. {item.get('title') or item['task']['title']} | {item.get('student', '')} | {STATUS[item['status']]} | {item['id']}")
    raw = input(label + ' (Enter — назад): ').strip()
    if not raw:
        return None
    index = int(raw) - 1
    if not 0 <= index < len(items):
        raise ValueError('Нет такого номера.')
    return items[index]


def show_task(t):
    print(f"\n{t['title']} · {LEVELS[t['level']]} · {STATUS[t['status']]}")
    print('Первая реплика:', t['opening']); print('Заявитель:', t['persona'])
    for key, label in FIELDS.items():
        f = t['fields'][key]
        print(f"\n{key} — {label}\n  Факт мира: {f['truth']}\n  Знает заявитель: {f['known']}\n  ЭТАЛОН: {f['expected']}\n  Критерий: {f['criterion']} (вес {f['weight']})")
    if t.get('workflow') == 'dds':
        print('\nВХОДЯЩАЯ КАРТОЧКА:', t['incoming_card'])
        print('Доступное уточнение:', t['verification_notes'])
        print('Ошибки для преподавателя:', t['faults'])
        print('Сотрудник службы:', t['service'])
        for key, label in ACTION_LABELS.items():
            print(key, label, t['actions'][key])


def edit_task(engine, t):
    while True:
        show_task(t)
        action = input('\n1 — исправить; 2 — утвердить; Enter — сохранить черновик и выйти: ').strip()
        if action == '1':
            field = input('Код поля (address и т. д.) либо title / opening / persona: ').strip()
            prop = input('Свойство: truth / known / expected / criterion / weight (incoming_card: код поля; service: name/role/knowledge): ').strip() if field in FIELDS or field in ACTION_LABELS or field in ('incoming_card', 'service') else ''
            t = engine.edit_task(t['id'], field, prop, input('Новое значение: '))
        elif action == '2':
            teacher = input('Имя преподавателя: ')
            if input('Подтверждаете согласованность сценария, знаний заявителя и эталона? да/нет: ').strip().lower() == 'да':
                engine.approve(t['id'], teacher)
                print('Карточка утверждена. Она доступна в пункте 7 «Утверждённые карточки».')
                print('Для прохождения выберите 5 «Начать обучение». Доступно карточек:', len(engine.approved_tasks()))
                return
        else:
            return


def review(engine, session):
    if session['status'] == 'submitted':
        print('ИИ готовит предварительное заключение…'); engine.assess(session['id'])
    s = engine.load(session['id'])
    labels = FIELDS | (ACTION_LABELS if s['task'].get('workflow') == 'dds' else {})
    print('\nРАБОТА НА СТОЛЕ ПРЕПОДАВАТЕЛЯ:', s['student'], '|', s['task']['title'])
    print('Уровень:', LEVELS[s['task']['level']], '| Подсказок:', len(s['hints']))
    for hint in s['hints']:
        print('  Подсказка:', hint['text'])
    print('\nРАЗГОВОР')
    for row in s['history']:
        print(f"[{row['id']}] {ROLE_LABELS[row['role']]}: {row['text']}")
        if row.get('delivery') in ('partial', 'lost'):
            print('  Доставлено:', row['delivered'] or 'ничего')
    print('\nПРЕДВАРИТЕЛЬНОЕ ЗАКЛЮЧЕНИЕ ИИ:', s['assessment']['summary'])
    for key, label in labels.items():
        row = s['assessment']['fields'][key]
        ref = (s['task']['fields'] | s['task'].get('actions', {}))[key]
        print(f"\n{label}\n  Ученик: {s['card'].get(key) or 'См. разговор / не заполнено'}\n  Эталон: {ref['expected']}\n  Критерий: {ref['criterion']}\n  ИИ: {VERDICTS[row['verdict']]} — {row['comment']}\n  Уточнение: {row['clarification']}")
        for cite in row['evidence']:
            print(f"  Реплика {cite['turn_id']}: «{cite['quote']}»")
        if row['citation_warning']:
            print('  ВНИМАНИЕ: ИИ привёл неподтверждённую цитату. Она удалена; замечание требует ручной проверки.')
    if s['status'] == 'reviewed':
        print('\nРЕШЕНИЕ ПРЕПОДАВАТЕЛЯ:', s['teacher_decision']); return
    if input('\nРассмотреть замечания и вынести итог сейчас? да/нет: ').strip().lower() != 'да':
        return
    decisions = {}
    for key, label in labels.items():
        while True:
            choice = input(label + ': 1 — согласен; 2 — отклонить; 3 — исправить замечание: ').strip()
            if choice in ('1', '2', '3'):
                break
        comment = s['assessment']['fields'][key]['comment'] if choice == '1' else input('Ваш комментарий: ').strip()
        if not comment:
            raise ValueError('Комментарий обязателен. Итог не опубликован.')
        decisions[key] = {'decision': {'1':'agree', '2':'reject', '3':'edit'}[choice], 'comment': comment}
    teacher = input('Имя преподавателя: ')
    grade = int(input('Ваша итоговая оценка (2–5): '))
    conclusion = input('Итоговый комментарий обучающемуся: ')
    if input('Опубликовать итог преподавателя? да/нет: ').strip().lower() == 'да':
        engine.finalize(s['id'], teacher, grade, conclusion, decisions)
        print('Итог сохранён. Обучающийся теперь может его посмотреть.')


HELP = '''
Просто введите вопрос — он будет отправлен заявителю.
/voice — произнести вопрос через микрофон
/card — показать вашу карточку и коды полей
/set address Текст — записать поле (замените address нужным кодом)
/hint — подсказка на лёгком и среднем уровнях
/history — разговор; /help — команды
/finish — сдать карточку; /back — сохранить и выйти без сдачи
ДДС: /call — звонок или перезвон; /hangup — завершить; /link clear|partial|drop — следующая реплика без помех / слышно начало / обрыв
'''


def student(engine, identifier):
    s = engine.student_view(identifier)
    print('\n', s['title'], '|', LEVELS[s['level']], '|', STATUS[s['status']])
    if s['status'] != 'active':
        if s['result']:
            print('Преподаватель:', s['result']['teacher'], '| Оценка:', s['result']['grade'])
            print(s['result']['conclusion'])
            for key, decision in s['result']['fields'].items():
                print((FIELDS | ACTION_LABELS)[key] + ': ' + decision['comment'])
        else:
            print('Работа сдана. Ожидайте итог преподавателя. Предварительная проверка ИИ ученику не показывается.')
        return
    print(ROLE_LABELS[s['history'][-1]['role']] + ':', s['history'][-1]['text']); print(HELP)
    if s['workflow'] == 'dds':
        print('Получена заполненная карточка. /card — просмотр.')
        print('Доступное уточнение:', s['dds']['verification_notes'])
        print('Служба:', s['dds']['service_name'], '| /call — позвонить')
    if s['level'] == 'easy' and not s['hints']:
        try:
            print('Помощник:', engine.hint(identifier))
        except Exception as exc:
            print('Подсказка недоступна:', exc)
    while True:
        try:
            line = input('\nДиспетчер > ').strip()
            if not line:
                continue
            if line == '/back':
                return
            if line == '/help':
                print(HELP); continue
            if line == '/call':
                state = engine.connect_service(identifier)
                print('Служба:', state['history'][-1]['text']); continue
            if line == '/hangup' or line.startswith('/link '):
                state = engine.set_channel(identifier, 'hangup' if line == '/hangup' else line.split(' ', 1)[1])
                print(state['history'][-1]['text']); continue
            if line == '/card':
                for key, value in engine.student_view(identifier)['card'].items():
                    print(f'{key} — {FIELDS[key]}: {value or "—"}')
                continue
            if line == '/history':
                for row in engine.student_view(identifier)['history']:
                    print(ROLE_LABELS[row['role']] + ': ' + row['text'])
                    if row.get('delivery') in ('partial', 'lost'):
                        print('  Доставлено:', row['delivered'] or 'ничего')
                continue
            if line.startswith('/set '):
                parts = line.split(' ', 2)
                if len(parts) < 3:
                    raise ValueError('Пример: /set floors 1 этаж')
                engine.set_field(identifier, parts[1], parts[2]); print('Записано.'); continue
            if line == '/hint':
                print('Помощник:', engine.hint(identifier)); continue
            if line == '/finish':
                if input('Сдать карточку без возможности изменения? да/нет: ').strip().lower() != 'да':
                    continue
                engine.submit(identifier)
                print('Карточка сдана. ИИ готовит материалы для преподавателя…')
                try:
                    engine.assess(identifier)
                    print('Передано на проверку преподавателю.')
                except Exception as exc:
                    print('Карточка сохранена. Проверка ИИ не завершена:', exc)
                    print('Преподаватель сможет повторить проверку из своей очереди.')
                return
            source = 'text'
            if line == '/voice':
                line = capture(); source = 'voice'
                if not line:
                    print('Голосовой ввод отменён.'); continue
                print('Распознано:', line)
                if input('Отправить заявителю? да/нет: ').strip().lower() != 'да':
                    continue
            elif line.startswith('/'):
                print('Неизвестная команда. /help — список.'); continue
            print('Собеседник отвечает…')
            print('Служба / событие:' if s['workflow'] == 'dds' else 'Заявитель:', engine.ask(identifier, line, source))
            if s['level'] == 'easy':
                print('Помощник:', engine.hint(identifier))
        except KeyboardInterrupt:
            print('\nДействие отменено. Записи сохранены; /back — в меню.')
        except Exception as exc:
            print('Не удалось выполнить действие:', exc)


def main():
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='ИИ для проекта — консольный прототип')
    parser.add_argument('--data-dir', help='Отдельное хранилище упражнений')
    args = parser.parse_args()
    engine = Engine(AIProvider(), args.data_dir)
    print('ИИ ДЛЯ ПРОЕКТА · ПРОБНАЯ ВЕРСИЯ · ИИ')
    print('Учебная карточка временная. Роли переключаются без пароля только для тестирования.')
    print('Все изменения сохраняются автоматически. Ctrl+C в главном меню — выход.')
    while True:
        try:
            print('\nПРЕПОДАВАТЕЛЬ: 1 — создать задание с ИИ; 2 — готовый пример; 3 — черновики')
            print('4 — сданные работы обучающихся; 7 — утверждённые карточки')
            print(f'ОБУЧАЮЩИЙСЯ: 5 — начать обучение (доступно карточек: {len(engine.approved_tasks())}); 6 — продолжить / посмотреть результат; 0 — выход')
            choice = input('Выбор: ').strip()
            if choice == '0':
                return
            if choice in ('1', '2'):
                workflow = choose_workflow()
                level = 'medium'  # internal legacy dialogue profile; no user-selectable difficulty
                if choice == '1':
                    topic = input('Тема задания: '); print('ИИ создаёт задание и черновик эталона…')
                    task = engine.draft(topic, level, workflow)
                else:
                    task = engine.sample(level, workflow)
                edit_task(engine, task)
            elif choice == '3':
                t = choose([t for t in engine.list_items('t') if t['status'] == 'draft'], 'Номер черновика')
                if t:
                    edit_task(engine, t)
            elif choice == '4':
                submissions = [s for s in engine.list_items('s') if s['status'] != 'active']
                if not submissions:
                    print('Обучающиеся пока не сдали ни одной работы. Утверждённые карточки — в пункте 7, начало обучения — в пункте 5.')
                    continue
                s = choose(submissions, 'Номер работы')
                if s:
                    review(engine, s)
            elif choice == '5':
                workflow = choose_workflow()
                tasks = engine.approved_tasks(workflow)
                if not tasks:
                    print('Нет утверждённых карточек. Создайте карточку в пункте 1 или 2, либо утвердите черновик в пункте 3.')
                    continue
                print('Будет выдана единственная утверждённая карточка.' if len(tasks) == 1 else 'Карточка будет выбрана случайно из утверждённых.')
                session = engine.start_assigned(input('Имя обучающегося: '), workflow)
                student(engine, session['id'])
            elif choice == '7':
                t = choose(engine.approved_tasks(), 'Номер карточки для просмотра преподавателем')
                if t:
                    show_task(t)
                    print('Для прохождения карточек выберите 5 «Начать обучение».')
            elif choice == '6':
                name = input('Имя обучающегося: ').strip()
                s = choose([s for s in engine.list_items('s') if s['student'] == name], 'Номер сеанса')
                if s:
                    student(engine, s['id'])
        except (KeyboardInterrupt, EOFError):
            print('\nДо встречи. Сохранённые работы останутся в папке data.'); return
        except Exception as exc:
            print('Не удалось выполнить действие:', exc)


if __name__ == '__main__':
    main()
