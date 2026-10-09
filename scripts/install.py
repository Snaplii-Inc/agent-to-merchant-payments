#!/usr/bin/env python3
"""Install and verify the Snaplii execution layer (snaplii CLI + snaplii-mcp) for AI agents.

Standard library only; runs on Python 3.8+; never logs in and never touches an API key.
JSON report on stdout, redacted logs on stderr; exit 0 only when status is "installed".
"""
from __future__ import annotations

import argparse
import collections
import datetime
import errno
import json
import os
import queue
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
INSTALLER_VERSION = "1"
SCHEMA = 1
MARKER_NAME = "snaplii-installer.json"
MUSE_HELPER = "/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py"
MUSE_SOCKET = "/run/hatch/auth/authd.sock"
INSTINCT_PREFIX = "INSTINCT_"
ACQUIRE_VERSION = "3.12"
MIN_PROTOCOL = "2024-11-05"
KNOWN_PROTOCOL = "2025-06-18"
HOSTS = ("claude-code", "claude-desktop", "codex", "cursor", "openclaw", "instinct")
NEED = {"mcp": (3, 10), "cli": (3, 9)}
DEADLINES = {"probe": 15, "metadata": 30, "version": 60, "doctor": 60, "venv": 120,
             "mcp": 20, "pip": 900, "uv": 600}
CLEANUP_BOUND = 10.0
MAX_LINE = 64 * 1024
MAX_LINES = 2000
MAX_BYTES = 256 * 1024
PROTOCOL_MAX_MESSAGE = 1024 * 1024
PROTOCOL_MAX_QUEUE = 64
PROTOCOL_MAX_QUEUE_BYTES = 4 * 1024 * 1024
UV_INSTALL_SH = "https://astral.sh/uv/install.sh"
UV_INSTALL_PS1 = "https://astral.sh/uv/install.ps1"
REPO = "Snaplii-Inc/agent-to-merchant-payments"
README_URL = "https://github.com/" + REPO + "#readme"

PIP_PASS = ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST", "PIP_CERT",
            "PIP_PROXY", "PIP_TIMEOUT")
PY_DROP = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONPYCACHEPREFIX")
UV_SCRUB = ("UV_NO_MANAGED_PYTHON", "UV_MANAGED_PYTHON", "UV_SYSTEM_PYTHON", "UV_PYTHON",
            "UV_PYTHON_DOWNLOADS", "UV_PYTHON_PREFERENCE")


def is_windows() -> bool:
    return os.name == "nt"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    sys.stderr.write("[snaplii-install] " + redact(message) + "\n")
    sys.stderr.flush()


# ----------------------------------------------------------------------------
# Failure type
# ----------------------------------------------------------------------------
class InstallFailure(Exception):
    def __init__(self, stage: str, code: str, message: str, remedy: str,
                 retryable: bool = False, diagnostics: str = "") -> None:
        super().__init__(code + ": " + message)
        self.stage, self.code, self.message, self.remedy = stage, code, message, remedy
        self.retryable, self.diagnostics = retryable, diagnostics

    def to_dict(self) -> Dict[str, object]:
        return {"stage": self.stage, "code": self.code, "message": redact(self.message),
                "remedy": redact(self.remedy), "retryable": self.retryable,
                "diagnostics": redact(self.diagnostics)}


# ----------------------------------------------------------------------------
# Redaction and bounded capture
# ----------------------------------------------------------------------------
_URL_CREDENTIALS = re.compile(r"(://)([^/\s@]+)@")
_SNAPLII_KEY = re.compile(r"snp_sk_[A-Za-z0-9_\-]+")
_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._\-]+")
_KEY_VALUE = re.compile(
    r"(?i)\b(token|access_token|api_key|apikey|session|password|secret|x-amz-signature|sig)"
    r"(\"?)(\s*[=:]\s*)(\"?)([^\s&\"',;}]+)")


def _redact_value(match) -> str:
    key, key_quote, separator, value_quote, value = match.groups()
    if key_quote and not value_quote:
        if value[:1] in "{[":
            return match.group(0)  # a JSON object or array: its own keys are redacted one by one
        return key + key_quote + separator + '"[redacted]"'  # keep a JSON document parseable
    return key + key_quote + separator + value_quote + "[redacted]"


def redact(text: str) -> str:
    text = _URL_CREDENTIALS.sub(r"\1[redacted]@", text)
    text = _SNAPLII_KEY.sub("[redacted]", text)
    text = _BEARER.sub(r"\1[redacted]", text)
    text = _KEY_VALUE.sub(_redact_value, text)
    return text


class LineBuffer:
    """Redacted, bounded capture of complete lines; overlong lines are discarded whole."""

    def __init__(self) -> None:
        self.lines = collections.deque()  # type: collections.deque
        self.bytes = 0
        self.discarded = 0

    def add_bytes(self, line: bytes) -> None:
        if len(line) > MAX_LINE:
            self.discard(len(line))
            return
        self.add_text(line.decode("utf-8", "replace"))

    def discard(self, nbytes: int) -> None:
        self.discarded += 1
        self.add_text("[line of %d bytes discarded]" % nbytes, already_safe=True)

    def add_text(self, text: str, already_safe: bool = False) -> None:
        text = text if already_safe else redact(text)
        self.lines.append(text)
        self.bytes += len(text)
        while self.lines and (self.bytes > MAX_BYTES or len(self.lines) > MAX_LINES):
            self.bytes -= len(self.lines.popleft())

    def text(self) -> str:
        return "\n".join(self.lines)

    def tail(self, lines: int = 40, limit: int = 8192) -> str:
        chunk = "\n".join(list(self.lines)[-lines:])
        return chunk[-limit:]


# ----------------------------------------------------------------------------
# Child environment policy
# ----------------------------------------------------------------------------
def child_env(base: Dict[str, str], check_mode: bool = False, for_uv: bool = False) -> Dict[str, str]:
    env = {k: v for k, v in base.items() if k not in PY_DROP and not k.startswith("PIP_")}
    for name in PIP_PASS:
        if name in base:
            env[name] = base[name]
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONIOENCODING": "utf-8",
                "PYTHONNOUSERSITE": "1"})
    if check_mode:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    if for_uv:
        for name in UV_SCRUB:
            env.pop(name, None)
    return env


