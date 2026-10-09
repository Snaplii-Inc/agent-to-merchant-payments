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
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


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
    r"(\"?\s*[=:]\s*\"?)([^\s&\"',;}]+)")


def redact(text: str) -> str:
    text = _URL_CREDENTIALS.sub(r"\1[redacted]@", text)
    text = _SNAPLII_KEY.sub("[redacted]", text)
    text = _BEARER.sub(r"\1[redacted]", text)
    text = _KEY_VALUE.sub(lambda m: m.group(1) + m.group(2) + "[redacted]", text)
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
