"""L1 Interactive Narrative Analysis — Socratic multi-turn protocol (Phase C H2).

Replaces single-shot analyze_layer1() with a multi-turn dialogue:
  1. Main AI receives signals + news → deep internal analysis → archive
  2. Presents concise conclusions to user (ABC format: conclusion + logic + evidence + gaps)
  3. User challenges, asks questions, provides ideas
  4. Main AI defends with data, evaluates user input independently (non-sycophantic)
  5. Directed data mining via Flash searches (user-directed or AI-suggested)
  6. AI proposes "enough info" → user confirms → proceed to L2/L3
  7. Or both agree to observe → skip L2/L3 (no missed_path)
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.gateway.async_client import chat_pro, chat_flash
from marketmind.pipeline.layer1_narrative import Layer1Result, FlashSignal, _format_signals, _parse_layer1_response
from marketmind.shadows.shadow_agent import defang_text

logger = logging.getLogger("marketmind.pipeline.layer1_interactive")


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class InteractiveState:
    """Mutable state tracked across L1 dialogue turns."""
    turn: int = 0
    deep_analysis: str = ""              # full archived analysis
    concise_summary: str = ""            # last concise report to user
    evidence_chain: list[str] = field(default_factory=list)
    info_gaps: list[str] = field(default_factory=list)
    confirmed_direction: str = ""        # investment direction (if confirmed)
    user_ideas: list[str] = field(default_factory=list)
    ai_evaluations: list[str] = field(default_factory=list)
    data_mining_results: list[str] = field(default_factory=list)
    forecast_predictions: list[dict] = field(default_factory=list)  # directional scenarios: dominant, alternative, tail-risk
    stage: str = "initial"              # initial | discussing | mining | confirming | done
    should_observe: bool = False         # both agree to skip trading today


# ── System prompts ───────────────────────────────────────────────────────────

L1_DEEP_ANALYSIS_PROMPT = """You are a senior macro investment analyst. You receive preprocessed market signals and news.

**CRITICAL: ALL output MUST be in Chinese (简体中文).** The user is a Chinese-speaking investor. English output is unacceptable. Both the deep analysis and the concise summary must be in Chinese.

Your first task is to produce a DEEP internal analysis (for archival). Do NOT request additional data at this stage — work only with what you are given.

## Deep Analysis Requirements

1. **Narrative Structure**: What is the dominant market narrative? What are the competing narratives?
2. **Causal Chain**: For each key event, trace: cause → mechanism → market impact → investment implication
3. **Directional Scenarios**: Based on evidence from the provided NEWS and SIGNALS, describe:
   - Dominant scenario: What the preponderance of evidence suggests (NOT a probability — just the best-supported narrative)
   - Alternative scenario: What could happen if the dominant narrative's key assumption is wrong
   - Tail risk: Low-likelihood but high-impact event that would invalidate both scenarios
   - For EACH scenario, list: (a) specific trigger conditions from today's news that would confirm it, (b) investment implications
   - CRITICAL: Do NOT assign numeric probabilities. You do not have a statistical model. Describe evidence strength qualitatively (strong/moderate/weak signal).
4. **Information Gaps**: What important data are you missing? What would you want to verify?
5. **Confidence Calibration**: For each major claim, rate confidence 0.0-1.0

Output this deep analysis in structured text (it will be archived, not shown to the user directly).

After the deep analysis, output a CONCISE SUMMARY for the user. **Must be in Chinese (简体中文).**

## 简报格式

**投资方向**：[1-2句话，投资方向建议]

**关键理由**（最多3条）：
1. [理由 + 支撑数据]
2. [理由 + 支撑数据]
3. [理由 + 支撑数据]

**信息缺口**（需要核实的事项）：
- [缺口1]
- [缺口2]

**风险提示**：[1句话，该观点面临的最大风险]

**提问**：[1个问题，询问用户想往哪个方向深入探讨]

重要：简报需在60秒内读完。先说结论，再讲过程。
在深度分析和简报之间，必须用 `=== CONCISE ===` 作为分隔符（独占一行）。"""


L1_DISCUSSION_PROMPT = """You are a senior macro investment analyst in a discussion with a Chinese-speaking investor.

