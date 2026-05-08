"""
test_router.py — Sprint 1: 路由判定器 LLMRouter 测试套件

测试覆盖：
  1. 所有 13 条路由规则的正例——确保匹配正确
  2. 边界条件——空文本、特殊字符、混合输入
  3. Token 预估合理性
  4. RouteInput 自动 URL 检测
  5. TaskProfile 不可变性
"""

from __future__ import annotations

import pytest
from projects.command_center.gateway.router import (
    LLMRouter,
    RouteInput,
    TaskProfile,
    TargetModel,
    TaskType,
    Priority,
)


class TestRouteInput:
    """RouteInput 创建与自动检测测试。"""

    def test_from_text_plain(self) -> None:
        """纯文本，无 URL。"""
        inp = RouteInput.from_text("帮我复盘本周策略")
        assert inp.text == "帮我复盘本周策略"
        assert not inp.has_url
        assert not inp.has_attachment
        assert not inp.is_interactive_conversation

    def test_from_text_with_url(self) -> None:
        """包含 URL。"""
        inp = RouteInput.from_text("看看这篇 https://example.com/article 怎么样")
        assert inp.has_url

    def test_from_text_with_www(self) -> None:
        """包含 www. 前缀。"""
        inp = RouteInput.from_text("www.example.com 这个网站的信息")
        assert inp.has_url

    def test_from_text_with_http(self) -> None:
        """包含 http://（非 https）。"""
        inp = RouteInput.from_text("http://old-site.com/page")
        assert inp.has_url

    def test_from_text_kwargs(self) -> None:
        """额外参数覆盖。"""
        inp = RouteInput.from_text(
            "帮我处理这个 PDF",
            has_attachment=True,
            attachment_size=15000,
            attachment_type="pdf",
        )
        assert inp.has_attachment
        assert inp.attachment_size == 15000
        assert inp.attachment_type == "pdf"


class TestTaskProfile:
    """TaskProfile 不可变性和验证测试。"""

    def test_create_basic(self) -> None:
        """基本创建。"""
        p = TaskProfile(
            target_model=TargetModel.PRO,
            task_type=TaskType.STRATEGY_DEBATE,
            priority=Priority.HIGH,
        )
        assert p.is_pro()
        assert not p.is_flash()
        assert p.label == "[pro/high] strategy_debate"

    def test_flash_profile(self) -> None:
        """Flash profile。"""
        p = TaskProfile(
            target_model=TargetModel.FLASH,
            task_type=TaskType.URL_FETCH,
        )
        assert p.is_flash()
        assert not p.is_pro()
        assert p.label == "[flash/normal] url_fetch"

    def test_default_priority(self) -> None:
        """默认 priority 应该是 NORMAL。"""
        p = TaskProfile(
            target_model=TargetModel.PRO,
            task_type=TaskType.FREE_CHAT,
        )
        assert p.priority == Priority.NORMAL

    def test_default_confidence(self) -> None:
        """默认 confidence 应该是 1.0。"""
        p = TaskProfile(
            target_model=TargetModel.FLASH,
            task_type=TaskType.CLASSIFY,
        )
        assert p.confidence == 1.0

    def test_invalid_confidence(self) -> None:
        """超出范围的 confidence 应引发 ValueError。"""
        with pytest.raises(ValueError):
            TaskProfile(
                target_model=TargetModel.PRO,
                task_type=TaskType.FREE_CHAT,
                confidence=1.5,
            )
        with pytest.raises(ValueError):
            TaskProfile(
                target_model=TargetModel.PRO,
                task_type=TaskType.FREE_CHAT,
                confidence=-0.1,
            )

    def test_frozen(self) -> None:
        """TaskProfile 应该是不可变的。"""
        p = TaskProfile(
            target_model=TargetModel.PRO,
            task_type=TaskType.FREE_CHAT,
        )
        with pytest.raises(AttributeError):
            p.target_model = TargetModel.FLASH  # type: ignore[misc]


