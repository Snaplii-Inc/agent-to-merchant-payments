import os
import signal
import subprocess
import sys
import time

import pytest

POSIX = os.name != "nt"


def test_deadline_fires_and_stops_the_child(installer, fake_child):
    argv = fake_child("import time; time.sleep(30)")
    with pytest.raises(installer.InstallFailure) as info:
        with installer.Child(argv, "probe", 0.5, dict(os.environ)) as child:
            child.wait()
    assert info.value.code == "probe_timeout" and info.value.retryable is True
    assert child.proc.poll() is not None


def test_stdin_is_devnull_by_default_so_a_prompt_cannot_block(installer, fake_child):
    argv = fake_child("import sys; data = sys.stdin.read(); print('got %d bytes' % len(data))")
    child = installer.run(argv, "probe", 10, dict(os.environ))
    assert child.returncode == 0 and child.stdout.text() == "got 0 bytes"


def test_pipe_stdin_protocol_roundtrip(installer, fake_child):
    argv = fake_child("""
        import sys
        for line in sys.stdin:
            sys.stdout.write('echo:' + line); sys.stdout.flush()
    """)
    with installer.Child(argv, "mcp", 10, dict(os.environ), pipe_stdin=True, protocol=True) as child:
        child.send('{"id": 1}')
        assert child.recv(5) == 'echo:{"id": 1}'
        child.close_stdin()
        assert child.wait() == 0


def test_stderr_flood_is_bounded_and_does_not_deadlock(installer, fake_child):
    argv = fake_child("import sys\nfor i in range(400):\n    sys.stderr.write('e' * 1023 + '\\n')\nsys.stderr.flush()\nprint('done')")
    child = installer.run(argv, "pip", 20, dict(os.environ))
    assert child.returncode == 0 and child.stdout.text() == "done"
    assert len(child.stderr.text().encode()) <= installer.MAX_BYTES + 2 * installer.MAX_LINES


def test_overlong_stdout_line_is_discarded_whole_and_oversize_protocol_message_rejected(installer, fake_child):
    argv = fake_child("import sys\nsys.stdout.write('https://u:SENTINEL3' + 'x' * (70 * 1024) + '@h\\n'); sys.stdout.flush()")
    child = installer.run(argv, "pip", 20, dict(os.environ))
    assert "SENTINEL3" not in child.stdout.text() and child.stdout.discarded == 1
    argv = fake_child("import sys\nsys.stdout.write('{' + 'a' * (1100 * 1024) + '}\\n'); sys.stdout.flush()")
    with installer.Child(argv, "mcp", 20, dict(os.environ), pipe_stdin=True, protocol=True) as child:
        with pytest.raises(installer.ProtocolError) as info:
            child.recv(10)
        assert info.value.reason == "oversize"


def test_protocol_flood_and_eof(installer, fake_child):
    argv = fake_child("import sys\nfor i in range(200):\n    sys.stdout.write('{\"n\": %d}\\n' % i)\nsys.stdout.flush()")
    with installer.Child(argv, "mcp", 20, dict(os.environ), pipe_stdin=True, protocol=True) as child:
        time.sleep(0.5)
        assert child.messages.q.qsize() <= installer.PROTOCOL_MAX_QUEUE + 2  # reader stopped at the bound
        seen = []
        with pytest.raises(installer.ProtocolError) as info:
            for _ in range(300):
                seen.append(child.recv(5))
        assert info.value.reason == "flood" and len(seen) <= installer.PROTOCOL_MAX_QUEUE
    argv = fake_child("print('{}')")
    with installer.Child(argv, "mcp", 20, dict(os.environ), pipe_stdin=True, protocol=True) as child:
        assert child.recv(5) == "{}"
        with pytest.raises(installer.ProtocolError) as info:
            child.recv(5)
        assert info.value.reason == "eof"


def test_non_utf8_output_is_decoded_with_replacement(installer, fake_child):
    argv = fake_child("import sys\nsys.stderr.buffer.write(b'Zugriff \\xe4 Could not fetch URL\\n')")
    child = installer.run(argv, "pip", 10, dict(os.environ))
    assert "Could not fetch URL" in child.stderr.text()