# ----------------------------------------------------------------------------
# Host detection
# ----------------------------------------------------------------------------
def detect_host(environ: Dict[str, str], exists=os.path.exists) -> Dict[str, object]:
    instinct_vars = sorted(name for name in environ if name.startswith(INSTINCT_PREFIX))
    if exists(MUSE_HELPER) and exists(MUSE_SOCKET):
        detected = "muse"
    elif instinct_vars:
        detected = "instinct"
    else:
        detected = "unknown"
    return {"detected": detected, "instinct_variables": instinct_vars, "platform": sys.platform}


# ----------------------------------------------------------------------------
# Destination
# ----------------------------------------------------------------------------
def home_dir(environ: Dict[str, str]) -> str:
    return environ.get("HOME") or environ.get("USERPROFILE") or os.path.expanduser("~")


def config_dir(environ: Dict[str, str]) -> str:
    configured = environ.get("SNAPLII_CONFIG_PATH")
    if configured:
        return os.path.dirname(os.path.abspath(os.path.expanduser(configured)))
    return os.path.join(home_dir(environ), ".snaplii")


def _occupied(message: str) -> InstallFailure:
    return InstallFailure("destination", "venv_path_occupied", message,
                          "pass another --venv path; nothing was touched", retryable=False)


def _is_within(child: str, parent: str) -> bool:
    child, parent = os.path.normcase(child), os.path.normcase(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def resolve_destination(venv_arg: Optional[str], environ: Dict[str, str]) -> str:
    raw = venv_arg or os.path.join(home_dir(environ), ".snaplii-env")
    raw = os.path.abspath(os.path.expanduser(raw))
    if os.path.islink(raw):
        raise _occupied("%s is a symbolic link" % raw)
    parent = os.path.realpath(os.path.dirname(raw))
    resolved = os.path.join(parent, os.path.basename(raw))
    if os.path.lexists(resolved) and not os.path.isdir(resolved):
        raise _occupied("%s exists and is not a directory" % resolved)
    cfg = os.path.realpath(config_dir(environ))
    if _is_within(resolved, cfg) or _is_within(cfg, resolved):
        raise _occupied("%s overlaps the Snaplii configuration directory %s" % (resolved, cfg))
    return resolved


# ----------------------------------------------------------------------------
# Subprocess policy: deadlines, concurrent redacted readers, whole-tree cleanup
# ----------------------------------------------------------------------------
SURVIVORS = []  # type: List[int]
JOB = None      # type: Optional["WindowsJob"]


class ProtocolError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Sentinel:
    EOF, OVERSIZE, FLOOD = object(), object(), object()


class ProtocolQueue:
    """Bounded queue of complete protocol lines (count and bytes)."""

    def __init__(self) -> None:
        self.q = queue.Queue()  # type: queue.Queue
        self.bytes = 0
        self.lock = threading.Lock()

    def offer(self, line: bytes) -> bool:
        """Queue one message; False once the bound is exceeded, and the reader then stops."""
        with self.lock:
            if self.q.qsize() >= PROTOCOL_MAX_QUEUE or self.bytes + len(line) > PROTOCOL_MAX_QUEUE_BYTES:
                self.q.put(_Sentinel.FLOOD)
                return False
            self.bytes += len(line)
        self.q.put(line.decode("utf-8", "replace"))
        return True

    def signal(self, sentinel: object) -> None:
        self.q.put(sentinel)

    def take(self, timeout: float):
        item = self.q.get(timeout=timeout)
        if isinstance(item, str):
            with self.lock:
                self.bytes -= len(item.encode("utf-8"))
        return item


def _read_stream(stream, sink: LineBuffer, proto: Optional[ProtocolQueue]) -> None:
    limit = PROTOCOL_MAX_MESSAGE if proto is not None else MAX_LINE
    pending = bytearray()
    discarding = 0

    def emit(line: bytes) -> bool:
        if proto is None:
            sink.add_bytes(line)
            return True
        if len(line) > PROTOCOL_MAX_MESSAGE:
            proto.signal(_Sentinel.OVERSIZE)
            return True
        return proto.offer(line)

    try:
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
            if not chunk:
                break
            data = chunk
            while data:
                newline = data.find(b"\n")
                if discarding:
                    if newline < 0:
                        discarding += len(data)
                        data = b""
                        continue
                    discarding += newline
                    if proto is not None:
                        proto.signal(_Sentinel.OVERSIZE)
                    else:
                        sink.discard(discarding)
                    discarding = 0
                    data = data[newline + 1:]
                    continue
                if newline < 0:
                    pending += data
                    data = b""
                    if len(pending) > limit:
                        discarding = len(pending)
                        pending = bytearray()
                    continue
                pending += data[:newline]
                data = data[newline + 1:]
                line = bytes(pending).rstrip(b"\r")
                pending = bytearray()
                if not emit(line):
                    return
        if pending:
            emit(bytes(pending).rstrip(b"\r"))
        if discarding:
            if proto is not None:
                proto.signal(_Sentinel.OVERSIZE)
            else:
                sink.discard(discarding)
    finally:
        if proto is not None:
            proto.signal(_Sentinel.EOF)
        try:
            stream.close()
        except OSError:
            pass


def pid_alive(pid: int) -> bool:
    """True unless the pid is known to be gone; errs towards alive."""
    if is_windows():
        api = _win_api()
        return api["PidAlive"](pid) if api else True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reap(proc) -> None:
    try:
        proc.poll()
    except OSError:
        pass


def stop_tree(proc) -> List[int]:
    """Stop the child's whole process tree; return pids/groups still alive after the bound."""
    if is_windows():
        if JOB is not None and JOB.available:
            return JOB.terminate_members()
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=CLEANUP_BOUND)
        except (OSError, subprocess.SubprocessError):
            pass
        return []
    pgid = proc.pid

    def alive() -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def send(sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass

    for sig in (signal.SIGTERM, signal.SIGKILL):
        send(sig)
        end = time.monotonic() + CLEANUP_BOUND / 2
        while alive() and time.monotonic() < end:
            _reap(proc)
            time.sleep(0.05)
        if not alive():
            return []
    return [pgid]


class Child:
    """A subprocess under the installer's policy: deadline, redacted bounded capture, tree cleanup."""

    def __init__(self, argv: List[str], stage: str, deadline: float, env: Dict[str, str],
                 cwd: Optional[str] = None, pipe_stdin: bool = False, protocol: bool = False) -> None:
        self.argv, self.stage, self.deadline, self.env, self.cwd = list(argv), stage, float(deadline), env, cwd
        self.pipe_stdin, self.protocol = pipe_stdin, protocol
        self.stdout, self.stderr = LineBuffer(), LineBuffer()
        self.messages = ProtocolQueue() if protocol else None
        self.proc = None
        self.threads = []  # type: List[threading.Thread]
        self.returncode = None  # type: Optional[int]
        self.survivors = []  # type: List[int]
        self.started = 0.0
        self.stopped = False

    def __enter__(self) -> "Child":
        kwargs = {"stdin": subprocess.PIPE if self.pipe_stdin else subprocess.DEVNULL,
                  "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": self.env, "cwd": self.cwd}
        if is_windows():
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            self.proc = subprocess.Popen(self.argv, **kwargs)
        except OSError as exc:
            raise InstallFailure(self.stage, self.stage + "_spawn_failed",
                                 "could not start %s: %s" % (self.argv[0], exc),
                                 "check that the executable exists and is runnable")
        self.started = time.monotonic()
        for stream, sink, proto in ((self.proc.stdout, self.stdout, self.messages),
                                    (self.proc.stderr, self.stderr, None)):
            thread = threading.Thread(target=_read_stream, args=(stream, sink, proto), daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.stop()
        return False

    def remaining(self) -> float:
        return self.deadline - (time.monotonic() - self.started)

    def send(self, text: str) -> None:
        self.proc.stdin.write((text + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def close_stdin(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass

    def recv(self, timeout: Optional[float] = None) -> str:
        budget = self.remaining() if timeout is None else min(timeout, self.remaining())
        if budget <= 0:
            self._timeout()
        try:
            item = self.messages.take(budget)
        except queue.Empty:
            self._timeout()
        if item is _Sentinel.EOF:
            raise ProtocolError("eof")
        if item is _Sentinel.OVERSIZE:
            raise ProtocolError("oversize")
        if item is _Sentinel.FLOOD:
            raise ProtocolError("flood")
        return item

    def wait(self) -> int:
        while True:
            code = self.proc.poll()
            if code is not None:
                self.stop()  # group kill after a clean exit too, before joining the readers
                self.returncode = code
                return code
            if self.remaining() <= 0:
                self._timeout()
            time.sleep(0.05)

    def _timeout(self) -> None:
        self.stop()
        raise InstallFailure(self.stage, self.stage + "_timeout",
                             "%s did not finish within %d s" % (self.argv[0], int(self.deadline)),
                             "re-run the installer; if it repeats, report the diagnostics",
                             retryable=True, diagnostics=self.stderr.tail())

    def _join(self) -> None:
        for thread in self.threads:
            thread.join(5)

    def stop(self) -> List[int]:
        if self.proc is None or self.stopped:
            return self.survivors
        self.stopped = True
        survivors = stop_tree(self.proc)
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        self.returncode = self.proc.returncode
        self.close_stdin()
        self._join()
        if survivors:
            self.survivors = list(survivors)
            for pid in survivors:
                if pid not in SURVIVORS:
                    SURVIVORS.append(pid)
        return self.survivors


def run(argv: List[str], stage: str, deadline: float, env: Dict[str, str],
        cwd: Optional[str] = None) -> Child:
    with Child(argv, stage, deadline, env, cwd=cwd) as child:
        child.wait()
    return child


# ----------------------------------------------------------------------------
# Windows job object (ctypes); children inherit membership at creation
# ----------------------------------------------------------------------------
_WIN_API = None  # type: Optional[Dict[str, object]]


def _win_api() -> Optional[Dict[str, object]]:
    global _WIN_API
    if not is_windows():
        return None
    if _WIN_API is not None:
        return _WIN_API
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ULONG_PTR),
                    ("MaximumWorkingSetSize", ULONG_PTR), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ULONG_PTR), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ULONG_PTR), ("JobMemoryLimit", ULONG_PTR),
                    ("PeakProcessMemoryUsed", ULONG_PTR), ("PeakJobMemoryUsed", ULONG_PTR)]

    def set_kill_on_close(handle) -> bool:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return bool(k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)))

    def query_pids(handle) -> List[int]:
        count = 256
        while True:
            class LIST(ctypes.Structure):
                _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD),
                            ("NumberOfProcessIdsInList", wintypes.DWORD), ("ProcessIdList", ULONG_PTR * count)]
            data = LIST()
            if k32.QueryInformationJobObject(handle, 3, ctypes.byref(data), ctypes.sizeof(data), None):
                return [int(data.ProcessIdList[i]) for i in range(data.NumberOfProcessIdsInList)]
            if data.NumberOfAssignedProcesses <= count:
                return []
            count = int(data.NumberOfAssignedProcesses) + 16

    def is_in_job(handle, job) -> bool:
        flag = wintypes.BOOL()
        return bool(k32.IsProcessInJob(handle, job, ctypes.byref(flag))) and bool(flag.value)

    def pid_alive_win(pid: int) -> bool:
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER means no such process
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)

    _WIN_API = {"CreateJobObjectW": k32.CreateJobObjectW, "SetKillOnClose": set_kill_on_close,
                "GetCurrentProcess": k32.GetCurrentProcess, "AssignProcessToJobObject": k32.AssignProcessToJobObject,
                "QueryProcessIds": query_pids, "OpenProcess": k32.OpenProcess, "IsProcessInJob": is_in_job,
                "TerminateProcess": k32.TerminateProcess, "CloseHandle": k32.CloseHandle, "PidAlive": pid_alive_win}
    return _WIN_API


