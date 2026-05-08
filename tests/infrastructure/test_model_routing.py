from __future__ import annotations

from src.core.config import ModelProviderConfig, ModelRoutingConfig, ModelRoutingRulesConfig
from src.infrastructure.model_routing import ModelRouter, RouteRequest


def test_short_question_routes_to_simple_tier() -> None:
    router = ModelRouter(_routing_config())

    decision = router.decide(RouteRequest(input_text="翻译 hello world"))

    assert decision.tier == "simple"
    assert decision.reason == "simple_keyword"
    assert decision.matched_rules == ("simple_keyword:翻译",)


def test_complex_keyword_routes_to_complex_tier() -> None:
    router = ModelRouter(_routing_config())

    decision = router.decide(RouteRequest(input_text="帮我调试这个数据库连接 bug"))

    assert decision.tier == "complex"
    assert decision.reason == "complex_keyword"
    assert decision.matched_rules == ("complex_keyword:调试",)


def test_multiple_requested_tools_route_to_complex_tier() -> None:
    router = ModelRouter(_routing_config())

    decision = router.decide(
        RouteRequest(
            input_text="查资料并整理成报告",
            tool_names=("web_search", "deep_research"),
        )
    )

    assert decision.tier == "complex"
    assert decision.reason == "tool_count"
    assert decision.matched_rules == ("tool_count:2",)


def test_medium_uncertain_prompt_uses_default_complex_tier() -> None:
    router = ModelRouter(_routing_config())

    decision = router.decide(
        RouteRequest(
            input_text=(
                "请分析一下这个产品想法的可行性，用户是谁，主要风险是什么，"
                "以及第一版应该优先验证哪些部分。"
            )
        )
    )

    assert decision.tier == "complex"
    assert decision.reason == "default_tier"
    assert decision.matched_rules == ("default_tier:complex",)


def _routing_config() -> ModelRoutingConfig:
    return ModelRoutingConfig(
        enabled=True,
        default_tier="complex",
        tiers={
            "simple": ModelProviderConfig(
                provider="openai_compatible",
                model="simple-model",
            ),
            "complex": ModelProviderConfig(
                provider="openai_compatible",
                model="complex-model",
            ),
        },
        rules=ModelRoutingRulesConfig(
            simple_max_chars=40,
            complex_min_chars=120,
            tool_count_complex_threshold=2,
            simple_keywords=["翻译", "总结"],
            complex_keywords=["调试", "实现", "重构"],
        ),
    )
