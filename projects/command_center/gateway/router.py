"""
router.py — Sprint 1: 双模型路由判定器 (LLMRouter)

任务类型分类器 + 路由规则引擎。
核心设计：轻量关键词匹配（零LLM调用），模糊判定用 Flash 兜底分类。

输出 TaskProfile 结构体，供 TaskQueue 决定将任务路由到 Pro 还是 Flash。

SPARC:
  Specification: V2.0 蓝图 §三-2 Routing Rules Matrix
  Pseudocode: rules list of (predicate, target, task_type) → first match wins
  Architecture: 纯函数，无 I/O，可单测
  Refinement: 模糊命中 → target_model="flash"，精度靠 Flash 保底
  Completion: Sprint 1 test_router.py 跑通
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Enums
# ============================================================

class TargetModel(str, enum.Enum):
    """路由目标模型"""
    PRO = "pro"        # DeepSeek V4 Pro — 高智能，低成本敏感
    FLASH = "flash"    # DeepSeek Flash — 高吞吐，低延迟


class TaskType(str, enum.Enum):
    """任务的业务类型标签"""
    # --- Flash 类型 ---
    URL_FETCH = "url_fetch"               # URL 抓取 + 结构化提取
    DOC_SUMMARIZE = "doc_summarize"       # 长文档速读摘要
    FACT_VERIFY = "fact_verify"           # 事实核查
    SCRAPE_SUMMARIZE = "scrape_summarize" # 自定义抓取+摘要
    CODE_GEN = "code_gen"                 # 代码生成（低复杂度）
    TEXT_FORMAT = "text_format"           # 文本格式化
    CLASSIFY = "classify"                 # 模糊路由的保底分类

    # --- Pro 类型 ---
    STRATEGY_DEBATE = "strategy_debate"   # 策略深度复盘
    REBALANCE_ADVICE = "rebalance_advice" # 调仓逻辑辩论
    BELIEF_DEBATE = "belief_debate"       # 信念更新研判
    FREE_CHAT = "free_chat"               # 自由对话
    REPORT_NARRATE = "report_narrate"     # 报告叙事生成
    DEEP_ANALYSIS = "deep_analysis"       # 复杂推理链

    # --- 特殊 ---
    INTAKE = "intake"                     # 情报摄入全管道（特殊路由，绕过Gateway直接到IntakePipeline）


class Priority(str, enum.Enum):
    """任务优先级"""
    HIGH = "high"           # 用户等待中，应尽快处理
    NORMAL = "normal"       # 后台任务，按序处理
    LOW = "low"             # 低优先级，可延迟处理
    BACKGROUND = "background"  # 后台预热任务


# ============================================================
# TaskProfile — 路由输出
# ============================================================

@dataclass(frozen=True)
class TaskProfile:
    """路由判定输出。由 LLMRouter.classify() 返回。

    Attributes:
        target_model: 路由目标模型
        task_type: 业务类型标签
        priority: 优先级
        estimated_tokens: Token 成本预估
        confidence: 路由置信度 [0, 1]，用于日志和调试
        raw_text: 原始输入文本摘要（日志用）
    """
    target_model: TargetModel
    task_type: TaskType
    priority: Priority = Priority.NORMAL
    estimated_tokens: int = 0
    confidence: float = 1.0
    raw_text: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0, 1]; got {self.confidence}"
            )

    def is_pro(self) -> bool:
        return self.target_model == TargetModel.PRO

    def is_flash(self) -> bool:
        return self.target_model == TargetModel.FLASH

    @property
    def label(self) -> str:
        """人类可读的任务标签"""
        return f"[{self.target_model.value}/{self.priority.value}] {self.task_type.value}"


# ============================================================
# Input 类型 (路由判定器的输入)
# ============================================================

@dataclass(frozen=True)
class RouteInput:
    """路由判定器的输入封装。

    Attributes:
        text: 用户输入文本（消息/URL/命令）
        has_url: 输入中是否包含 URL
        has_attachment: 是否附带文件
        attachment_size: 文件大小（字节），0 表示无附件
        attachment_type: 文件类型扩展名（如 'pdf', 'png'）
        is_interactive_conversation: 是否在连续对话中
    """
    text: str = ""
    has_url: bool = False
    has_attachment: bool = False
    attachment_size: int = 0
    attachment_type: str = ""
    is_interactive_conversation: bool = False

    @classmethod
    def from_text(cls, text: str, **kwargs) -> "RouteInput":
        """从纯文本创建，自动检测 URL 和附件。

        Args:
            text: 用户输入文本
            **kwargs: 覆盖 RouteInput 的其他字段
        """
        has_url = (
            "http://" in text or "https://" in text or "www." in text
        )
        return cls(
            text=text,
            has_url=has_url,
            **kwargs,
        )


# ============================================================
# 路由规则定义
# ============================================================

# 每条规则: ( predicate(RouteInput) → bool, target_model, task_type, priority )
# 顺序优先 — 第一个匹配的规则生效

ROUTING_RULES: List[tuple] = [
    # ─────────────────────────────────────────────────────
    # Flash 路由 — 机械/重复/高吞吐
    # ─────────────────────────────────────────────────────

    # URL 抓取（交互式对话中的链接按情报摄入处理）
    (lambda t: t.has_url and not t.is_interactive_conversation,
     TargetModel.FLASH, TaskType.URL_FETCH, Priority.HIGH),

    # 明确请求抓取/摘要
    (lambda t: any(kw in t.text for kw in ("抓取", "fetch", "爬取", "提取", "scrape")),
     TargetModel.FLASH, TaskType.SCRAPE_SUMMARIZE, Priority.NORMAL),

    # 长附件 → Flash 摘要
    (lambda t: t.has_attachment and t.attachment_size > 5000,
     TargetModel.FLASH, TaskType.DOC_SUMMARIZE, Priority.NORMAL),

    # 请求摘要/总结/提炼
    (lambda t: any(kw in t.text for kw in ("摘要", "总结", "提炼", "概括", "summarize")),
     TargetModel.FLASH, TaskType.DOC_SUMMARIZE, Priority.NORMAL),

    # 事实核查请求
    (lambda t: any(kw in t.text for kw in ("事实核查", "验证", "verify", "fact check", "真伪")),
     TargetModel.FLASH, TaskType.FACT_VERIFY, Priority.NORMAL),

    # 格式化请求
    (lambda t: any(kw in t.text for kw in ("格式化", "整理格式", "转成表格")),
     TargetModel.FLASH, TaskType.TEXT_FORMAT, Priority.LOW),

    # ─────────────────────────────────────────────────────
    # Pro 路由 — 策略/研判/深度
    # ─────────────────────────────────────────────────────

    # 策略复盘请求
    (lambda t: any(kw in t.text for kw in ("复盘", "回顾", "review", "retrospect")),
     TargetModel.PRO, TaskType.STRATEGY_DEBATE, Priority.NORMAL),

    # 调仓建议请求
    (lambda t: any(kw in t.text for kw in ("调仓", "重新配置", "rebalance", "优化持仓")),
     TargetModel.PRO, TaskType.REBALANCE_ADVICE, Priority.HIGH),

    # 信念系统相关（非简单查询）
    (lambda t: any(kw in t.text for kw in (
        "信念", "修改信念", "更新信念", "我认为", "我的看法", "这会影响"
    )) and "查询" not in t.text,
     TargetModel.PRO, TaskType.BELIEF_DEBATE, Priority.HIGH),

    # 深度分析请求
    (lambda t: any(kw in t.text for kw in ("为什么", "原因", "根本", "root cause", "深度分析")),
     TargetModel.PRO, TaskType.DEEP_ANALYSIS, Priority.NORMAL),

    # 报告生成请求
    (lambda t: any(kw in t.text for kw in ("生成报告", "报告", "report", "周报", "日报")),
     TargetModel.PRO, TaskType.REPORT_NARRATE, Priority.NORMAL),

    # 情报摄入请求（URL + 意图讨论）
    (lambda t: t.has_url and t.is_interactive_conversation,
     TargetModel.PRO, TaskType.INTAKE, Priority.HIGH),

    # ─────────────────────────────────────────────────────
    # 默认 — 复杂/自由/交互 → Pro
    # ─────────────────────────────────────────────────────

    # 交互式对话 → Pro
    (lambda t: t.is_interactive_conversation,
     TargetModel.PRO, TaskType.FREE_CHAT, Priority.NORMAL),

    # 长文本（>200字）含多个问句 → Pro
    (lambda t: len(t.text) > 200 and t.text.count("?") + t.text.count("？") >= 2,
     TargetModel.PRO, TaskType.DEEP_ANALYSIS, Priority.NORMAL),

    # 默认 Fallback — Flash 做一次廉价分类确认
    (lambda t: True, TargetModel.FLASH, TaskType.CLASSIFY, Priority.BACKGROUND),
]


# ============================================================
# LLMRouter — 路由判定器
# ============================================================

class LLMRouter:
    """双模型路由判定器。

    纯函数式设计：classify() 接收 RouteInput，输出 TaskProfile。
    无网络 I/O，无外部状态，线程安全。

    用法:
        router = LLMRouter()
        profile = router.classify(RouteInput.from_text("帮我复盘本周策略"))
        # profile.target_model == TargetModel.PRO
        # profile.task_type == TaskType.STRATEGY_DEBATE
    """

    def __init__(self, rules: Optional[List[tuple]] = None) -> None:
        """初始化路由器。

        Args:
            rules: 可选的自定义路由规则列表。默认为 ROUTING_RULES。
        """
        self._rules = rules or ROUTING_RULES
        logger.debug("LLMRouter initialized with %d rules", len(self._rules))

    def classify(self, input_data: RouteInput) -> TaskProfile:
        """对输入进行路由判定。

        Args:
            input_data: 封装的输入数据（文本、URL标记、附件标记、对话状态）

        Returns:
            TaskProfile: 路由判定输出（target_model, task_type, priority, ...）

        算法:
            1. 按顺序遍历 ROUTING_RULES
            2. 返回第一个 predicate(input) == True 对应的 profile
            3. 默认 Fallback: Flash classify (最后一条规则兜底)
        """
        text_summary = input_data.text[:50] if len(input_data.text) > 50 else input_data.text

        for idx, (predicate, target_model, task_type, priority) in enumerate(self._rules):
            try:
                if predicate(input_data):
                    # 计算粗略的 Token 预估
                    estimated_tokens = self._estimate_tokens(
                        input_data.text, task_type
                    )

                    profile = TaskProfile(
                        target_model=target_model,
                        task_type=task_type,
                        priority=priority,
                        estimated_tokens=estimated_tokens,
                        confidence=1.0 if idx < len(self._rules) - 1 else 0.5,
                        raw_text=text_summary,
                    )

                    logger.debug(
                        "Route match [rule=%d]: %s → %s",
                        idx, text_summary, profile.label,
                    )
                    return profile
            except Exception as e:
                logger.warning(
                    "Route rule %d failed for input '%s': %s",
                    idx, text_summary, e,
                )
                continue

        # 不应到达此处（最后一条规则始终匹配），但保险
        return TaskProfile(
            target_model=TargetModel.FLASH,
            task_type=TaskType.CLASSIFY,
            priority=Priority.BACKGROUND,
            estimated_tokens=self._estimate_tokens(input_data.text, TaskType.CLASSIFY),
            confidence=0.3,
            raw_text=text_summary,
        )

    def classify_text(self, text: str, **kwargs) -> TaskProfile:
        """便利方法：从纯文本直接路由。

        Args:
            text: 用户输入文本
            **kwargs: 传递给 RouteInput.from_text() 的额外参数

        Returns:
            TaskProfile
        """
        return self.classify(RouteInput.from_text(text, **kwargs))

    # ============================================================
    # Private Helpers
    # ============================================================

    @staticmethod
    def _estimate_tokens(text: str, task_type: TaskType) -> int:
        """粗略 Token 计数（每 4 字符 ≈ 1 token）。

        Args:
            text: 输入文本
            task_type: 任务类型（用于附加上下文 token 预估）

        Returns:
            预估的输入 token 数量
        """
        base_tokens = len(text) // 4

        # 不同任务类型的上下文开销不同
        overheads = {
            TaskType.URL_FETCH: 500,        # 抓取结果可能很大
            TaskType.DOC_SUMMARIZE: 500,    # 文档内容
            TaskType.FACT_VERIFY: 300,
            TaskType.STRATEGY_DEBATE: 400,  # 报告中信念上下文
            TaskType.REBALANCE_ADVICE: 300, # 仓位数据
            TaskType.BELIEF_DEBATE: 200,
            TaskType.FREE_CHAT: 100,
            TaskType.DEEP_ANALYSIS: 300,
            TaskType.REPORT_NARRATE: 500,   # 全量数据
            TaskType.INTAKE: 1000,          # 情报摄入全上下文
            TaskType.CLASSIFY: 50,
            TaskType.SCRAPE_SUMMARIZE: 300,
            TaskType.TEXT_FORMAT: 100,
            TaskType.CODE_GEN: 200,
        }

        overhead = overheads.get(task_type, 150)
        return base_tokens + overhead

    @staticmethod
    def create_default() -> "LLMRouter":
        """工厂方法：使用默认规则创建路由器。"""
        return LLMRouter(ROUTING_RULES)