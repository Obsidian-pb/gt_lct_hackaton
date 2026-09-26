"""Optional local Piper TTS for the browser training interface.

The project remains usable without Piper. If a supported Russian Piper voice and
runtime are present, applicant/service replicas are returned as local WAV data.
"""
from __future__ import annotations

import base64
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave

ROOT = Path(__file__).resolve().parent
VOICE_DIR = ROOT / 'piper_voices'
VOICE_ORDER = ('ru_RU-irina-medium', 'ru_RU-denis-medium', 'ru_RU-dmitri-medium')
_CACHE = {}


def _voices():
    result = []
    for stem in VOICE_ORDER:
        model = VOICE_DIR / f'{stem}.onnx'
        config = VOICE_DIR / f'{stem}.onnx.json'
        if model.is_file() and config.is_file():
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
    python_api = importlib.util.find_spec('piper') is not None
    executable = _executable()
    return {
        'available': bool(voices and (python_api or executable)),
        'engine': 'piper' if voices and (python_api or executable) else 'browser',
        'voices': [v['id'] for v in voices],
        'runtime': 'python' if python_api else ('executable' if executable else 'missing'),
    }


def _python_synthesize(text: str, voice_row: dict) -> bytes:
    from piper.voice import PiperVoice  # type: ignore

    key = voice_row['id']
    voice = _CACHE.get(key)
    if voice is None:
        try:
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
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError('Текст для озвучивания должен содержать от 1 до 1200 символов.')
    voices = _voices()
    if not voices:
        raise RuntimeError('Модели Piper не найдены в папке piper_voices.')
    chosen = next((row for row in voices if row['id'] == voice), voices[0])
    python_api = importlib.util.find_spec('piper') is not None
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