## Rules of Engagement

1. **Language**: Always respond in Chinese (简体中文). The investor communicates in Chinese — you must reply in Chinese.
2. **Evidence-first**: Every claim must cite specific data or reasoning. Never respond with empty rhetoric.
3. **Independent judgment**: The investor may offer ideas or opinions. Evaluate them honestly — do NOT blindly agree. If the investor's idea has merit, acknowledge it with evidence. If it has flaws, explain why respectfully with data.
4. **No un-evidenced reversals**: You may change your position only when new data or analysis justifies it. Cite what changed.
5. **Contradiction handling**: If you find contradictory evidence, present both sides with their sources and explain what additional data would resolve the contradiction.
6. **Confidence labeling**: Label each conclusion with [高置信度] / [中等置信度] / [低置信度] when responding in Chinese, or [High/Medium/Low Confidence] in English.

## Response Format

When the investor challenges or asks a question:
- Direct answer first (1-2 sentences)
- Supporting evidence (data, reasoning, sources)
- If applicable: what additional data would strengthen or weaken this view

When you need to mine additional data:
- State what specific data you want to look for
- Explain why it matters
- Ask the investor's permission before executing Flash searches

When you believe information is sufficient:
- **Proactively suggest proceeding**: State "我认为信息已充足，建议进入 L2 标的筛选阶段" (or English equivalent)
- Summarize the confirmed investment direction in one line
- List remaining open questions (if any)
- End with: "回复'好'或'可以'进入 L2，也可继续讨论。"
- IMPORTANT: Be proactive — don't wait for the investor to ask to proceed. If you've answered 2+ rounds of questions and the direction is clear, suggest moving forward.

If the investor suggests observing (not trading today):
- Evaluate the suggestion honestly
- If you agree conditions are unclear: "同意——当前市场条件不够清晰。现金也是一种仓位。"
- If you disagree: explain what opportunities you see despite the uncertainty"""


L1_DATA_MINING_PROMPT = """You are collecting specific data to verify or refute a hypothesis.

The investor has asked you to investigate: {direction}

Use the provided Flash search results to:
1. Cross-validate the hypothesis against the new data
2. Identify any contradictions or surprises in the findings
3. Update your confidence in the original direction
4. Note any new information gaps revealed by this search

Be concise. Focus on what CHANGED based on the new data."""


# ── Mock responses for testing (no API calls) ───────────────────────────────

MOCK_DEEP_ANALYSIS = """## Deep Analysis

### 1. Dominant Narrative
The dominant market narrative is "Fed patience meets tech earnings momentum." The Fed's steady-rate signal reduces near-term policy uncertainty, while strong tech earnings confirm AI-driven demand is real and accelerating. However, rising oil prices on Middle East concerns introduce a stagflationary risk that competes with the soft-landing narrative.

### 2. Causal Chain
- **Fed holds steady** → reduces rate volatility → supports growth equity valuations → favors tech/consumer discretionary
- **Oil price surge** → increases input costs → compresses margins in transport/manufacturing → potential inflation resurgence → could delay future rate cuts
- **Tech earnings beat** → confirms AI CapEx cycle is durable → semiconductor demand sustained → positive for SOXX/SMH
- **ECB rate cut hint** → weakens EUR → strengthens USD → creates headwind for commodities and EM
- **China export beat** → signals global demand resilience → positive for industrial metals and shipping

### 3. Directional Scenarios (evidence-based, no numeric probabilities)
- **Dominant scenario (strongest signal support)**: Tech earnings + Fed patience → risk-on for growth equities. Evidence: CNBC Fed signal (strong), Yahoo Tech earnings (strong).
- **Alternative scenario (if key assumption wrong)**: Oil supply disruption persists → stagflationary pressure → growth/value rotation. Evidence: Bloomberg oil surge (moderate), SCMP China export (moderate).
- **Tail risk**: Middle East escalation widens beyond current scope → broad risk-off. Evidence: BBC geopolitical fragment (weak signal).
- Trigger conditions and evidence strength listed per scenario. No numeric probabilities assigned.

