"""Cleanup for subprocess groups created by OpenBot execution tools."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio.subprocess import Process
    from collections.abc import Coroutine
    from typing import Any


async def start_owned_process(creation: Coroutine[Any, Any, Process]) -> Process:
    """Do not lose a just-spawned child if cancellation races its creation."""
    task = asyncio.create_task(creation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        process = await task
        await kill_owned_process_group(process)
        raise


async def kill_owned_process_group(process: Process) -> None:
    """Stop and reap a child started with ``start_new_session=True``.

    Kill the group even when its leader has exited: a descendant may still own
    a captured pipe or continue an external side effect after cancellation.
    """
    with contextlib.suppress(ProcessLookupError):
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.returncode is None:
            process.kill()
    await process.communicate()
