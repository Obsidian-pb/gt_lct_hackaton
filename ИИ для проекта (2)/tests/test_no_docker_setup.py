from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_no_docker_scripts_exist():
    assert (ROOT/'SETUP_SHARED_SERVER_NO_DOCKER.cmd').exists()
    assert (ROOT/'SETUP_SHARED_SERVER_NO_DOCKER.ps1').exists()


def test_default_setup_falls_back_without_docker():
    text=(ROOT/'SETUP_SHARED_SERVER.ps1').read_text(encoding='utf-8-sig')
    assert 'SETUP_SHARED_SERVER_NO_DOCKER.ps1' in text
    assert 'Docker не найден' in text


def test_no_docker_setup_creates_database_and_env():
    text=(ROOT/'SETUP_SHARED_SERVER_NO_DOCKER.ps1').read_text(encoding='utf-8-sig')
    assert 'createdb.exe' in text
    assert "CREATE ROLE trainer112" in text
    assert "DATABASE_URL=" in text
    assert "manage_db.py','migrate" in text
    assert 'docker compose' not in text.lower()


def test_setup_handles_offline_revocation_and_bom_without_erasing_cluster():
    text=(ROOT/'SETUP_SHARED_SERVER_NO_DOCKER.ps1').read_text(encoding='utf-8-sig')
    assert '--ssl-revoke-best-effort' in text
    assert '--insecure' not in text and '--ssl-no-revoke' not in text
    assert '-c $roleSql' in text
    assert '-f $sqlPath' not in text
    assert 'postgres-data-unconfigured-' in text
    assert 'Move-Item -LiteralPath $dataDir -Destination $backup' in text
    assert 'function Invoke-Python([string[]]$CommandArgs)' in text
    assert "Invoke-Python -CommandArgs @('manage_db.py','migrate')" in text
