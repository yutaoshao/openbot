from __future__ import annotations

from src.tools.builtin.code_executor import CodeExecutorTool


async def test_code_executor_returns_full_stdout_without_internal_truncation() -> None:
    tool = CodeExecutorTool()

    result = await tool.execute({"code": "print('x' * 12000)"})

    assert not result.is_error
    assert result.content == "x" * 12000
