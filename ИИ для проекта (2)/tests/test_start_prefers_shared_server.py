from pathlib import Path


def test_start_prefers_shared_server_after_setup():
    contents = (Path(__file__).resolve().parents[1] / "START.cmd").read_bytes()
    assert contents.startswith(b'@echo off')
    text = contents.decode('ascii')
    assert 'if exist "%~dp0.env.server"' in text
    assert 'START_SHARED_SERVER.cmd' in text
    assert ':shared' in text and 'exit /b %RC%' in text
