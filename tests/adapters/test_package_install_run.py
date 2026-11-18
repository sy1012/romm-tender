"""The package install runner over real child processes: its exit status, a start that fails, and a cancel."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from adapters.package_install_run import PackageInstallRunAdapter


async def test_it_answers_the_commands_exit_status():
    assert await PackageInstallRunAdapter().run([sys.executable, "-c", "raise SystemExit(3)"]) == 3


async def test_a_command_that_cannot_be_started_raises_os_error(tmp_path):
    with pytest.raises(OSError):
        await PackageInstallRunAdapter().run([str(tmp_path / "no-such-program")])


async def test_a_cancel_kills_the_command_and_its_children(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    task = asyncio.ensure_future(PackageInstallRunAdapter().run([sys.executable, "-c", script]))
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.02)
    child = int(pid_file.read_text())

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(100):
        if not _alive(child):
            break
        await asyncio.sleep(0.02)
    assert not _alive(child)


async def test_a_timeout_the_caller_sets_ends_the_command():
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.2):
            await PackageInstallRunAdapter().run([sys.executable, "-c", "import time; time.sleep(60)"])


def _alive(pid: int) -> bool:
    """Whether *pid* still runs; a zombie the init process has not reaped yet counts as gone."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
            return stat.read().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False
    except OSError:
        return os.path.exists(f"/proc/{pid}")