class WindowsJob:
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self, api: Optional[Dict[str, object]] = None) -> None:
        self.api = api if api is not None else (_win_api() or {})
        self.handle = None
        self.available = False
        self.reason = ""
        if not self.api:
            self.reason = "not Windows"
            return
        handle = self.api["CreateJobObjectW"](None, None)
        if not handle:
            self.reason = "CreateJobObjectW failed"
            return
        if not self.api["SetKillOnClose"](handle):
            self.reason = "SetInformationJobObject failed"
            self.api["CloseHandle"](handle)
            return
        if not self.api["AssignProcessToJobObject"](handle, self.api["GetCurrentProcess"]()):
            self.reason = "AssignProcessToJobObject failed (nested jobs unsupported or forbidden by a hosting job)"
            self.api["CloseHandle"](handle)
            return
        self.handle = handle
        self.available = True

    def member_pids(self) -> List[int]:
        return [pid for pid in self.api["QueryProcessIds"](self.handle) if pid != os.getpid()]

    def terminate_members(self, bound: float = CLEANUP_BOUND) -> List[int]:
        end = time.monotonic() + bound
        while True:
            pids = self.member_pids()
            if not pids:
                return []
            for pid in pids:
                handle = self.api["OpenProcess"](self.PROCESS_TERMINATE | self.PROCESS_QUERY_LIMITED_INFORMATION,
                                                 False, pid)
                if not handle:
                    continue
                try:
                    if self.api["IsProcessInJob"](handle, self.handle):
                        self.api["TerminateProcess"](handle, 1)
                finally:
                    self.api["CloseHandle"](handle)
            if time.monotonic() >= end:
                return self.member_pids()
            time.sleep(0.2)


