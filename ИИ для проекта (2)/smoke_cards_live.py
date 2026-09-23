"""Optional real-model smoke test; generated cards stay in test-output, never user storage."""
import json
from pathlib import Path
from card_factory import generate, approve
from provider import GigaChat
from card_reference import generate as generate_reference


def main():
    provider = GigaChat()
    out = Path(__file__).with_name('test-output') / 'cards-live'
    out.mkdir(parents=True, exist_ok=True)
    cases = [('fire', 'Задымление, сведения о людях неполные', 2, 2),
             ('road', 'ДТП, очевидец не знает число пострадавших', 1, 1),
             ('medical', 'Сообщение родственника о плохом самочувствии человека дома', 100, 100)]
    for category, topic, index, total in cases:
        result = generate(provider, dict(category=category, topic=topic, index=index, total=total))
        # Validate the review operation with a test identity, not an actual teacher approval.
        result['reference'] = generate_reference(provider, {'content': result['content']})
        approve(dict(content=result['content'], reference=result['reference'], reference_checked=True, teacher='Техническая проверка', note='Не является утверждением преподавателя'))
        (out / f'{category}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'category': category, 'model': result['model'], 'title': result['content']['title'],
                          'report': result['content']['report'], 'people': result['content']['fields']['people'],
                          'injured': result['content']['fields']['injured'], 'status': 'schema_valid'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
