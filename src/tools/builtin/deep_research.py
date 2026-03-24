"""Deep research tool — wraps the DeepResearch engine as an agent tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from src.agent.deep_research import DeepResearch


class DeepResearchTool:
    """Tool that triggers multi-round deep research on a topic.

    The agent can invoke this tool when it detects a request for
    in-depth research, instead of doing multiple web_search calls.
    """

    def __init__(self, deep_research: DeepResearch) -> None:
        self._engine = deep_research

    @property
    def name(self) -> str:
        return "deep_research"

    @property
    def description(self) -> str:
        return (
            "Perform deep, multi-round research on a topic. "
            "Automatically plans search angles, executes multiple rounds "
            "of web search and content extraction, detects when new "
            "information is exhausted, and synthesizes a structured report. "
            "Use this for complex research tasks that need thorough investigation "
            "from multiple angles. Returns a comprehensive markdown report."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The research topic or question to investigate",
                },
                "max_rounds": {
                    "type": "integer",
                    "description": "Maximum number of search rounds (default: 5)",
                    "default": 5,
                },
            },
            "required": ["topic"],
        }

    @property
    def category(self) -> str:
        return "research"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        topic = args.get("topic", "")
        if not topic:
            return ToolResult(content="Topic is required", is_error=True)

        max_rounds = args.get("max_rounds", 5)

        try:
            report = await self._engine.research(topic, max_rounds=max_rounds)

            # Build summary with metadata
            meta = (
                f"\n\n---\n"
                f"Research completed: {report.rounds_executed} rounds, "
                f"{report.total_searches} searches, "
                f"{len(report.findings)} findings, "
                f"{len(report.sources)} sources"
            )
            if report.saturated:
                meta += " (saturated)"
            meta += f"\nLatency: {report.latency_ms}ms"

            return ToolResult(
                content=report.synthesis + meta,
                metadata={
                    "rounds": report.rounds_executed,
                    "findings": len(report.findings),
                    "sources": len(report.sources),
                    "saturated": report.saturated,
                    "latency_ms": report.latency_ms,
                },
            )

        except Exception as e:
            return ToolResult(content=f"Research failed: {e}", is_error=True)
