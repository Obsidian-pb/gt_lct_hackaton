"""Opt-in real AI smoke test. Uses isolated technical-test records."""
from pathlib import Path
from ai_core import Engine
from provider import AIProvider


def main():
    e=Engine(AIProvider(), Path(__file__).with_name('test-output'))
    print('1/4 ИИ создаёт вариант ДДС…',flush=True)
    t=e.draft('Повреждение водопроводной трубы во дворе вымышленного Учебного города. Ошибка в номере дома обнаруживается по приложенному уточнению 112.', 'hard', 'dds')
    e.approve(t['id'],'Технический тест — не учебное утверждение')
    sid=e.start(t['id'],'Тест ДДС')['id']; e.connect_service(sid)
    e.set_channel(sid,'drop');e.ask(sid,'Лесная 987654 — это сообщение должно потеряться целиком.')
    e.connect_service(sid)
    print('2/4 Проверка разговора после обрыва…',flush=True)
    reply=e.ask(sid,'Связь оборвалась. Повторите, какой адрес вы успели услышать?')
    print('Служба:',reply,flush=True)
    assert '987654' not in reply, 'Служба выдала недоставленный номер'
    print('3/4 Передача уточнённого сообщения…',flush=True)
    reply=e.ask(sid,f"Передаю сообщение: адрес {t['fields']['address']['expected']}. {t['fields']['incident']['expected']}. Подтвердите, что приняли.")
    print('Служба:',reply,flush=True)
    e.submit(sid)
    print('4/4 Предварительный разбор ИИ…',flush=True)
    result=e.assess(sid)
    assert len(result['fields'])==11
    assert e.student_view(sid)['result'] is None
    print('OK: две роли разделены, потерянный адрес не раскрыт, 11 критериев ожидают решения преподавателя.',sid,flush=True)


if __name__=='__main__':main()