### 4. Information Gaps
- Missing: Oil inventory data (API/EIA this week)
- Missing: Fed minutes detail on inflation tolerance
- Missing: Tech earnings guidance (not just results)
- Missing: China credit impulse data for March

### 5. Confidence Calibration
- Fed narrative: 0.75 confidence
- Oil impact: 0.60 confidence (dependent on geopolitical developments)
- Tech earnings durability: 0.70 confidence
- China export signal: 0.55 confidence (one-month data point)

=== CONCISE ===

**投资方向**：偏多科技和消贵，但对油价上行保持警惕。

**关键理由**（最多3条）：
1. 美联储按兵不动 + 科技财报超预期 → AI 资本支出周期确定性增强 [高置信度]
2. 中东供应担忧推高油价 → 如果持续突破$90将压缩下游利润 [中等置信度]
3. 中国出口超预期 + ECB 降息暗示 → 全球需求韧性好于市场定价 [中等置信度]

**信息缺口**（需要核实的事项）：
- 本周 API/EIA 原油库存数据
- 美联储会议纪要中的通胀容忍度表述
- 科技公司全年 Capex 指引（不仅是上季度结果）

**风险提示**：油价若突破$95将逆转当前的软着陆叙事，触发成长股轮动卖出。

**提问**：你认为油价上涨是短期波动还是结构性趋势？这会直接影响我们今天是否加仓能源板块。"""

MOCK_DISCUSSION_RESPONSE = """[中等置信度] 关于油价问题，当前数据更支持"短期供应冲击"而非结构性趋势。

**支持短期判断的证据**：
1. 中东供应中断历史上持续时间中位数是 45 天（过去 20 年 12 次事件）
2. OPEC+ 仍有 300 万桶/日的闲置产能可以释放
3. 全球 SPR 库存处于 5 年均值附近，有释放空间

**但如果出现以下情况，我会转向结构性判断**：
1. 霍尔木兹海峡通行受阻（概率低但影响极大）
2. OPEC+ 明确不增产（目前没有信号）
3. 美国页岩油产量见顶（EIA 月度数据需跟踪）

**我的建议**：今天不加仓能源。先等本周 EIA 库存数据，如果库存下降超预期且油价站稳$90以上，明天再考虑。

你还有其他担心吗？或者我们可以进入 L2 做标的筛选了？"""

MOCK_MINING_RESPONSE = """[数据挖掘结果]

按你的要求搜索了"中东石油供应中断历史"相关数据：

**历史模式**：
- 过去 20 年中东供应中断 12 次，恢复时间中位数 45 天
- 单次事件 Brent 平均涨幅 12%，但 3 个月内回吐 80% 涨幅
- 只有 2 次演变为结构性牛市（2008、2022）

**当前特殊性**：
- 本次事件涉及的生产设施占全球供应 2%，低于历史均值 4%
- 但红海航运保险费率已上涨 300%，反映市场定价了更高风险