@pytest.mark.skipif(not POSIX, reason="process groups are POSIX; Windows uses the job object")
def test_grandchild_does_not_survive_a_clean_exit(installer, fake_child, tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    argv = fake_child("""
        import subprocess, sys
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        open(%r, 'w').write(str(p.pid))
    """ % str(pidfile))
    started = time.monotonic()
    child = installer.run(argv, "venv", 20, dict(os.environ))
    assert time.monotonic() - started < 3  # the readers are not left waiting on the grandchild's pipes
    assert child.returncode == 0
    grandchild = int(pidfile.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)
    assert child.survivors == []


@pytest.mark.skipif(not POSIX, reason="POSIX signal test")
def test_keyboard_interrupt_still_stops_the_tree(installer, fake_child):
    argv = fake_child("import time; time.sleep(60)")
    with pytest.raises(KeyboardInterrupt):
        with installer.Child(argv, "pip", 60, dict(os.environ)) as child:
            raise KeyboardInterrupt
    assert child.proc.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(child.proc.pid, 0)


def test_survivors_are_recorded_module_wide(installer, fake_child, monkeypatch):
    monkeypatch.setattr(installer, "stop_tree", lambda proc: [4242])
    monkeypatch.setattr(installer, "SURVIVORS", [])
    child = installer.run(fake_child("print('x')"), "pip", 10, dict(os.environ))
    assert child.survivors == [4242] and installer.SURVIVORS == [4242]


def test_pid_alive_posix_or_windows(installer):
    assert installer.pid_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    if POSIX:
        assert installer.pid_alive(proc.pid) is False


class FakeWinApi(dict):
    def __init__(self, members, unopenable=(), not_in_job=(), assign_ok=True):
        self.members = list(members)
        self.unopenable, self.not_in_job = set(unopenable), set(not_in_job)
        self.terminated, self.closed, self.opened = [], [], []
        self.update({
            "CreateJobObjectW": lambda a, b: 0x10,
            "SetKillOnClose": lambda h: True,
            "GetCurrentProcess": lambda: 0x20,
            "AssignProcessToJobObject": lambda job, proc: assign_ok,
            "QueryProcessIds": lambda job: list(self.members) + [os.getpid()],
            "OpenProcess": self.open_process,
            "IsProcessInJob": lambda h, job: (h - 0x100) not in self.not_in_job,
            "TerminateProcess": self.terminate,
            "CloseHandle": lambda h: self.closed.append(h) or True,
        })

    def open_process(self, access, inherit, pid):
        self.opened.append(pid)
        return 0 if pid in self.unopenable else 0x100 + pid

    def terminate(self, handle, code):
        pid = handle - 0x100
        self.terminated.append(pid)
        self.members.remove(pid)
        return True


def test_windows_job_assigns_itself_and_terminates_members_through_the_opened_handle(installer):
    api = FakeWinApi(members=[11, 12], not_in_job=[12])
    job = installer.WindowsJob(api=api)
    assert job.available is True
    survivors = job.terminate_members(bound=1.0)
    assert api.terminated == [11]            # 12 was reused by a process outside the job: left alone
    assert 12 in api.opened and api.closed   # opened, checked, closed, never terminated
    assert survivors == [12]


def test_windows_job_unopenable_member_ends_after_the_bound(installer):
    api = FakeWinApi(members=[13], unopenable=[13])
    job = installer.WindowsJob(api=api)
    started = time.monotonic()
    assert job.terminate_members(bound=0.5) == [13]
    assert 0.4 <= time.monotonic() - started < 3


def test_windows_job_unavailable_when_assignment_fails(installer):
    api = FakeWinApi(members=[], assign_ok=False)
    job = installer.WindowsJob(api=api)
    assert job.available is False and "AssignProcessToJobObject" in job.reason


def test_protocol_message_just_over_the_limit_split_at_a_chunk_boundary_is_rejected(installer):
    import io
    proto = installer.ProtocolQueue()
    stream = io.BytesIO(b"{" + b"a" * installer.PROTOCOL_MAX_MESSAGE + b"}\n")
    installer._read_stream(stream, installer.LineBuffer(), proto)
    assert proto.take(1) is installer._Sentinel.OVERSIZE
