"""Running an emulator's package install to its end, with a bound on it and a cancel that ends it.

A package install runs for minutes on a multi-gigabyte package, so it is run
on the loop as a child process rather than on a worker thread: a thread
cannot be cancelled, and a download's task, cancelled by the user or at
shutdown, must take the install down with it. The child is started in a
session of its own and the whole group is killed, because ``flatpak run``
starts the emulator as a grandchild; the wait after the kill is bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# How long a killed install is given to go before the caller is told regardless;
# ``SIGKILL`` ends any process that can be ended within it.
_REAP_SECONDS = 2.0


class PackageInstallRunAdapter:
    """Runs one install command to its end."""

    async def run(self, argv: Sequence[str]) -> int:
        """Run *argv* with no input and its output discarded, and answer its exit status.

        Raises ``OSError`` where it cannot be started. A cancel of the caller —
        its own timeout's among them — kills it and is re-raised once it has
        gone, or after :data:`_REAP_SECONDS`.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return await process.wait()
        except BaseException:
            await _kill(process)
            raise


async def _kill(process: asyncio.subprocess.Process) -> None:
    """Kill *process*'s group and wait a bounded time for it to go."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=_REAP_SECONDS)
