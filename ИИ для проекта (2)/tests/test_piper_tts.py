import base64
import io
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import piper_tts


class PiperTtsTests(unittest.TestCase):
    def test_status_reports_model_and_runtime_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(piper_tts, 'VOICE_DIR', directory), patch.object(piper_tts, '_python_available', return_value=True), patch.object(piper_tts, '_executable', return_value=None):
                self.assertFalse(piper_tts.status()['available'])
                (directory / 'ru_RU-irina-medium.onnx').write_bytes(b'0' * 1_000_001)
                self.assertFalse(piper_tts.status()['available'])
                (directory / 'ru_RU-irina-medium.onnx.json').write_text('{' + ' ' * 120 + '}')
                status = piper_tts.status()
                self.assertTrue(status['available'])
                self.assertEqual(status['voices'], ['ru_RU-irina-medium'])

    def test_status_rejects_tiny_or_partial_onnx_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'ru_RU-irina-medium.onnx').write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
            (directory / 'ru_RU-irina-medium.onnx.json').write_text('{' + ' ' * 120 + '}')
            with patch.object(piper_tts, 'VOICE_DIR', directory), patch.object(piper_tts, '_python_available', return_value=True), patch.object(piper_tts, '_executable', return_value=None):
                status = piper_tts.status()
            self.assertFalse(status['available'])
            self.assertEqual(status['voices'], [])
            self.assertIn('ru_RU-irina-medium', status['missing_voices'])


    def test_portable_runtime_marker_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            active = runtime / 'piper_packages_py314_v1_8_0'
            active.mkdir()
            (runtime / 'piper-packages-path.txt').write_text(active.name, encoding='utf-8')
            with patch.object(piper_tts, 'RUNTIME_DIR', runtime):
                self.assertEqual(piper_tts._portable_packages_dir(), active)

    def test_synthesize_returns_playable_wav_payload(self):
        case = self
        class FakeVoice:
            @staticmethod
            def load(model, config_path):
                case.assertTrue(Path(model).is_file())
                case.assertTrue(Path(config_path).is_file())
                return FakeVoice()

            def synthesize_wav(self, text, writer):
                case.assertEqual(text, 'Очевидец отвечает')
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(22050)
                writer.writeframes(b'\x00\x00' * 100)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'ru_RU-irina-medium.onnx').write_bytes(b'0' * 1_000_001)
            (directory / 'ru_RU-irina-medium.onnx.json').write_text('{' + ' ' * 120 + '}')
            with patch.object(piper_tts, 'VOICE_DIR', directory), patch.object(piper_tts, '_python_available', return_value=True), patch.dict(sys.modules, {'piper': types.SimpleNamespace(PiperVoice=FakeVoice)}):
                piper_tts._CACHE.clear()
                result = piper_tts.synthesize('  Очевидец отвечает  ', 'ru_RU-irina-medium')
            self.assertEqual(result['voice'], 'ru_RU-irina-medium')
            self.assertEqual(result['mime'], 'audio/wav')
            with wave.open(io.BytesIO(base64.b64decode(result['audio'].split(',', 1)[1])), 'rb') as wav:
                self.assertEqual(wav.getframerate(), 22050)
                self.assertEqual(wav.getnframes(), 100)
            piper_tts._CACHE.clear()

    def test_espeak_data_marker_is_preferred(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            data = runtime / 'ascii-espeak'
            data.mkdir()
            (data / 'phontab').write_bytes(b'ok')
            (runtime / 'piper-espeak-data-path.txt').write_text(str(data), encoding='utf-8')
            with patch.object(piper_tts, 'RUNTIME_DIR', runtime), patch.dict(piper_tts.os.environ, {}, clear=True):
                self.assertEqual(piper_tts._espeak_data_dir(), data)

    def test_python_synthesize_passes_explicit_espeak_data_dir(self):
        case = self
        class FakeVoice:
            @staticmethod
            def load(model, config_path=None, espeak_data_dir=None):
                case.assertTrue(espeak_data_dir)
                case.assertTrue((Path(espeak_data_dir) / 'phontab').is_file())
                return FakeVoice()
            def synthesize_wav(self, text, writer):
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(22050); writer.writeframes(b'\x00\x00' * 10)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'ascii'; data.mkdir(); (data / 'phontab').write_bytes(b'ok')
            model = root / 'v.onnx'; model.write_bytes(b'0')
            config = root / 'v.onnx.json'; config.write_text('{}')
            row = {'id': 'v', 'model': model, 'config': config}
            with patch.object(piper_tts, '_espeak_data_dir', return_value=data), patch.dict(sys.modules, {'piper': types.SimpleNamespace(PiperVoice=FakeVoice)}):
                piper_tts._CACHE.clear()
                audio = piper_tts._python_synthesize('тест', row)
            self.assertTrue(audio.startswith(b'RIFF'))
            piper_tts._CACHE.clear()


if __name__ == '__main__':
    unittest.main()