# ----------------------------------------------------------------------------
# Ownership: lock, reservation, classification
# ----------------------------------------------------------------------------
def unwritable(path: str, exc: OSError) -> InstallFailure:
    return InstallFailure("destination", "destination_unwritable",
                          "cannot create %s: %s" % (path, exc),
                          "pass a writable --venv path", retryable=False,
                          diagnostics="errno %s: %s" % (exc.errno, exc.strerror))


def _write_atomic(path: str, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class Lock:
    def __init__(self, venv_path: str) -> None:
        self.path = venv_path + ".lock"
        self.held = False

    def _read(self) -> Dict[str, object]:
        try:
            with open(self.path, "r") as handle:
                record = json.load(handle)
            return record if isinstance(record, dict) else {}
        except (OSError, ValueError):
            return {}

    def _locked(self) -> InstallFailure:
        record = self._read()
        if record.get("state") == "cleanup_incomplete":
            pids = [int(p) for p in record.get("surviving_pids", []) if str(p).isdigit()]
            alive = [p for p in pids if pid_alive(p)]
            if alive or not pids:
                remedy = ("processes %s from an earlier run may still be writing to the environment; wait "
                          "until they have exited, then delete %s" % (alive or pids, self.path))
            else:
                remedy = "the earlier run's processes %s have exited; delete %s and re-run" % (pids, self.path)
        else:
            remedy = "wait for the other installer, or delete %s if no installer is running" % self.path
        return InstallFailure("destination", "venv_locked", "another installer holds " + self.path,
                              remedy, retryable=True)

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise self._locked()
        except OSError as exc:
            raise unwritable(self.path, exc)
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created": utc_now()}))
        self.held = True

    def retain(self, surviving_pids: List[int]) -> None:
        _write_atomic(self.path, json.dumps({"state": "cleanup_incomplete", "surviving_pids": list(surviving_pids),
                                             "pid": os.getpid(), "created": utc_now()}))
        self.held = False

    def release(self) -> None:
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.held = False


class ForeignFile(Exception):
    pass


class Reservation:
    def __init__(self, venv_path: str) -> None:
        self.venv = venv_path
        self.path = venv_path + ".creating"
        self.parent = os.path.dirname(venv_path)
        self.name = os.path.basename(venv_path)

    def read(self) -> Optional[Dict[str, object]]:
        try:
            with open(self.path, "r") as handle:
                text = handle.read()
        except FileNotFoundError:
            return None
        except OSError:
            raise ForeignFile(self.path)
        try:
            record = json.loads(text)
        except ValueError:
            raise ForeignFile(self.path)
        if not isinstance(record, dict) or record.get("installer") != "snaplii-install" or record.get("schema") != SCHEMA:
            raise ForeignFile(self.path)
        return record

    def publish(self, record: Dict[str, object], update: bool = False) -> None:
        payload = dict(record)
        payload.update({"installer": "snaplii-install", "schema": SCHEMA})
        try:
            fd, tmp = tempfile.mkstemp(prefix=self.name + ".creating.", suffix=".tmp", dir=self.parent)
        except OSError as exc:
            raise unwritable(self.path, exc)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps(payload))
                handle.flush()
                os.fsync(handle.fileno())
            if update:
                os.replace(tmp, self.path)
            else:
                os.link(tmp, self.path)
                os.remove(tmp)
        except FileExistsError:
            os.remove(tmp)
            raise
        except OSError as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise unwritable(self.path, exc)

    def remove(self) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass

    def leftovers(self) -> List[str]:
        prefix = self.name + ".creating."
        try:
            names = os.listdir(self.parent)
        except OSError:
            return []
        return sorted(os.path.join(self.parent, n) for n in names if n.startswith(prefix) and n.endswith(".tmp"))


def dir_identity(path: str) -> List[int]:
    info = os.stat(path)
    return [int(info.st_dev), int(info.st_ino)]


def marker_ours(venv_path: str) -> bool:
    try:
        with open(os.path.join(venv_path, MARKER_NAME), "r") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return False
    return isinstance(record, dict) and record.get("installer") == "snaplii-install" and record.get("schema") == SCHEMA


