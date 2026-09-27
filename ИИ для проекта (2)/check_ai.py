"""Local connectivity check for the external AI service. Never prints the key."""
from provider import AIProvider


def main():
    try:
        result = AIProvider().status()
    except Exception as exc:
        print('ИИ: ОШИБКА')
        print(str(exc))
        return 1
    print('ИИ: API ОТВЕЧАЕТ' if result.get('state') == 'available' else 'ИИ: НАСТРОЕН, КЛЮЧ НЕ ПРОВЕРЕН')
    print(result.get('message', 'ИИ доступен'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