**结论**：历史模式不支持油价持续 >$95，但航运中断可能持续更久。维持"短期冲击"判断。"""

# ── Interactive L1 Pipeline ─────────────────────────────────────────────────

async def run_l1_interactive(
    signals: list[FlashSignal],
    news_items: list,
    user_input_handler=None,  # async callable(str) -> str
    mock: bool = False,       # use canned responses, no API calls
) -> tuple[Layer1Result, bool, dict]:
    """Run L1 as an interactive Socratic dialogue.

    Args:
        signals: Preprocessed Flash signals
        news_items: Raw news articles
        user_input_handler: Async function that presents text to user and returns their response.
                           If None, falls back to a single-shot non-interactive analysis.
        mock: If True, use hardcoded responses instead of calling LLM APIs.

    Returns:
        (Layer1Result, should_observe, session_data)
        session_data = {"user_ideas": [...], "discussion_text": "..."}
    """
    state = InteractiveState()

    # Inject current date — factual only, no meta-commentary that triggers cutoff thinking
    today_str = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    date_context = (
        f"\n\nTODAY IS {today_str}."
        f" The provided NEWS HEADLINES and MARKET SIGNALS are real-time data as of this date."
        f" Your analysis must be grounded in this provided information."
        f" Do NOT reference your training data as a limitation — the news and signals ARE your data."
    )

    # ── Step 1: Deep analysis + concise summary ──────────────────────────
    # Build analysis text from signals if available, otherwise from raw news
    if signals:
        signal_text = _format_signals(signals, news_items)
    elif news_items:
        # Fallback: use raw news headlines when Flash preprocessing produced no signals
        headlines = [f"[{getattr(n, 'source_name', 'news')}] {getattr(n, 'title', '')}"
                     for n in news_items[:30]]
        signal_text = "News headlines (no preprocessed signals available):\n" + "\n".join(f"- {h}" for h in headlines)
    else:
        # No data at all — use mock news to keep interactive test working
        # Generic themes only — avoid hardcoding specific events that go stale
        print(f"\n[L1] 无可用新闻数据（{today_str}），使用测试模拟信号继续。")
        signal_text = f"Mock market signals for interactive testing ({today_str}):\n"
        signal_text += "- [Gateway] Central bank policy decision: no change in benchmark rate\n"
        signal_text += "- [Commodity] Energy markets volatile on geopolitical developments\n"
        signal_text += "- [Tech] Sector earnings broadly in line; AI demand remains a key theme\n"
        signal_text += "- [Macro] Mixed economic data from major economies\n"
        signal_text += "- [Trade] Export data varies by region; currency markets fluctuate\n"

    deep_result = await chat_pro(
        system_prompt=L1_DEEP_ANALYSIS_PROMPT + date_context,
        user_prompt=f"Analyze these market signals for narrative structure:\n\n{signal_text}",
        temperature=0.3,
        max_tokens=8192,
    ) if not mock else {"content": MOCK_DEEP_ANALYSIS}

    raw_content = deep_result.get("content", "")
    # P0: filter out meta-commentary + fabricated numbers
    from marketmind.pipeline.output_filter import strip_meta_commentary
    state.deep_analysis = strip_meta_commentary(raw_content)
    state.stage = "discussing"

    # Extract concise summary for user (second half of the output)
    concise_summary = _extract_concise_summary(state.deep_analysis)
    if _response_looks_truncated(concise_summary) and len(state.deep_analysis) > 500:
        concise_summary += "\n\n[注意：简报可能因长度限制被截断。可在讨论中要求AI补充遗漏部分。]"
    state.concise_summary = concise_summary

    # ── Step 1.5: Attempt to parse structured result for backward compat ──
    l1_result = _try_parse_l1_result(state.deep_analysis)

    # ── Step 2: If interactive, present to user ──────────────────────────
    if user_input_handler is None:
        # Non-interactive mode: return what we have
        l1_result.raw_analysis = state.deep_analysis
        return l1_result, False, {"user_ideas": [], "discussion_text": ""}

    # Present concise summary to user
    print(f"\n{'='*60}")
    _safe_print(concise_summary)
    print(f"{'='*60}")
    print(f"\n你可以：提问 / 质疑推理 / 建议探索方向 / 回复'好'进入L2 / 回复'observe'观望")
    print(f"  输入 'elite' 查看可用的ELITE领域专家影子")

    # ── Step 3: Discussion loop ──────────────────────────────────────────
    discussion_history: list[dict] = [
        {"role": "assistant", "content": f"Concise Summary:\n{concise_summary}"}
    ]

    while state.stage != "done":
        state.turn += 1

        # Get user input — handler manages its own prompt
        user_response = await user_input_handler("> ")
        if not user_response or not user_response.strip():
            continue

        user_text = user_response.strip()

        # Handle proceed to L2 — only trigger on short confirmations, not casual mentions
        # Exact short confirmations (<=5 chars in Chinese, single words in English)
        short_confirm = user_text.strip().lower()
        is_short_confirm = short_confirm in (
            "好", "好的", "ok", "okay", "yes", "行", "可以", "同意", "继续",
            "开始", "没问题", "go", "sure", "yep", "yeah",
        )
        # Longer confirmations that explicitly reference L2 or proceeding
        is_explicit_proceed = short_confirm in (
            "proceed", "go ahead", "进入l2", "进入L2", "进入 L2", "下一步",
            "就这么办", "lets go", "let's go", "done", "enough",
        ) or short_confirm.startswith("进入l2") or short_confirm.startswith("进入 l2")
        # DO NOT match "好，那我们再看看..." — those are conversation, not confirmation

        if is_short_confirm or is_explicit_proceed:
            state.stage = "done"
            state.confirmed_direction = concise_summary[:200]
            print("\n[L1] 进入 L2 标的筛选...\n")
            break

        if short_confirm in ("observe", "等等看", "等等", "观望", "跳过", "不买",
                              "skip", "pass", "wait", "hold", "先不看"):
            state.should_observe = True
            state.stage = "done"
            print(
                "\n[L1] 同意——今日观望。现金也是一种仓位。\n"
            )
            break

        # Handle ELITE shadow query
        if user_text.lower() in ("elite", "影子", "elite影子", "elite shadow"):
            _handle_elite_query(state)
            continue

        # Check if user wants data mining
        if _is_data_mining_request(user_text):
            state.stage = "mining"
            search_results = await _execute_data_mining(user_text, state)
            state.data_mining_results.append(search_results)

            # Feed results back to AI for analysis
            mining_prompt = L1_DATA_MINING_PROMPT.format(direction=user_text[:200])
            analysis = await chat_pro(
                system_prompt=mining_prompt + date_context,
                user_prompt=f"Search results:\n{search_results}\n\nOriginal hypothesis: {user_text}\n\nAnalyze:",
                temperature=0.3,
                max_tokens=4096,
            ) if not mock else {"content": MOCK_MINING_RESPONSE}
            ai_response = analysis.get("content", "Analysis unavailable.")
            if _response_looks_truncated(ai_response):
                ai_response += ("\n\n[注意：数据挖掘结果可能因长度限制被截断。"
                                "可输入'继续说'让AI补充遗漏的方向。]")

            _safe_print(f"\n[L1 Data Mining]\n{ai_response}")
            discussion_history.append({"role": "assistant", "content": ai_response})
            state.stage = "discussing"
            continue

        # Normal discussion turn
        discussion_history.append({"role": "user", "content": user_text})
        state.user_ideas.append(user_text)

        # Build discussion prompt
        history_text = _format_history(discussion_history[-20:])  # last 10 exchanges (was 3 — too little context)
        discussion_prompt = (
            f"## Discussion Context\n{history_text}\n\n"
            f"## Investor's Latest Point\n{user_text}\n\n"
            f"Respond following the Rules of Engagement. Be direct, evidence-based, "
            f"and label your confidence levels."
        )

        # Show "thinking" indicator
        print("  ...", end="", flush=True)
        try:
            ai_response_result = await chat_pro(
                system_prompt=L1_DISCUSSION_PROMPT + date_context,
                user_prompt=discussion_prompt,
                temperature=0.3,
                max_tokens=4096,
            ) if not mock else {"content": MOCK_DISCUSSION_RESPONSE}
            ai_response = ai_response_result.get("content", "")
            ai_response = strip_meta_commentary(ai_response)
            if not ai_response.strip():
                ai_response = "[AI 返回了空回复，可能是网络波动。请重试你的问题。]"
            elif _response_looks_truncated(ai_response):
                ai_response += ("\n\n[注意：AI回复可能因长度限制被截断。"
                                "可输入'继续说'让AI补充，或输入'好'进入L2。]")
        except Exception as e:
            logger.warning("L1 discussion LLM call failed: %s", e)
            ai_response = f"[系统提示：AI 响应失败，请重试或输入'好'进入 L2]"

        state.ai_evaluations.append(ai_response)
        discussion_history.append({"role": "assistant", "content": ai_response})

        # Show response
        _safe_print(f"\n\n{ai_response}")
        if _ai_suggests_proceeding(ai_response):
            print(f"\n[L1] AI 认为信息已充足。输入 'proceed' 进入 L2，或继续讨论。")


    # ── Step 3.5: Red Team background bias check (H8 PMV) ────────────────
    if state.turn >= 2 and not mock:
        _run_bias_check(state)

    # ── Step 4: Return result ────────────────────────────────────────────
    # Build session data for broadcast to shadows (user ideas + chat, no main AI analysis)
    session_data = {
        "user_ideas": state.user_ideas,
        "discussion_text": _build_discussion_text(discussion_history),
    }

    if state.should_observe:
        result = Layer1Result.empty_default()
        result.raw_analysis = state.deep_analysis
        return result, True, session_data

    # Always attach deep analysis text for L2 consumption
    l1_result.raw_analysis = state.deep_analysis
    return l1_result, False, session_data


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_bias_check(state: InteractiveState) -> None:
    """H8 PMV: Quick bias check on L1 interaction — no LLM call, pattern-based."""
    warnings: list[str] = []

    # 1. Confirmation bias: AI agrees too readily
    agree_markers = ["同意", "支持", "合理", "有道理", "agree", "correct", "valid"]
    if state.ai_evaluations:
        agree_count = sum(
            1 for resp in state.ai_evaluations
            if any(m in resp.lower() for m in agree_markers)
        )
        if agree_count >= len(state.ai_evaluations) * 0.8 and len(state.ai_evaluations) >= 2:
            warnings.append("[偏差预警] AI 同意率过高 — 可能存在阿谀偏差 (sycophancy)")

    # 2. Counterfactual check
    counterfactual_phrases = ["如果", "万一", "反过来", "what if", "相反"]
    if state.user_ideas:
        has_cf = any(
            any(p in idea for p in counterfactual_phrases)
            for idea in state.user_ideas
        )
        if not has_cf and len(state.user_ideas) >= 2:
            warnings.append("[偏差预警] 未探索反向情景 — 建议考虑'如果判断错误会怎样'")

    if warnings:
        print(f"\n[Red Team 后台]")
        for w in warnings:
            print(f"  {w}")


def _handle_elite_query(state: InteractiveState) -> None:
    """H7/P2: Display ELITE shadow availability during L1 discussion.

    ELITE shadows run in background — their results may not be ready yet.
    This shows what's available and lets the user query by domain.
    """
    from marketmind.config.ticker_labels import domain_cn
    print(f"\n[ELITE 影子系统]")
    print(f"  ELITE 影子正在后台并行分析当日新闻。")
    print(f"  可用领域: " + " ".join(
        domain_cn(d) for d in ["energy","tech","crypto","bonds","gold",
        "macro","metals","financials","healthcare","consumer",
        "industrials","emerging","real_estate","volatility","fx","short"]
    ))
    print(f"  输入影子名称或领域关键词来查询 | 或继续讨论")

    # If user typed "elite energy", try to get shadow opinion
    # For the MVP, this triggers data mining in that domain
    domain_map = {
        "energy": "能源/油气", "tech": "科技/AI/半导体", "crypto": "加密货币",
        "bonds": "债券/利率", "gold": "黄金/贵金属", "macro": "宏观/指数",
        "metals": "工业金属/矿业", "financials": "金融/银行",
        "healthcare": "医疗/制药", "consumer": "消费/零售",
        "industrials": "工业/制造", "emerging": "新兴市场",
        "real_estate": "房地产/REIT", "volatility": "波动率/VIX",
        "fx": "外汇", "short": "做空/看跌",
    }


def _build_discussion_text(history: list[dict]) -> str:
    """Build a flattened chat transcript from discussion history (user+AI only, no main AI analysis)."""
    lines = []
    for msg in history:
        role = "用户" if msg["role"] == "user" else "分析师"
        content = msg.get("content", "")[:500]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _response_looks_truncated(text: str) -> bool:
    """Check if text appears to have been cut off mid-sentence."""
    if len(text) < 80:
        return False  # short responses are fine
    sentence_end = {'.', '!', '?', '。', '！', '？', '”', '’', ')', ']', '》'}
    return text.rstrip()[-1] not in sentence_end

def _safe_print(text: str) -> None:
    """Print text safely on Windows GBK consoles (handle emoji in AI output)."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace characters the console encoding can't represent
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="backslashreplace").decode(encoding))