def classify_destination(venv_path: str, reservation: Reservation, check_mode: bool,
                         warnings: List[str]) -> str:
    for leftover in reservation.leftovers():
        warnings.append("leftover temporary file %s from an interrupted run; delete it manually" % leftover)
    foreign = False
    try:
        record = reservation.read()
    except ForeignFile:
        record, foreign = None, True
    exists = os.path.isdir(venv_path)
    if exists and marker_ours(venv_path):
        if foreign:
            warnings.append("%s exists but was not written by this installer; left alone" % reservation.path)
        elif record is not None:
            if check_mode:
                warnings.append("leftover reservation %s; check mode leaves it in place" % reservation.path)
            else:
                reservation.remove()
        return "ours"
    if foreign:
        raise _occupied("%s exists and was not written by this installer" % reservation.path)
    if record is not None:
        identity = record.get("identity")
        if not exists:
            return "rebuild"
        if identity is None:
            if not os.listdir(venv_path):
                return "rebuild"
            raise _occupied("%s is not empty and its reservation recorded no identity" % venv_path)
        if dir_identity(venv_path) == list(identity):
            return "rebuild"
        raise _occupied("%s does not match the identity its reservation recorded" % venv_path)
    if exists:
        raise _occupied("%s exists and was not created by this installer" % venv_path)
    return "new"


# ----------------------------------------------------------------------------
# Interpreter discovery and acquisition
# ----------------------------------------------------------------------------
PROBE_CODE = ("import json, sys\n"
              "try:\n    import venv, ensurepip\n    ok = True\nexcept Exception:\n    ok = False\n"
              "print(json.dumps({'version': list(sys.version_info[:3]), 'executable': sys.executable, "
              "'venv_ok': ok}))")


def required_python_remedy() -> str:
    return ("install Python 3.12 (macOS: brew install python@3.12; Debian/Ubuntu: apt install python3.12 "
            "python3.12-venv; Windows: winget install Python.Python.3.12) or uv "
            "(curl -LsSf https://astral.sh/uv/install.sh | sh), then re-run the installer")


def python_too_old_failure(detail: str) -> InstallFailure:
    return InstallFailure("python", "python_too_old", detail, required_python_remedy(), retryable=True)


def download_failed(detail: str, diagnostics: str) -> InstallFailure:
    return InstallFailure("python", "python_download_failed", detail, required_python_remedy(),
                          retryable=True, diagnostics=diagnostics)


def candidate_argvs(python_arg: Optional[str], cli_only: bool, environ: Dict[str, str], platform: str,
                    uv_path: Optional[str], which=shutil.which) -> List[List[str]]:
    minors = [14, 13, 12, 11, 10] + ([9] if cli_only else [])
    path = environ.get("PATH")
    argvs = []  # type: List[List[str]]
    if python_arg:
        argvs.append([python_arg])
    argvs.append([sys.executable])
    for minor in minors:
        found = which("python3.%d" % minor, path=path)
        if found:
            argvs.append([found])
    for name in ("python3", "python"):
        found = which(name, path=path)
        if found:
            argvs.append([found])
    if platform == "win32":
        launcher = which("py", path=path)
        if launcher:
            for minor in minors:
                argvs.append([launcher, "-3.%d" % minor])
    if uv_path:
        for minor in minors:
            argvs.append([uv_path, "python", "find", "--no-project", "3.%d" % minor])
    return argvs


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def probe(argv: List[str], env: Dict[str, str]) -> Optional[Dict[str, object]]:
    try:
        if len(argv) >= 3 and argv[1:3] == ["python", "find"]:
            found = run(argv, "probe", DEADLINES["probe"], env)
            if found.returncode != 0 or not _last_line(found.stdout.text()):
                return None
            argv = [_last_line(found.stdout.text())]
        child = run(list(argv) + ["-c", PROBE_CODE], "probe", DEADLINES["probe"], env)
    except InstallFailure:
        return None
    if child.returncode != 0:
        return None
    try:
        info = json.loads(_last_line(child.stdout.text()))
    except ValueError:
        return None
    if not isinstance(info, dict) or "version" not in info:
        return None
    info["argv"] = list(argv)
    return info


def qualifying_candidates(argvs: List[List[str]], need: Tuple[int, int], env: Dict[str, str],
                          python_arg: Optional[str], warnings: List[str]) -> List[Dict[str, object]]:
    seen = set()
    out = []  # type: List[Dict[str, object]]
    for argv in argvs:
        if len(argv) == 1:
            resolved = os.path.realpath(argv[0])
            if resolved in seen:
                continue  # an alias of an interpreter already probed
            seen.add(resolved)
        info = probe(argv, env)
        reason = None
        if info is None:
            reason = "not runnable"
        elif tuple(info["version"][:2]) < need:
            reason = "Python %s is older than %d.%d" % (".".join(map(str, info["version"])), need[0], need[1])
        elif not info.get("venv_ok"):
            reason = "cannot import venv/ensurepip (install the python3-venv package or use another interpreter)"
        if reason:
            log("candidate %s skipped: %s" % (" ".join(argv), reason))
            if python_arg and argv == [python_arg]:
                warnings.append("--python %s skipped: %s" % (python_arg, reason))
            continue
        key = os.path.realpath(str(info["executable"]))
        if any(os.path.realpath(str(c["executable"])) == key for c in out):
            continue
        seen.add(key)
        out.append(info)
    return out


def uv_binary() -> str:
    return "uv.exe" if is_windows() else "uv"


def locate_uv(environ: Dict[str, str], which=shutil.which, exists=os.path.exists) -> Optional[str]:
    found = which("uv", path=environ.get("PATH"))
    if found:
        return found
    dirs = []  # type: List[str]
    for var in ("UV_INSTALL_DIR", "XDG_BIN_HOME"):
        if environ.get(var):
            dirs.append(environ[var])
    if environ.get("XDG_DATA_HOME"):
        dirs.append(os.path.join(environ["XDG_DATA_HOME"], "..", "bin"))
    dirs.append(os.path.join(home_dir(environ), ".local", "bin"))
    for directory in dirs:
        candidate = os.path.normpath(os.path.join(os.path.expanduser(directory), uv_binary()))
        if exists(candidate):
            return candidate
    return None


