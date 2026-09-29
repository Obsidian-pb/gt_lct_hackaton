"""Identify the files loaded by a local UI process without including user data or keys."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED_UI = ('api-client.js', 'api-routes.js', 'api-docs.html', 'react.html', 'react/app.js', 'student.css', 'teacher.css', 'workspace.css',
               'theme.css', 'making.css', 'cards.css', 'welcome.css', 'admin.css', 'hero-logo.svg',
               'hero-background.svg', 'address.css', 'geo/addresses.json', 'geo/map.json',
               'scenarios.html', 'scenarios.css', 'scenarios.js', 'enhancements.js',
               'banners/gas-leak.webp', 'banners/person-danger.webp', 'banners/road-injured.webp',
               'banners/mass-event.webp', 'banners/industrial-fire.webp', 'banners/residential-fire.webp')


def release_id(root=ROOT):
    digest = hashlib.sha256()
    files = list(root.glob('*.py')) + list((root / 'ui').rglob('*'))
    files += list((root / 'catalog').glob('*.json'))
    for path in sorted(p for p in files if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def validate_ui(root=ROOT):
    missing = [name for name in REQUIRED_UI if not (root / 'ui' / name).is_file()]
    if missing:
        raise RuntimeError('Получена неполная копия интерфейса. Обновите папку программы целиком. '
                           'Отсутствуют: ' + ', '.join('ui/' + x for x in missing))


def compatible_server(status, root, revision):
    return (isinstance(status, dict) and status.get('app') == 'ai-project-ui'
            and status.get('root') == str(root) and status.get('revision') == revision
            and '/student' in status.get('pages', []))