def _extract_concise_summary(deep_analysis: str) -> str:
    """Extract the user-facing concise summary from the deep analysis output."""
    markers = [
        "## Concise Summary",
        "## 简报格式",
        "=== CONCISE ===",
        "简明版",
        "面向用户",
        "——— 以下为面向用户的简明版",
        "**投资方向**",
        "**Direction**",
    ]
    for marker in markers:
        idx = deep_analysis.find(marker)
        if idx != -1:
            return deep_analysis[idx:].strip()
    # Fallback: return last ~1200 chars
    return deep_analysis[-1200:].strip()


def _try_parse_l1_result(text: str) -> Layer1Result:
    """Attempt to parse a structured Layer1Result from analysis text.
    Falls back to text-based extraction when JSON parsing fails (interactive mode).
    """
    try:
        return _parse_layer1_response(text)
    except Exception:
        pass  # not JSON — extract from structured text

    # Text-based extraction for interactive mode (structured text, not JSON)
    import re
    result = Layer1Result.empty_default()

    # Extract event_grade from text patterns like "grade=B" or "等级: B"
    grade_match = re.search(r'(?:event_?grade|等级|grade)\s*[=:：]\s*([A-E])', text, re.IGNORECASE)
    if grade_match:
        result.event_grade = grade_match.group(1).upper()

    # Extract sentiment direction
    if re.search(r'(?:sentiment|情绪|市场情绪).*(?:bullish|看多|乐观|risk.on)', text, re.IGNORECASE):
        result.sentiment_direction = "bullish"
    elif re.search(r'(?:sentiment|情绪|市场情绪).*(?:bearish|看空|悲观|risk.off)', text, re.IGNORECASE):
        result.sentiment_direction = "bearish"

    # Extract matrix quadrant
    quad_match = re.search(r'(?:matrix_?quadrant|象限|quadrant)\s*[=:：]\s*(\w+)', text, re.IGNORECASE)
    if quad_match:
        result.matrix_quadrant = quad_match.group(1).lower()

    # Extract price-in score
    price_match = re.search(r'(?:price.?in|已定价|price.in.score)\s*[=:：]\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if price_match:
        try:
            result.price_in_score = float(price_match.group(1))
        except ValueError:
            pass

    return result


def _is_data_mining_request(user_text: str) -> bool:
    """Detect if user is requesting data mining / Flash search."""
    mining_keywords = [
        "search for", "look up", "find data", "check", "verify",
        "what does the data say", "get data on", "research",
        "查一下", "搜索", "查查", "查", "找一下", "核实",
        "cross reference", "cross-reference",
    ]
    text_lower = user_text.lower()
    return any(kw in text_lower for kw in mining_keywords)


async def _execute_data_mining(direction: str, state: InteractiveState) -> str:
    """Execute knowledge-base data mining (training data only; no live web search)."""
    try:
        result = await chat_flash(
            system_prompt=(
                "You are a data retrieval assistant working from your training knowledge "
                "(cutoff: early 2025). You do NOT have live web search. If you do not know "
                "something or the information may be outdated, clearly state that limitation. "
                "Summarize what you know concisely."
            ),
            user_prompt=f"Find data related to: {direction[:500]}. Summarize key findings concisely. ",
            temperature=0.1,
            max_tokens=1024,
        )
        return result.get("content", "No search results available.")
    except Exception as e:
        logger.warning("Data mining Flash call failed: %s", e)
        return f"Search unavailable: {e}"


def _ai_suggests_proceeding(ai_response: str) -> bool:
    """Check if the AI is suggesting to proceed to L2."""
    proceed_phrases = [
        "enough information to proceed",
        "move to L2",
        "proceed to L2",
        "move to sector",
        "sufficient information",
        "we have enough",
        "shall we proceed",
        "ready for L2",
        # Chinese keywords for bilingual users
        "继续",
        "进入",
        "可以开始",
        "准备好了",
        "信息足够",
        "足够了",
    ]
    response_lower = ai_response.lower()
    return any(p in response_lower for p in proceed_phrases)


def _format_history(history: list[dict]) -> str:
    """Format recent discussion history for the prompt."""
    lines = []
    for msg in history:
        role = "Investor" if msg["role"] == "user" else "Analyst"
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"**{role}**: {content}")
    return "\n\n".join(lines)
