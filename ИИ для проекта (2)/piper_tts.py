"""Optional local Piper TTS for the browser training interface.

The project remains usable without Piper. If a supported Russian Piper voice and
runtime are present, applicant/service replicas are returned as local WAV data.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parent
VOICE_DIR = ROOT / 'piper_voices'
VOICE_ORDER = ('ru_RU-irina-medium', 'ru_RU-denis-medium', 'ru_RU-dmitri-medium')
_CACHE = {}
RUNTIME_DIR = ROOT / '.runtime'

def _portable_packages_dir() -> Path:
    """Resolve the active project-local Piper runtime.

    New launchers publish a versioned runtime and store its directory name in
    .runtime/piper-packages-path.txt.  The legacy piper_packages folder remains
    a fallback for older projects.  A marker uses a relative leaf name so the
    whole project stays portable when moved to another Windows folder.
    """
    marker = RUNTIME_DIR / 'piper-packages-path.txt'
    try:
        raw = marker.read_text(encoding='utf-8').strip()
    except OSError:
        raw = ''
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = RUNTIME_DIR / candidate
        if candidate.is_dir():
            return candidate
    return RUNTIME_DIR / 'piper_packages'

PORTABLE_PACKAGES = _portable_packages_dir()
if PORTABLE_PACKAGES.is_dir() and str(PORTABLE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PORTABLE_PACKAGES))


def _selftest_ready() -> bool:
    """On Windows, only advertise Piper after START.cmd completed a real WAV self-test."""
    if os.environ.get('PIPER_SELFTEST_BOOTSTRAP') == '1':
        return True
    if os.name != 'nt':
        return True
    marker = RUNTIME_DIR / 'piper-ready.json'
    try:
        data = json.loads(marker.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError):
        return False
    if data.get('ready') is not True:
        return False
    espeak = data.get('espeak_data_dir')
    if espeak and not (Path(espeak) / 'phontab').is_file():
        return False
    return True


def _espeak_data_dir() -> Path | None:
    """Resolve the short ASCII eSpeak data path prepared by PREPARE_PIPER.ps1."""
    env_path = os.environ.get('PIPER_ESPEAK_DATA_DIR', '').strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    marker = RUNTIME_DIR / 'piper-espeak-data-path.txt'
    try:
        raw = marker.read_text(encoding='utf-8-sig').strip()
    except OSError:
        raw = ''
    if raw:
        candidates.append(Path(raw))
    try:
        from piper.phonemize_espeak import ESPEAK_DATA_DIR  # type: ignore
        candidates.append(Path(ESPEAK_DATA_DIR))
    except (ImportError, OSError):
        pass
    for candidate in candidates:
        if (candidate / 'phontab').is_file():
            return candidate
    return None


def _voices():
    result = []
    for stem in VOICE_ORDER:
        model = VOICE_DIR / f'{stem}.onnx'
        config = VOICE_DIR / f'{stem}.onnx.json'
        # A Hugging Face/Xet pointer or an interrupted download may leave a tiny
        # placeholder file. Do not advertise it as a usable voice.
        if (model.is_file() and model.stat().st_size > 1_000_000 and
                config.is_file() and config.stat().st_size > 100):
            result.append({'id': stem, 'model': model, 'config': config})
    return result


def _executable():
    candidates = [
        ROOT / 'piper' / ('piper.exe' if __import__('os').name == 'nt' else 'piper'),
        ROOT / ('piper.exe' if __import__('os').name == 'nt' else 'piper'),
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return shutil.which('piper')


def status():
    voices = _voices()
    python_api = _python_available()
    executable = _executable()
    selftest_ready = _selftest_ready()
    ready = bool(voices and (python_api or executable) and selftest_ready)
    missing = [stem for stem in VOICE_ORDER if stem not in {v['id'] for v in voices}]
    return {
        'available': ready,
        'engine': 'piper' if ready else 'browser',
        'voices': [v['id'] for v in voices],
        'missing_voices': missing,
        'runtime': 'python' if python_api else ('executable' if executable else 'missing'),
        'selftest_ready': selftest_ready,
        'espeak_data_dir': str(_espeak_data_dir() or ''),
        'message': (f"Piper готов. Доступно голосов: {len(voices)}." if ready
                    else 'Модели Piper отсутствуют или загружены не полностью. Перезапустите START.cmd: он скачает голоса автоматически.' if not voices
                    else 'Piper установлен, но реальный WAV self-test не пройден. Перезапустите START.cmd и проверьте .runtime\\piper-selftest.log.' if not selftest_ready
                    else 'Модели найдены, но Piper runtime не установлен. Перезапустите START.cmd.'),
    }


def _python_available():
    if importlib.util.find_spec('piper') is None:
        return False
    try:
        from piper import PiperVoice  # type: ignore
        return PiperVoice is not None
    except (ImportError, OSError):
        return False


def _python_synthesize(text: str, voice_row: dict) -> bytes:
    from piper import PiperVoice  # type: ignore

    key = voice_row['id']
    voice = _CACHE.get(key)
    if voice is None:
        espeak_data_dir = _espeak_data_dir()
        try:
            if espeak_data_dir is not None:
                voice = PiperVoice.load(
                    str(voice_row['model']),
                    config_path=str(voice_row['config']),
                    espeak_data_dir=str(espeak_data_dir),
                )
            else:
                voice = PiperVoice.load(str(voice_row['model']), config_path=str(voice_row['config']))
        except TypeError:
            voice = PiperVoice.load(str(voice_row['model']), str(voice_row['config']))
        _CACHE[key] = voice
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()


def _exe_synthesize(text: str, voice_row: dict, executable: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        output = Path(tmp.name)
    try:
        command = [executable, '--model', str(voice_row['model']), '--config', str(voice_row['config']), '--output_file', str(output)]
        completed = subprocess.run(command, input=text, text=True, encoding='utf-8', capture_output=True, timeout=45)
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 44:
            raise RuntimeError('Piper не смог создать аудио.')
        return output.read_bytes()
    finally:
        output.unlink(missing_ok=True)


def synthesize(text: str, voice: str | None = None):
    if os.name == 'nt' and not _selftest_ready():
        raise RuntimeError('Piper не прошёл реальный WAV self-test. Перезапустите START.cmd и проверьте .runtime\\piper-selftest.log.')
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError('Текст для озвучивания должен содержать от 1 до 1200 символов.')
    voices = _voices()
    if not voices:
        raise RuntimeError('Модели Piper не найдены в папке piper_voices.')
    chosen = next((row for row in voices if row['id'] == voice), voices[0])
    python_api = _python_available()
    executable = _executable()
    if python_api:
        audio = _python_synthesize(text.strip(), chosen)
    elif executable:
        audio = _exe_synthesize(text.strip(), chosen, executable)
    else:
        raise RuntimeError('Piper не установлен. Используется голос браузера.')
    return {
        'engine': 'piper',
        'voice': chosen['id'],
        'mime': 'audio/wav',
        'audio': 'data:audio/wav;base64,' + base64.b64encode(audio).decode('ascii'),
    }
