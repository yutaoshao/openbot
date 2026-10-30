from __future__ import annotations

import asyncio
import json
import shlex
import sys
from pathlib import Path

import pytest

from src.tools.builtin.bash_tool import BashTool
from src.tools.builtin.code_executor import CodeExecutorTool


async def _wait_for_file(path: Path) -> None:
    async def wait():
        while not path.exists():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), 2)


def _spawning_code(root: Path) -> str:
    child = (
        "import time; from pathlib import Path; "
        f"Path({str(root / 'child-ready')!r}).write_text('ready'); "
        "time.sleep(0.4); "
        f"Path({str(root / 'descendant-leaked')!r}).write_text('leaked'); time.sleep(1)"
    )
    return (
        "import subprocess,sys,time; from pathlib import Path\n"
        f"subprocess.Popen([sys.executable,'-B','-s','-c',{child!r}])\n"
        f"while not Path({str(root / 'child-ready')!r}).exists(): time.sleep(0.005)\n"
        f"Path({str(root / 'parent-ready')!r}).write_text('ready')\n"
        "time.sleep(2)\n"
    )


def _tool_and_arguments(kind: str, root: Path, timeout: float):
    code = _spawning_code(root)
    if kind == "python":
        return CodeExecutorTool(root), {"code": code, "timeout": timeout}
    script = root / "spawn.py"
    script.write_text(code)
    command = f"{shlex.quote(sys.executable)} -B -s {shlex.quote(str(script))}"
    return BashTool(root), {
        "description": "synthetic descendant cleanup",
        "command": command,
        "timeout_seconds": timeout,
    }


@pytest.mark.parametrize("kind", ["python", "shell"])
async def test_cancel_stops_execution_descendants_before_they_continue_side_effects(tmp_path, kind):
    tool, arguments = _tool_and_arguments(kind, tmp_path, 3)
    task = asyncio.create_task(tool.execute(arguments))
    await _wait_for_file(tmp_path / "parent-ready")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    await asyncio.sleep(0.5)
    assert not (tmp_path / "descendant-leaked").exists()


@pytest.mark.parametrize("kind", ["python", "shell"])
async def test_timeout_stops_execution_descendants(tmp_path, kind):
    tool, arguments = _tool_and_arguments(kind, tmp_path, 0.15)
    result = await tool.execute(arguments)
    assert result.is_error
    assert result.effects[0].status == "timeout"
    await asyncio.sleep(0.5)
    assert not (tmp_path / "descendant-leaked").exists()


async def test_python_uses_the_selected_global_working_directory(tmp_path):
    result = await CodeExecutorTool(tmp_path).execute(
        {"code": "import os,json; print(json.dumps(os.getcwd()))"}
    )
    assert not result.is_error
    assert Path(json.loads(result.content)) == tmp_path.resolve()


async def test_cancellation_during_process_creation_keeps_the_child_owned_and_reaped(tmp_path):
    from src.tools.processes import start_owned_process

    created = asyncio.Event()
    release = asyncio.Event()
    processes = []

    async def slow_creation():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-s",
            "-c",
            "import time; time.sleep(2)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        processes.append(process)
        created.set()
        await release.wait()
        return process

    task = asyncio.create_task(start_owned_process(slow_creation()))
    await created.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert processes[0].returncode is not None
