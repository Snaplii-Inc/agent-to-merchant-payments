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
            self.discarded += 1
            self.add_text("[line of %d bytes discarded]" % len(line), already_safe=True)
            return
        self.add_text(line.decode("utf-8", "replace"))

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