def install_uv(environ: Dict[str, str], env: Dict[str, str], which=shutil.which) -> str:
    target = environ.get("UV_INSTALL_DIR") or os.path.join(home_dir(environ), ".local", "bin")
    env = dict(env)
    env["UV_INSTALL_DIR"] = target
    env["UV_NO_MODIFY_PATH"] = "1"
    path = environ.get("PATH")
    if is_windows():
        if not which("powershell", path=path):
            raise python_too_old_failure("no suitable Python and PowerShell is unavailable to install uv")
        argv = ["powershell", "-ExecutionPolicy", "ByPass", "-c", "irm %s | iex" % UV_INSTALL_PS1]
    else:
        if which("curl", path=path):
            fetch = "curl -LsSf %s" % UV_INSTALL_SH
        elif which("wget", path=path):
            fetch = "wget -qO- %s" % UV_INSTALL_SH
        else:
            raise python_too_old_failure("no suitable Python and neither curl nor wget is available to install uv")
        argv = ["sh", "-c", fetch + " | sh"]
    log("installing uv into " + target)
    child = run(argv, "uv", DEADLINES["uv"], env)
    binary = os.path.join(target, uv_binary())
    if child.returncode != 0 or not os.path.exists(binary):
        raise download_failed("installing uv failed", child.stderr.tail())
    return binary


def acquire_python(environ: Dict[str, str], env: Dict[str, str], need: Tuple[int, int]) -> Dict[str, object]:
    uv = locate_uv(environ)
    acquired_by = "uv"
    if uv is None:
        uv = install_uv(environ, env)
        acquired_by = "uv-installed"
    log("acquiring CPython %s with uv" % ACQUIRE_VERSION)
    child = run([uv, "python", "install", "--no-bin", "--no-registry", ACQUIRE_VERSION], "uv", DEADLINES["uv"], env)
    if child.returncode != 0:
        raise download_failed("uv could not install CPython %s" % ACQUIRE_VERSION, child.stderr.tail())
    found = run([uv, "python", "find", "--no-project", "--managed-python", ACQUIRE_VERSION], "uv",
                DEADLINES["probe"], env)
    executable = _last_line(found.stdout.text())
    if found.returncode != 0 or not executable:
        raise download_failed("uv installed CPython %s but could not locate it" % ACQUIRE_VERSION, found.stderr.tail())
    info = probe([executable], env)
    if info is None or tuple(info["version"][:2]) < need or not info.get("venv_ok"):
        raise download_failed("the interpreter uv provided does not qualify", "")
    info["acquired_by"] = acquired_by
    return info


# ----------------------------------------------------------------------------
# Virtual environment protocol
# ----------------------------------------------------------------------------
INFO_CODE = ("import json, sys\nprint(json.dumps({'version': list(sys.version_info[:3]), 'prefix': sys.prefix, "
             "'executable': sys.executable}))")


def venv_bin_dir(venv: str) -> str:
    return os.path.join(venv, "Scripts" if is_windows() else "bin")


def venv_python(venv: str) -> str:
    return os.path.join(venv_bin_dir(venv), "python.exe" if is_windows() else "python")


def venv_exe(venv: str, name: str) -> str:
    return os.path.join(venv_bin_dir(venv), name + (".exe" if is_windows() else ""))


def interpreter_info(python_exe: str, env: Dict[str, str]) -> Optional[Dict[str, object]]:
    try:
        child = run([python_exe, "-c", INFO_CODE], "probe", DEADLINES["probe"], env)
    except InstallFailure:
        return None
    if child.returncode != 0:
        return None
    try:
        info = json.loads(_last_line(child.stdout.text()))
    except ValueError:
        return None
    return info if isinstance(info, dict) else None


def pip_works(python_exe: str, env: Dict[str, str]) -> bool:
    try:
        return run([python_exe, "-m", "pip", "--version"], "probe", DEADLINES["metadata"], env).returncode == 0
    except InstallFailure:
        return False


