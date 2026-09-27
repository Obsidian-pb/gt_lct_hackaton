"""Explicit real-provider end-to-end smoke test, isolated from user exercises."""
from pathlib import Path
from ai_core import Engine, FIELDS
from provider import AIProvider


def main():
    engine = Engine(AIProvider(), Path(__file__).with_name('test-output'))
    print('1/4 ИИ: создание задания…', flush=True)
    task = engine.draft('Пожар в одноэтажном гараже. Заявитель не уверен, остался ли муж внутри. Только вымышленные адреса.', 'hard')
    engine.approve(task['id'], 'Автоматическая техническая проверка — не учебное утверждение')
    sid = engine.start(task['id'], 'Технический тест')['id']
    print('2/4 ИИ: вопрос заявителю…', flush=True)
    reply = engine.ask(sid, 'Назовите точный адрес и скажите, может ли кто-нибудь находиться внутри.')
    print('Заявитель:', reply, flush=True)
    engine.set_field(sid, 'incident', 'Пожар в гараже')
    engine.set_field(sid, 'people', 'Людей точно нет')
    engine.submit(sid)
    print('3/4 ИИ: предварительная проверка…', flush=True)
    result = engine.assess(sid)
    assert engine.student_view(sid)['result'] is None
    assert len(result['fields']) == len(FIELDS)
    decisions = {k: {'decision': 'edit', 'comment': 'Технический тест рассмотрения преподавателем'} for k in FIELDS}
    engine.finalize(sid, 'Тестовый преподаватель', 3, 'Технический проход завершён', decisions)
    assert engine.student_view(sid)['result']['grade'] == 3
    print('4/4 Ученик видит только опубликованное решение преподавателя. OK. Сеанс:', sid, flush=True)


if __name__ == '__main__':
    main()
