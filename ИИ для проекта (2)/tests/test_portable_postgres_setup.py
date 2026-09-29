from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_no_docker_setup_offers_portable_first():
    text=(ROOT/'SETUP_SHARED_SERVER_NO_DOCKER.ps1').read_text(encoding='utf-8-sig')
    assert 'Portable PostgreSQL' in text
    assert 'postgresql-16.15-1-windows-x64-binaries.zip' in text
    assert "if($mode -eq '1'){Prepare-PortablePostgres" in text
    assert 'initdb.exe' in text
    assert 'PORTABLE_POSTGRES=1' in text

def test_shared_start_starts_portable_postgres():
    text=(ROOT/'START_SHARED_SERVER.ps1').read_text(encoding='utf-8-sig')
    assert "$env:PORTABLE_POSTGRES -eq '1'" in text
    assert 'START_PORTABLE_POSTGRES.ps1' in text

def test_shared_start_installs_dependencies_without_terminating_probe():
    text=(ROOT/'START_SHARED_SERVER.ps1').read_text(encoding='utf-8-sig')
    assert '-m pip show psycopg' not in text
    assert "Invoke-Python -CommandArgs @('-m','pip','install','-r','requirements-server.txt'" in text
    assert "$ErrorActionPreference = 'Continue'" in text
    assert 'if ($code -ne 0)' in text
    assert 'function Invoke-Python([string[]]$CommandArgs)' in text
    assert 'function Start-Python([string[]]$CommandArgs' in text
    assert '& $exe @prefix @CommandArgs' in text
    assert '$web = Start-Python $serverArgs $webOut $webErr' in text
    assert "Wait-Health 'http://127.0.0.1:8878/api/v1/health'" in text
    assert "Start-Process 'http://127.0.0.1:8878/'" in text

def test_stop_all_stops_portable_postgres():
    text=(ROOT/'STOP_ALL.ps1').read_text(encoding='utf-8-sig')
    assert 'STOP_PORTABLE_POSTGRES.ps1' in text