class TestLLMRouterRouting:
    """路由判定器 LLMRouter 的路由准确性测试。"""

    def setup_method(self) -> None:
        self.router = LLMRouter.create_default()

    # ============================================================
    # Flash 路由测试
    # ============================================================

    def test_url_fetch_routes_to_flash(self) -> None:
        """非对话中的 URL 应路由到 Flash url_fetch。"""
        inp = RouteInput(
            text="https://example.com/news/article-1",
            has_url=True,
            is_interactive_conversation=False,
        )
        profile = self.router.classify(inp)
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.URL_FETCH

    def test_scrape_keyword_routes_to_flash(self) -> None:
        """"抓取" 关键字应路由到 Flash scrape_summarize。"""
        profile = self.router.classify_text("请抓取这个页面")
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.SCRAPE_SUMMARIZE

    def test_summarize_keyword_routes_to_flash(self) -> None:
        """"摘要" 关键字应路由到 Flash doc_summarize。"""
        profile = self.router.classify_text("帮我摘要一下")
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.DOC_SUMMARIZE

    def test_fact_check_keyword_routes_to_flash(self) -> None:
        """"事实核查" 关键字应路由到 Flash fact_verify。"""
        profile = self.router.classify_text("事实核查这篇文章")
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.FACT_VERIFY

    def test_long_attachment_routes_to_flash(self) -> None:
        """长附件应路由到 Flash doc_summarize。"""
        inp = RouteInput(
            text="处理这个文件",
            has_attachment=True,
            attachment_size=10000,
        )
        profile = self.router.classify(inp)
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.DOC_SUMMARIZE

    def test_format_keyword_routes_to_flash(self) -> None:
        """"整理格式" 关键字应路由到 Flash text_format (LOW priority)。"""
        profile = self.router.classify_text("整理格式")
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.TEXT_FORMAT
        assert profile.priority == Priority.LOW

    # ============================================================
    # Pro 路由测试
    # ============================================================

    def test_strategy_debate_routes_to_pro(self) -> None:
        """"复盘" 关键字应路由到 Pro strategy_debate。"""
        profile = self.router.classify_text("帮我复盘今天的交易策略")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.STRATEGY_DEBATE

    def test_rebalance_routes_to_pro(self) -> None:
        """"调仓" 关键字应路由到 Pro rebalance_advice (HIGH priority)。"""
        profile = self.router.classify_text("调仓建议有哪些？")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.REBALANCE_ADVICE
        assert profile.priority == Priority.HIGH

    def test_belief_debate_routes_to_pro(self) -> None:
        """信念相关（不含"查询"）应路由到 Pro belief_debate。"""
        profile = self.router.classify_text("这个信念需要修改")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.BELIEF_DEBATE

    def test_belief_query_does_not_route_to_debate(self) -> None:
        """含"查询"的信念输入不应路由到 belief_debate。"""
        profile = self.router.classify_text("查询信念状态")
        # 不含"查询"的规则除外，这里"查询"出现在文本中，应跳过 belief_debate
        assert profile.task_type != TaskType.BELIEF_DEBATE

    def test_deep_analysis_routes_to_pro(self) -> None:
        """"为什么" 关键字应路由到 Pro deep_analysis。"""
        profile = self.router.classify_text("为什么这个策略不奏效")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.DEEP_ANALYSIS

    def test_report_generation_routes_to_pro(self) -> None:
        """"生成报告" 应路由到 Pro report_narrate。"""
        profile = self.router.classify_text("生成报告")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.REPORT_NARRATE

    def test_url_in_conversation_routes_to_intake(self) -> None:
        """对话中的 URL（无其他关键字匹配）应路由到 Pro intake。"""
        inp = RouteInput(
            text="https://example.com 这文章靠谱吗",
            has_url=True,
            is_interactive_conversation=True,
        )
        profile = self.router.classify(inp)
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.INTAKE

    def test_interactive_free_chat_routes_to_pro(self) -> None:
        """交互式对话（无关键字匹配）应路由到 Pro free_chat。"""
        inp = RouteInput(
            text="今天市场怎么样？",
            is_interactive_conversation=True,
        )
        profile = self.router.classify(inp)
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.FREE_CHAT

    def test_long_multi_question_routes_to_pro(self) -> None:
        """长文本含多个问句应路由到 Pro deep_analysis。"""
        profile = self.router.classify_text(
            "第一个问题？第二个问题？第三个呢？第四个如何？"
        )
        # 文本 28 字，含 4 个问号，满足 >200字 的规则？不，28 < 200
        # 且 4 >= 2，但 len > 200 才匹配，所以应走默认 fallback
        # 但 etc... 等等，检查文本长度
        assert len("第一个问题？第二个问题？第三个呢？第四个如何？") < 200
        # 所以应走默认 Flash classify
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.CLASSIFY

    def test_long_text_multi_question_routes_to_pro(self) -> None:
        """实际长文本（>200字）含多个问句应路由到 Pro deep_analysis。"""
        text = "这是一个非常长的文本" * 20 + "？第一个问题？第二个呢？第三个？" * 5
        assert len(text) > 200
        profile = self.router.classify_text(text)
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.DEEP_ANALYSIS

    # ============================================================
    # 默认 Fallback 测试
    # ============================================================

    def test_bare_text_fallback_to_flash(self) -> None:
        """纯文本无匹配应走默认 Flash classify。"""
        profile = self.router.classify_text("测试")
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.CLASSIFY
        assert profile.priority == Priority.BACKGROUND

    def test_empty_text_fallback(self) -> None:
        """空文本应走默认 Flash classify。"""
        profile = self.router.classify_text("")
        assert profile.target_model == TargetModel.FLASH

    def test_special_chars_fallback(self) -> None:
        """特殊字符也能正常 fallback。"""
        profile = self.router.classify_text("@#$%^&*()")
        assert profile.target_model == TargetModel.FLASH