def _same_dir(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def validate_existing(venv: str, need: Tuple[int, int], env: Dict[str, str]) -> Dict[str, object]:
    broken = InstallFailure("venv", "venv_broken", "%s is an environment of this installer but it no longer works" % venv,
                            "pass another --venv path", retryable=False)
    python = venv_python(venv)
    if not os.path.exists(os.path.join(venv, "pyvenv.cfg")) or not os.path.exists(python):
        raise broken
    info = interpreter_info(python, env)
    if info is None or not _same_dir(str(info.get("prefix", "")), venv):
        raise broken
    if tuple(info["version"][:2]) < need:
        raise InstallFailure("venv", "venv_python_too_old",
                             "%s uses Python %s, which is too old for this install" % (venv, ".".join(map(str, info["version"]))),
                             "pass another --venv path", retryable=False)
    if not pip_works(python, env):
        raise broken
    return {"executable": python, "version": info["version"]}


def write_marker(venv: str, creator_exe: str) -> None:
    record = {"installer": "snaplii-install", "schema": SCHEMA, "python": creator_exe,
              "created": utc_now(), "installer_version": INSTALLER_VERSION}
    _write_atomic(os.path.join(venv, MARKER_NAME), json.dumps(record))


def build_venv(venv: str, reservation: Reservation, candidates: List[Dict[str, object]], need: Tuple[int, int],
               env: Dict[str, str], mode: str) -> Dict[str, object]:
    if mode == "new":
        reservation.publish({"pid": os.getpid(), "created": utc_now()})
    record = reservation.read() or {}
    last = ""
    for candidate in candidates:
        if not os.path.isdir(venv):
            if record.get("identity") is not None:
                record = {k: v for k, v in record.items() if k != "identity"}
                reservation.publish(record, update=True)
            try:
                os.mkdir(venv)
            except OSError as exc:
                raise unwritable(venv, exc)
        if record.get("identity") is None:
            record = dict(record, identity=dir_identity(venv), python=candidate["executable"])
            reservation.publish(record, update=True)
        if dir_identity(venv) != list(record["identity"]):
            raise _occupied("%s changed identity while being built" % venv)
        log("creating virtual environment at %s with %s" % (venv, candidate["executable"]))
        child = run(list(candidate["argv"]) + ["-m", "venv", "--clear", venv], "venv", DEADLINES["venv"], env)
        if child.returncode != 0:
            last = child.stderr.tail()
            log("venv creation with %s failed; trying the next interpreter" % candidate["executable"])
            continue
        python = venv_python(venv)
        info = interpreter_info(python, env)
        if info is None or not _same_dir(str(info.get("prefix", "")), venv) or not pip_works(python, env):
            last = "the new environment's interpreter or pip did not work"
            continue
        write_marker(venv, str(candidate["executable"]))
        reservation.remove()
        return {"executable": python, "version": info["version"], "state": "created" if mode == "new" else "rebuilt"}
    raise InstallFailure("venv", "venv_create_failed", "no interpreter could create a virtual environment at " + venv,
                         required_python_remedy(), retryable=True, diagnostics=last)


# ----------------------------------------------------------------------------
# pip
# ----------------------------------------------------------------------------
PIP_SIGNALS = [
    ("index_auth_failed", (re.compile(r"(?i)HTTP error 40[13]\b|\b40[13] Client Error|\b40[13] (?:Unauthorized|Forbidden)\b"),
                           "User for ", "credentials"), False),
    ("tls_failed", ("CERTIFICATE_VERIFY_FAILED", "SSLError", "certificate verify"), False),
    ("index_unreachable", ("Could not fetch URL", "connection", "name resolution", "timed out", "ProxyError",
                           "NewConnectionError", "Max retries exceeded"), True),
    ("package_unavailable", ("No matching distribution", "Could not find a version"), False),
    ("build_failed", ("Failed building wheel", "subprocess-exited-with-error"), False),
    ("disk_full", ("No space left on device", "[Errno 28]"), True),
    ("files_in_use", ("being used by another process", "WinError 32"), True),
    ("permission_denied", ("[Errno 13]", "Permission denied", "Access is denied"), False),
]

PIP_REMEDIES = {
    "index_auth_failed": "the package index rejected the credentials; supply a reachable index through PIP_INDEX_URL "
                         "(and PIP_EXTRA_INDEX_URL, PIP_TRUSTED_HOST, PIP_CERT, PIP_PROXY as needed), then re-run",
    "tls_failed": "TLS verification failed; set PIP_CERT or SSL_CERT_FILE to the CA bundle, then re-run",
    "index_unreachable": "the package index is unreachable; check the network, or supply a mirror through "
                         "PIP_INDEX_URL (pip.conf is not read by this installer), then re-run",
    "package_unavailable": "no release matches this Python; use Python 3.10+ (the installer can fetch 3.12 with uv) "
                           "or check the mirror's contents",
    "build_failed": "a dependency had to be built from source and failed; use a Python with prebuilt wheels "
                    "(3.10–3.13) or install the platform's build tools",
    "disk_full": "free disk space, then re-run",
    "files_in_use": "close the host that runs the Snaplii MCP server (it holds the files open), then re-run",
    "permission_denied": "the environment is not writable by this user; pass a writable --venv path",
    "dependency_conflict": "pip check reported conflicting packages in the environment; pass another --venv path",
    "pip_failed": "pip failed; read the diagnostics and re-run after fixing the cause",
}


def classify_pip(output: str) -> Tuple[str, bool]:
    for code, signals, retryable in PIP_SIGNALS:
        for signal_ in signals:
            if isinstance(signal_, str):
                if signal_.lower() in output.lower():
                    return code, retryable
            elif signal_.search(output):
                return code, retryable
    return "pip_failed", False


def pip_remedy(code: str) -> str:
    return PIP_REMEDIES.get(code, PIP_REMEDIES["pip_failed"])


def _pip_failure(code: str, retryable: bool, child: Child, what: str) -> InstallFailure:
    return InstallFailure("pip", code, "%s failed (%s)" % (what, code), pip_remedy(code),
                          retryable=retryable, diagnostics=child.stderr.tail() or child.stdout.tail())


def pip_floor_ok(python_exe: str, env: Dict[str, str]) -> bool:
    child = run([python_exe, "-m", "pip", "--version"], "pip", DEADLINES["metadata"], env)
    match = re.search(r"pip (\d+)\.(\d+)", child.stdout.text())
    if child.returncode != 0 or not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (23, 1)


def ensure_pip_floor(python_exe: str, env: Dict[str, str]) -> None:
    if pip_floor_ok(python_exe, env):
        return
    log("upgrading pip to 23.1 or newer")
    child = run([python_exe, "-m", "pip", "install", "--upgrade", "--no-input", "pip>=23.1"], "pip", DEADLINES["pip"], env)
    if child.returncode != 0:
        code, retryable = classify_pip(child.stderr.text() + "\n" + child.stdout.text())
        raise _pip_failure(code, retryable, child, "upgrading pip")


def package_specs(cli_only: bool, source: Optional[str]) -> List[str]:
    if source:
        specs = [os.path.join(source, "snaplii-cli")]
        if not cli_only:
            specs.append(os.path.join(source, "mcp-server"))
        return specs
    return ["snaplii-cli"] if cli_only else ["snaplii-cli", "snaplii-mcp"]


def pip_install(python_exe: str, specs: List[str], env: Dict[str, str]) -> None:
    argv = [python_exe, "-m", "pip", "install", "--upgrade", "--prefer-binary", "--no-input",
            "--keyring-provider", "disabled", "--timeout", "30", "--retries", "2"] + list(specs)
    for attempt in (1, 2):
        child = run(argv, "pip", DEADLINES["pip"], env)
        if child.returncode == 0:
            return
        code, retryable = classify_pip(child.stderr.text() + "\n" + child.stdout.text())
        if code == "index_unreachable" and attempt == 1:
            log("package index unreachable; retrying once in 3 s")
            time.sleep(3)
            continue
        raise _pip_failure(code, retryable, child, "pip install")


def install_packages(python_exe: str, cli_only: bool, source: Optional[str], env: Dict[str, str]) -> None:
    ensure_pip_floor(python_exe, env)
    pip_install(python_exe, package_specs(cli_only, source), env)
    check = run([python_exe, "-m", "pip", "check"], "pip", DEADLINES["metadata"], env)
    if check.returncode != 0:
        raise InstallFailure("pip", "dependency_conflict", "pip check reported a conflict", pip_remedy("dependency_conflict"),
                             retryable=False, diagnostics=check.stdout.tail() or check.stderr.tail())


# ----------------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------------
ISOLATED_KEYRING = "keyring.backends.fail.Keyring"


def metadata_version(python_exe: str, dist: str, env: Dict[str, str]) -> str:
    code = "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))"
    try:
        child = run([python_exe, "-c", code, dist], "metadata", DEADLINES["metadata"], env)
    except InstallFailure:
        return ""
    return _last_line(child.stdout.text()) if child.returncode == 0 else ""


def _cli_failed(detail: str, child: Optional[Child] = None) -> InstallFailure:
    return InstallFailure("verify", "cli_verification_failed", detail, "re-run the installer; if it repeats, report the diagnostics",
                          retryable=True, diagnostics=child.stderr.tail() if child else "")


def verify_cli(venv: str, env: Dict[str, str], tmpdir: str) -> Dict[str, object]:
    exe = venv_exe(venv, "snaplii")
    if not os.path.exists(exe):
        raise InstallFailure("verify", "cli_missing", "the snaplii executable is missing at " + exe,
                             "re-run the installer", retryable=True)
    child = run([exe, "--version"], "version", DEADLINES["version"], env)
    match = re.match(r"snaplii, version (\S+)", child.stdout.text().strip())
    if child.returncode != 0 or not match:
        raise _cli_failed("unexpected output from snaplii --version", child)
    version = match.group(1)
    meta = metadata_version(venv_python(venv), "snaplii-cli", env)
    if meta != version:
        raise _cli_failed("metadata reports snaplii-cli %s but --version prints %s" % (meta or "nothing", version))
    config = os.path.join(tmpdir, "doctor-config.json")
    doctor_env = dict(env, SNAPLII_CONFIG_PATH=config, PYTHON_KEYRING_BACKEND=ISOLATED_KEYRING)
    child = run([exe, "config", "doctor"], "doctor", DEADLINES["doctor"], doctor_env)
    try:
        doctor = json.loads(child.stdout.text())
    except ValueError:
        raise _cli_failed("snaplii config doctor did not print JSON", child)
    auth = doctor.get("authentication") if isinstance(doctor, dict) else None
    if child.returncode != 0 or "version" not in doctor or not isinstance(auth, dict) or "host" not in auth:
        raise _cli_failed("snaplii config doctor returned an unexpected document", child)
    return {"status": "installed", "version": version, "executable": exe, "host_seen_by_cli": auth["host"]}


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_protocol_date(value) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return value >= MIN_PROTOCOL


def _mcp_failed(detail: str, child: Optional[Child] = None) -> InstallFailure:
    return InstallFailure("verify", "mcp_handshake_failed", detail, "re-run the installer; if it repeats, report the diagnostics",
                          retryable=True, diagnostics=child.stderr.tail() if child else "")


def _await_response(child: Child, wanted: int) -> Dict[str, object]:
    while True:
        line = child.recv()
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("id") != wanted:
            continue
        if "error" in message:
            raise ProtocolError("error response: %s" % json.dumps(message["error"])[:200])
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProtocolError("malformed result for id %d" % wanted)
        return result


def mcp_handshake(argv: List[str], env: Dict[str, str], tmpdir: str, warnings: List[str]) -> int:
    config = os.path.join(tmpdir, "config.json")
    env = dict(env, SNAPLII_CONFIG_PATH=config, PYTHON_KEYRING_BACKEND=ISOLATED_KEYRING)
    count = 0
    with Child(argv, "mcp", DEADLINES["mcp"], env, cwd=tmpdir, pipe_stdin=True, protocol=True) as child:
        try:
            child.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": KNOWN_PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "snaplii-install", "version": INSTALLER_VERSION}}}))
            result = _await_response(child, 1)
            version = result.get("protocolVersion")
            if not valid_protocol_date(version):
                raise _mcp_failed("unsupported protocolVersion %r" % (version,), child)
            if version > KNOWN_PROTOCOL:
                warnings.append("the MCP server negotiated protocol %s, newer than the %s this installer knows"
                                % (version, KNOWN_PROTOCOL))
            capabilities = result.get("capabilities")
            if not isinstance(capabilities, dict) or "tools" not in capabilities:
                raise _mcp_failed("the server reports no tools capability", child)
            child.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            found, cursor, next_id, pages = False, None, 2, 0
            while True:
                params = {"cursor": cursor} if cursor else {}
                child.send(json.dumps({"jsonrpc": "2.0", "id": next_id, "method": "tools/list", "params": params}))
                result = _await_response(child, next_id)
                next_id += 1
                pages += 1
                for tool in result.get("tools") or []:
                    count += 1
                    if isinstance(tool, dict) and tool.get("name") == "snaplii_config_show":
                        found = True
                if pages > 16 or count > 10000:
                    raise _mcp_failed("tools/list did not terminate within 16 pages", child)
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            if not found:
                raise _mcp_failed("snaplii_config_show is not among the server's tools", child)
        except ProtocolError as exc:
            raise _mcp_failed("transport failure: %s" % exc.reason, child)
        except OSError as exc:  # the server closed its input, e.g. a broken pipe on send
            raise _mcp_failed("transport failure: %s" % exc, child)
        finally:
            child.close_stdin()
            try:
                child.proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
    if os.path.exists(config):
        raise _mcp_failed("the server created a configuration file during verification")
    return count


def verify_mcp(venv: str, env: Dict[str, str], tmpdir: str, warnings: List[str]) -> Dict[str, object]:
    exe = venv_exe(venv, "snaplii-mcp")
    if not os.path.exists(exe):
        raise InstallFailure("verify", "mcp_missing", "the snaplii-mcp executable is missing at " + exe,
                             "re-run the installer", retryable=True)
    version = metadata_version(venv_python(venv), "snaplii-mcp", env)
    tools = mcp_handshake([exe], env, tmpdir, warnings)
    return {"status": "installed", "version": version, "executable": exe, "tools": tools}
