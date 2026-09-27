import json
import multiprocessing
from pathlib import Path
import stat
import subprocess
import sys
from unittest.mock import patch

from snaplii import auth
from snaplii.config_store import ConfigStore

DRIVER = Path(__file__).parent / "helpers" / "auth_process_driver.py"


def run_child(path, operation, host="muse"):
    result = subprocess.run([sys.executable, str(DRIVER), str(path), operation, host],
                            capture_output=True, text=True, timeout=15, check=True)
    assert not result.stderr
    assert "synthetic-process-token" not in result.stdout
    assert "hsurr:" not in result.stdout
    return json.loads(result.stdout)


def test_two_cli_processes_reuse_file_session_without_another_exchange(tmp_path):
    path = tmp_path / "config.json"
    first, second = run_child(path, "init"), run_child(path, "balance")
    assert first["pid"] != second["pid"]
    assert first["counts"] == {"auth": 1, "protected": 0}
    assert second["counts"] == {"auth": 0, "protected": 1}
    assert first["state"]["agent_id"] == second["state"]["agent_id"]
    assert first["state"]["has_valid_token"] is True
    assert second["state"]["has_valid_token"] is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_non_muse_memory_session_does_not_survive_new_process(tmp_path):
    path = tmp_path / "config.json"
    first = run_child(path, "init", "unknown")
    second = run_child(path, "balance", "unknown")
    # A one-shot CLI process refuses a memory-only session instead of printing
    # a success that the next process could never reuse.
    assert first["output"]["reason_code"] == "no_persistent_storage"
    assert first["state"]["credential_storage"] == "process memory"
    assert first["state"]["has_valid_token"] is False
    assert second["state"]["has_valid_token"] is False
    assert second["counts"] == {"auth": 0, "protected": 0}
    assert not path.exists() or "access_token" not in json.loads(path.read_text())


def test_expiry_blocks_protected_call_until_explicit_authentication(tmp_path):
    path = tmp_path / "config.json"
    first = run_child(path, "init")
    data = json.loads(path.read_text())
    data["token_expires_at"] = 1
    path.write_text(json.dumps(data))
    expired = run_child(path, "balance")
    assert expired["counts"] == {"auth": 0, "protected": 0}
    assert expired["output"]["next_action"]["argv"][-1] == "--vault-auth"
    refreshed = run_child(path, "init")
    assert refreshed["state"]["agent_id"] == first["state"]["agent_id"]
    assert refreshed["counts"] == {"auth": 1, "protected": 0}


def _concurrent_writer(path, barrier, kind):
    with patch.object(auth, "detect_muse", lambda: auth.MuseEnvironment(True, "test_only")):
        store = ConfigStore(Path(path))
        for n in range(12):
            barrier.wait(timeout=10)
            if kind == "session":
                store.commit_session("token-" + str(n), 3600, agent_id="agent-" + str(n),
                                     auth_method="vault", token_origin=auth.DEFAULT_ORIGIN)
            else:
                store.set("_version_check_test", n)


def test_process_writers_do_not_lose_session_or_version_updates(tmp_path):
    path = tmp_path / "config.json"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    workers = [context.Process(target=_concurrent_writer, args=(str(path), barrier, kind))
               for kind in ("session", "version")]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    store = ConfigStore(path)
    assert store.get_cached_token() == "token-11"
    assert store.get("agent_id") == "agent-11"
    assert store.get("_version_check_test") == 11
