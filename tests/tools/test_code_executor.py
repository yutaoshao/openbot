from __future__ import annotations

import json
import sys
from pathlib import Path

from src.tools.builtin.code_executor import CodeExecutorTool


async def test_code_executor_returns_full_stdout_without_internal_truncation() -> None:
    tool = CodeExecutorTool()

    result = await tool.execute({"code": "print('x' * 12000)"})

    assert not result.is_error
    assert result.content == "x" * 12000


async def test_code_executor_uses_the_service_interpreter() -> None:
    result = await CodeExecutorTool().execute(
        {"code": "import json,sys; print(json.dumps([sys.executable,list(sys.version_info[:2])]))"}
    )

    assert not result.is_error
    executable, version = json.loads(result.content)
    assert Path(executable).resolve() == Path(sys.executable).resolve()
    assert version == list(sys.version_info[:2])


async def test_code_executor_does_not_inherit_service_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENBOT_TEST_SECRET", "example-private-value")

    result = await CodeExecutorTool().execute(
        {"code": "import os; print(os.environ.get('OPENBOT_TEST_SECRET', 'not inherited'))"}
    )

    assert not result.is_error
    assert result.content == "not inherited"


async def test_code_executor_does_not_write_cache_into_imported_resources(tmp_path) -> None:
    (tmp_path / "preview_resource.py").write_text("value = 42\n")
    result = await CodeExecutorTool().execute(
        {
            "code": (
                f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
                "import preview_resource; print(preview_resource.value)"
            )
        }
    )

    assert not result.is_error
    assert result.content == "42"
    assert not (tmp_path / "__pycache__").exists()


async def test_code_executor_does_not_load_host_user_site() -> None:
    result = await CodeExecutorTool().execute(
        {
            "code": (
                "import json,site,sys; print(json.dumps(["
                "site.ENABLE_USER_SITE,site.getusersitepackages() in sys.path]))"
            )
        }
    )

    assert not result.is_error
    assert json.loads(result.content) == [False, False]