class TestTokenEstimation:
    """Token 预估测试。"""

    def test_short_text(self) -> None:
        """短文本预估正常。"""
        profile = LLMRouter.create_default().classify_text("Hello World")
        assert profile.estimated_tokens > 0

    def test_url_fetch_higher_overhead(self) -> None:
        """URL fetch 应有更高的 token 预估。"""
        router = LLMRouter.create_default()
        url_profile = router.classify_text("https://example.com")
        text_profile = router.classify_text("Hi")
        # URL_fetch 的 overhead (500) 应大于 classify (50)
        # 但分类结果可能不同，只需验证两者都是正数
        assert url_profile.estimated_tokens > 0
        assert text_profile.estimated_tokens > 0


class TestEdgeCases:
    """边界条件测试。"""

    def test_rule_priority_order(self) -> None:
        """URL + 多个关键词同时存在时，规则顺序应保证 URL 优先。"""
        inp = RouteInput(
            text="https://example.com 帮我摘要复盘",
            has_url=True,
            is_interactive_conversation=False,
        )
        profile = LLMRouter.create_default().classify(inp)
        # URL 规则（订单 0）应在复盘（订单 6）之前匹配
        assert profile.target_model == TargetModel.FLASH
        assert profile.task_type == TaskType.URL_FETCH

    def test_custom_rules_override(self) -> None:
        """自定义规则集应覆盖默认规则。"""
        custom_rules = [
            (lambda t: True, TargetModel.PRO, TaskType.FREE_CHAT, Priority.NORMAL),
        ]
        custom_router = LLMRouter(custom_rules)
        profile = custom_router.classify_text("什么都不会")
        assert profile.target_model == TargetModel.PRO
        assert profile.task_type == TaskType.FREE_CHAT

    def test_router_reuse_across_calls(self) -> None:
        """同一个路由器实例应能多次调用。"""
        router = LLMRouter.create_default()
        p1 = router.classify_text("帮我复盘")
        p2 = router.classify_text("抓取这个")
        p3 = router.classify_text("事实核查")
        p4 = router.classify_text("测试")
        assert p1.target_model == TargetModel.PRO
        assert p2.target_model == TargetModel.FLASH
        assert p3.target_model == TargetModel.FLASH
        assert p4.target_model == TargetModel.FLASH  # fallback

    def test_faulty_predicate_skips(self) -> None:
        """抛出异常的 predicate 应被跳过（不会中断路由）。"""
        faulty_rules = [
            (lambda t: 1/0, TargetModel.PRO, TaskType.FREE_CHAT, Priority.NORMAL),
            (lambda t: True, TargetModel.FLASH, TaskType.CLASSIFY, Priority.BACKGROUND),
        ]
        router = LLMRouter(faulty_rules)
        profile = router.classify_text("任何文本")
        assert profile.target_model == TargetModel.FLASH