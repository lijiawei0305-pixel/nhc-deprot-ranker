"""Harmless process-tree behaviours used by Phase 8A supervisor tests."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _write_pid(path: str | None, pid: int | None = None) -> None:
    if path is not None:
        Path(path).write_text(f"{os.getpid() if pid is None else pid}\n", encoding="ascii")


def _sleep(seconds: float) -> int:
    time.sleep(seconds)
    return 0


def _ignore_term(seconds: float, pid_file: str | None) -> int:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    _write_pid(pid_file)
    print("ready", flush=True)
    time.sleep(seconds)
    return 0


def _grandchild(
    seconds: float,
    pid_file: str | None,
    child_pid_file: str | None,
) -> int:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    _write_pid(pid_file)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "ignore-term",
        "--seconds",
        str(seconds),
    ]
    if child_pid_file is not None:
        command.extend(["--pid-file", child_pid_file])
    child = subprocess.Popen(command, close_fds=True)
    _write_pid(child_pid_file, child.pid)
    print(f"grandchild={child.pid}", flush=True)
    time.sleep(seconds)
    return 0


def _parent_exits_with_child(seconds: float, child_pid_file: str | None) -> int:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "sleep",
        "--seconds",
        str(seconds),
    ]
    child = subprocess.Popen(command, close_fds=True)
    _write_pid(child_pid_file, child.pid)
    print(f"child={child.pid}", flush=True)
    return 0


def _flood(byte_count: int) -> int:
    stdout_chunk = b"O" * 8192
    stderr_chunk = b"E" * 8192
    remaining = byte_count
    while remaining > 0:
        size = min(remaining, len(stdout_chunk))
        os.write(sys.stdout.fileno(), stdout_chunk[:size])
        os.write(sys.stderr.fileno(), stderr_chunk[:size])
        remaining -= size
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "success",
            "nonzero",
            "streams",
            "flood",
            "sleep",
            "ignore-term",
            "grandchild",
            "parent-exits-child",
        ),
    )
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--code", type=int, default=7)
    parser.add_argument("--bytes", type=int, default=1024 * 1024)
    parser.add_argument("--pid-file")
    parser.add_argument("--child-pid-file")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _write_pid(args.pid_file)
    if args.mode == "success":
        return 0
    if args.mode == "nonzero":
        return args.code
    if args.mode == "streams":
        print("stdout-message", flush=True)
        print("stderr-message", file=sys.stderr, flush=True)
        return 0
    if args.mode == "flood":
        return _flood(args.bytes)
    if args.mode == "sleep":
        return _sleep(args.seconds)
    if args.mode == "ignore-term":
        return _ignore_term(args.seconds, args.pid_file)
    if args.mode == "grandchild":
        return _grandchild(args.seconds, args.pid_file, args.child_pid_file)
    if args.mode == "parent-exits-child":
        return _parent_exits_with_child(args.seconds, args.child_pid_file)
    raise AssertionError(f"unhandled mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
