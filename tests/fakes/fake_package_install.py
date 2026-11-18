"""In-memory ``PackageInstallReader`` and ``PackageInstallControl`` for service tests."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from domain.package_install import PackageInstallPlan, PackageInstallRefused


class FakePackageInstallReader:
    """Answers ``answer`` for every question, and records each question in ``asked``.

    ``answer`` is ``None`` — no package to install — until a test sets one.
    """

    def __init__(self, answer: PackageInstallPlan | PackageInstallRefused | None = None) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str, tuple[str, ...]]] = []

    def package_install(
        self, system: str, content_path: str, *, writable: tuple[str, ...] = ()
    ) -> PackageInstallPlan | PackageInstallRefused | None:
        self.asked.append((system, content_path, writable))
        return self.answer


class FakePackageInstallControl:
    """Records each command in ``ran`` and runs ``effect`` for it; answers ``status``.

    ``effect`` is what the install does — by default nothing, so no boot file
    appears; ``write_boot_file`` makes one. ``raises`` is raised instead of
    running, and ``hangs`` waits until the caller is cancelled, recording the
    cancel in ``cancelled``.
    """

    def __init__(self) -> None:
        self.ran: list[tuple[str, ...]] = []
        self.effect: Callable[[], None] = lambda: None
        self.status = 0
        self.raises: BaseException | None = None
        self.hangs = False
        self.cancelled = False

    async def run(self, argv: Sequence[str]) -> int:
        self.ran.append(tuple(argv))
        if self.raises is not None:
            raise self.raises
        if self.hangs:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        self.effect()
        return self.status


def write_boot_file(path: str) -> Callable[[], None]:
    """An install effect that leaves a boot file at *path*."""

    def effect() -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"SCE")

    return effect
