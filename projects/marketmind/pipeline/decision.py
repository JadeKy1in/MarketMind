"""Decision generator: decision card + "no-trade" card synthesis."""
from __future__ import annotations
import json
import logging

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

logger = logging.getLogger("marketmind.pipeline.decision")
from dataclasses import dataclass, field
from typing import Any

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.pipeline.red_team import RedTeamReport
from marketmind.pipeline.resonance import ResonanceResult
from marketmind.shadows.shadow_agent import defang_text

# P3-2b: dynamic prompt assembly (replaces static DECISION_SYSTEM_PROMPT)
_rule_registry = None


@dataclass
class SignalConflict:
    """Detected signal conflict between two analytical dimensions."""
    signal_a: tuple[str, float]   # (source_name, value)
    signal_b: tuple[str, float]   # (source_name, value)
    divergence: float             # absolute difference
    description: str              # Chinese-language conflict description


def _detect_signal_conflicts(hypotheses: list) -> list[SignalConflict]:
    """Detect signal conflicts across analytical dimensions.

    Checks two conflict types:
    1. Causal net_directional_force vs Flow flow_imbalance (divergence > 0.4)
    2. Scenario base confidence vs Fragility score (divergence > 0.4)
    """
    conflicts: list[SignalConflict] = []
    for h in hypotheses:
        if h is None:
            continue

        # Check 1: causal vs flow divergence
        causal = getattr(h, 'causal', None)
        flow = getattr(h, 'flow', None)
        if causal is not None and flow is not None:
            c_force = getattr(causal, 'net_directional_force', 0) or 0
            f_imb = getattr(flow, 'flow_imbalance', 0) or 0
            divergence = abs(c_force - f_imb)
            if divergence > 0.4:
                conflicts.append(SignalConflict(
                    signal_a=("causal_decomposition", c_force),
                    signal_b=("flow_decomposition", f_imb),
                    divergence=divergence,
                    description=f"因果分解与资金流分解信号背离 (divergence={divergence:.2f})，"
                                f"因果分解方向力={c_force:.2f}，资金流失衡={f_imb:.2f}",
                ))

        # Check 2: scenario confidence vs fragility
        scenario = getattr(h, 'scenario_tree', None)
        fragility = getattr(h, 'fragility_score', None)
        if scenario is not None and fragility is not None:
            base = getattr(scenario, 'base_case', None)
            if base is not None:
                sc_conf = getattr(base, 'confidence', 0) or 0
                fg_score = 1.0 - fragility  # invert: high fragility = low confidence
                divergence = abs(sc_conf - fg_score)
                if divergence > 0.4:
                    conflicts.append(SignalConflict(
                        signal_a=("scenario_forecaster", sc_conf),
                        signal_b=("fragility_scanner", fg_score),
                        divergence=divergence,
                        description=f"情景预测置信度与脆弱性评分矛盾 (divergence={divergence:.2f})，"
                                    f"情景预测置信={sc_conf:.2f}，脆弱性调整={fg_score:.2f}",
                    ))
    return conflicts


def _get_decision_prompt() -> str:
    """Get the current decision system prompt, dynamically assembled from active rules."""
    global _rule_registry
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    yr = today[:4]
    date_note = (
        f"\n\n[TODAY: {today}. All trading decisions, entry/exit levels, stop-loss prices "
        f"must be based on CURRENT ({yr}) market conditions. "
        f"Do NOT reference {int(yr)-2}-{int(yr)-1} data as if it were recent.]"
    )
    lang_note = f"\n\n[LANGUAGE: {_lang_instruction()}]"
    try:
        from marketmind.pipeline.methodology_rules import (
            assemble_dynamic_prompt, get_default_rules
        )
        if _rule_registry is None:
            _rule_registry = get_default_rules()
        return assemble_dynamic_prompt(_rule_registry) + date_note + lang_note
    except Exception:
        return DECISION_SYSTEM_PROMPT + date_note + lang_note


def get_rule_registry():
    """Expose rule registry for SHARP evolution (P3-2b)."""
    global _rule_registry
    if _rule_registry is None:
        from marketmind.pipeline.methodology_rules import get_default_rules
        _rule_registry = get_default_rules()
    return _rule_registry


@dataclass
class DecisionCard:
    ticker: str
    direction: str                # long | short
    position_size_pct: float      # % of portfolio
    entry_low: float
    entry_high: float
    stop_loss: float
    target_price: float
    max_hold_days: int
    reward_risk_ratio: float
    thesis: str                   # 1-sentence investment thesis
    risk_statement: str           # 1-sentence risk declaration
    red_team_note: str            # most important objection
    cash_reframing: str           # "if I had cash today, would I buy this?"


@dataclass
class NoTradeCard:
    thesis: str                   # why NOT trading is the best action
    supporting_evidence: list[str]
    counterfactual: str           # what would make us trade today instead
    structural_advantages: list[str]  # why no-trade has an edge (esp. in bear/high-VIX)
    pre_mortem: str = ""          # Phase B audit: 1-year failure narrative
    no_trade_score: float = 0.0   # Phase B audit: 0-100 strength of no-trade case


@dataclass
class PaperTrade:
    ticker: str
    direction: str  # "long" or "short"
    confidence: float
    thesis: str
    source: str = ""  # e.g. "L2 fundamental", "L3 technical", "L1 narrative"


@dataclass
class DecisionOutput:
    decision_cards: list[DecisionCard] = field(default_factory=list)
    no_trade_card: NoTradeCard | None = None
    paper_trade: PaperTrade | None = None  # virtual trade when no_trade
    summary: str = ""
    contrarian_challenges: list[dict] = field(default_factory=list)


def _lang_instruction() -> str:
    """Return language directive for LLM output based on MARKETMIND_LANG env var."""
    import os as _os
    lang = _os.environ.get("MARKETMIND_LANG", "zh")
    lang_map = {
        "zh": "所有输出必须使用中文。报告、分析、结论全部用中文撰写。",
        "en": "All output must be in English.",
        "ja": "すべての出力は日本語で記述すること。",
        "ko": "모든 출력은 한국어로 작성해야 합니다.",
        "es": "Toda la salida debe estar en español.",
        "fr": "Toute sortie doit être en français.",
        "ru": "Весь вывод должен быть на русском языке.",
        "ar": "يجب أن يكون كل المخرجات باللغة العربية.",
        "de": "Alle Ausgaben müssen auf Deutsch sein.",
    }
    return lang_map.get(lang, "所有输出必须使用中文。")


def _t(key: str) -> str:
    """Return i18n message for current language. Falls back to zh."""
    import os as _os
    lang = _os.environ.get("MARKETMIND_LANG", "zh")
    msgs = _I18N.get(lang, _I18N["zh"])
    return msgs.get(key, _I18N["zh"].get(key, key))


_I18N = {
    "zh": {
        "no_signal_thesis": "无信号通过统计验证，且无标的通过技术审查。",
        "no_signal_counterfactual": "需要 DSR > 0 且 PBO <= 0.10，同时至少有一个绿灯标的。",
        "no_signal_adv_1": "统计纪律防止过拟合",
        "no_signal_adv_2": "现金保留选择权",
        "no_signal_summary": "今日无可行信号。持有现金是有效仓位。",
        "api_error_thesis": "决策合成因 API 或系统错误失败。",
        "api_error_counterfactual": "一次成功的 LLM 调用生成了决策合成。",
        "api_error_adv_1": "合成不可用时的安全默认值",
        "api_error_adv_2": "保护资本",
        "api_error_summary": "决策合成失败 — 安全起见回退到不交易。",
        "src_l1": "L1 宏观叙事",
        "src_l2": "L2 基本面",
        "src_l3": "L3 绿灯",
        "l1_bullish": "看涨",
        "l1_bearish": "看跌",
    },
    "en": {
        "no_signal_thesis": "No signal passed statistical validation and no ticker cleared technical review.",
        "no_signal_counterfactual": "A signal exceeding DSR > 0 and PBO <= 0.10 with at least 1 green-light ticker.",
        "no_signal_adv_1": "Statistical discipline prevents overfitting",
        "no_signal_adv_2": "Cash preserves optionality",
        "no_signal_summary": "No actionable signal today. Cash is a valid position.",
        "api_error_thesis": "Decision synthesis failed due to API or system error.",
        "api_error_counterfactual": "A successful LLM call producing a decision synthesis.",
        "api_error_adv_1": "Safe default when synthesis is unavailable",
        "api_error_adv_2": "Preserves capital",
        "api_error_summary": "Decision synthesis failed — falling back to no-trade for safety.",
        "src_l1": "L1 Narrative",
        "src_l2": "L2 Fundamental",
        "src_l3": "L3 Green Light",
        "l1_bullish": "bullish",
        "l1_bearish": "bearish",
    },
    "ja": {
        "no_signal_thesis": "統計的検証を通過したシグナルはなく、技術的レビューをクリアした銘柄もありません。",
        "no_signal_counterfactual": "DSR > 0 かつ PBO <= 0.10 で、少なくとも1つのグリーンライト銘柄が必要です。",
        "no_signal_adv_1": "統計的規律が過学習を防ぐ",
        "no_signal_adv_2": "現金は選択肢を保持する",
        "no_signal_summary": "本日は実行可能なシグナルなし。現金は有効なポジションです。",
        "api_error_thesis": "APIまたはシステムエラーにより決定合成に失敗しました。",
        "api_error_counterfactual": "決定合成を生成するLLM呼び出しの成功。",
        "api_error_adv_1": "合成が利用できない場合の安全なデフォルト",
        "api_error_adv_2": "資本を保護",
        "api_error_summary": "決定合成に失敗 — 安全のため取引なしにフォールバック。",
        "src_l1": "L1 マクロ分析",
        "src_l2": "L2 ファンダメンタル",
        "src_l3": "L3 グリーンライト",
        "l1_bullish": "強気",
        "l1_bearish": "弱気",
    },
    "ko": {
        "no_signal_thesis": "통계적 검증을 통과한 신호가 없으며 기술적 검토를 통과한 종목도 없습니다.",
        "no_signal_counterfactual": "DSR > 0, PBO <= 0.10, 최소 1개의 녹색 신호 종목이 필요합니다.",
        "no_signal_adv_1": "통계적 규율이 과적합 방지",
        "no_signal_adv_2": "현금은 선택권을 보존",
        "no_signal_summary": "오늘 실행 가능한 신호 없음. 현금은 유효한 포지션입니다.",
        "api_error_thesis": "API 또는 시스템 오류로 결정 합성 실패.",
        "api_error_counterfactual": "결정 합성을 생성하는 성공적인 LLM 호출.",
        "api_error_adv_1": "합성을 사용할 수 없을 때의 안전한 기본값",
        "api_error_adv_2": "자본 보호",
        "api_error_summary": "결정 합성 실패 — 안전을 위해 거래 없음으로 폴백.",
        "src_l1": "L1 매크로 분석",
        "src_l2": "L2 펀더멘털",
        "src_l3": "L3 녹색 신호",
        "l1_bullish": "강세",
        "l1_bearish": "약세",
    },
    "es": {
        "no_signal_thesis": "Ninguna señal pasó la validación estadística y ningún activo superó la revisión técnica.",
        "no_signal_counterfactual": "Una señal que supere DSR > 0 y PBO <= 0.10 con al menos un activo en luz verde.",
        "no_signal_adv_1": "La disciplina estadística previene el sobreajuste",
        "no_signal_adv_2": "El efectivo preserva la opcionalidad",
        "no_signal_summary": "Sin señales procesables hoy. El efectivo es una posición válida.",
        "api_error_thesis": "La síntesis de decisión falló por error de API o sistema.",
        "api_error_counterfactual": "Una llamada LLM exitosa que produzca una síntesis de decisión.",
        "api_error_adv_1": "Valor predeterminado seguro cuando la síntesis no está disponible",
        "api_error_adv_2": "Preserva el capital",
        "api_error_summary": "Síntesis de decisión fallida — recurriendo a no operar por seguridad.",
        "src_l1": "L1 Narrativa",
        "src_l2": "L2 Fundamental",
        "src_l3": "L3 Luz Verde",
        "l1_bullish": "alcista",
        "l1_bearish": "bajista",
    },
    "fr": {
        "no_signal_thesis": "Aucun signal n'a passé la validation statistique et aucun actif n'a réussi l'examen technique.",
        "no_signal_counterfactual": "Un signal dépassant DSR > 0 et PBO <= 0.10 avec au moins un actif en feu vert.",
        "no_signal_adv_1": "La discipline statistique empêche le surapprentissage",
        "no_signal_adv_2": "Les liquidités préservent l'optionalité",
        "no_signal_summary": "Aucun signal exploitable aujourd'hui. Les liquidités sont une position valide.",
        "api_error_thesis": "La synthèse de décision a échoué en raison d'une erreur API ou système.",
        "api_error_counterfactual": "Un appel LLM réussi produisant une synthèse de décision.",
        "api_error_adv_1": "Valeur par défaut sûre lorsque la synthèse n'est pas disponible",
        "api_error_adv_2": "Préserve le capital",
        "api_error_summary": "Échec de la synthèse de décision — repli vers l'absence de transaction par sécurité.",
        "src_l1": "L1 Récit",
        "src_l2": "L2 Fondamental",
        "src_l3": "L3 Feu Vert",
        "l1_bullish": "haussier",
        "l1_bearish": "baissier",
    },
    "ru": {
        "no_signal_thesis": "Ни один сигнал не прошёл статистическую проверку, и ни один актив не прошёл технический обзор.",
        "no_signal_counterfactual": "Сигнал с DSR > 0 и PBO <= 0.10, имеющий хотя бы один актив с зелёным светом.",
        "no_signal_adv_1": "Статистическая дисциплина предотвращает переобучение",
        "no_signal_adv_2": "Наличные сохраняют опциональность",
        "no_signal_summary": "Сегодня нет действенных сигналов. Наличные — допустимая позиция.",
        "api_error_thesis": "Синтез решения не удался из-за ошибки API или системы.",
        "api_error_counterfactual": "Успешный вызов LLM, создающий синтез решения.",
        "api_error_adv_1": "Безопасное значение по умолчанию при недоступности синтеза",
        "api_error_adv_2": "Сохраняет капитал",
        "api_error_summary": "Синтез решения не удался — возврат к отсутствию сделок для безопасности.",
        "src_l1": "L1 Макро",
        "src_l2": "L2 Фундамент",
        "src_l3": "L3 Зелёный",
        "l1_bullish": "бычий",
        "l1_bearish": "медвежий",
    },
    "ar": {
        "no_signal_thesis": "لم تتجاوز أي إشارة التحقق الإحصائي ولم يجتز أي أصل المراجعة الفنية.",
        "no_signal_counterfactual": "إشارة تتجاوز DSR > 0 و PBO <= 0.10 مع أصل واحد على الأقل في الضوء الأخضر.",
        "no_signal_adv_1": "الانضباط الإحصائي يمنع الإفراط في التخصيص",
        "no_signal_adv_2": "النقد يحافظ على الخيارات",
        "no_signal_summary": "لا توجد إشارات قابلة للتنفيذ اليوم. النقد مركز صالح.",
        "api_error_thesis": "فشل تركيب القرار بسبب خطأ في API أو النظام.",
        "api_error_counterfactual": "استدعاء LLM ناجح ينتج تركيب قرار.",
        "api_error_adv_1": "القيمة الافتراضية الآمنة عند عدم توفر التركيب",
        "api_error_adv_2": "يحافظ على رأس المال",
        "api_error_summary": "فشل تركيب القرار — التراجع إلى عدم التداول للسلامة.",
        "src_l1": "L1 السرد",
        "src_l2": "L2 أساسي",
        "src_l3": "L3 ضوء أخضر",
        "l1_bullish": "صاعد",
        "l1_bearish": "هابط",
    },
    "de": {
        "no_signal_thesis": "Kein Signal hat die statistische Validierung bestanden und kein Wert hat die technische Prüfung bestanden.",
        "no_signal_counterfactual": "Ein Signal mit DSR > 0 und PBO <= 0.10 mit mindestens einem Wert mit grünem Licht.",
        "no_signal_adv_1": "Statistische Disziplin verhindert Überanpassung",
        "no_signal_adv_2": "Bargeld bewahrt Optionalität",
        "no_signal_summary": "Heute keine handelbaren Signale. Bargeld ist eine gültige Position.",
        "api_error_thesis": "Entscheidungssynthese aufgrund eines API- oder Systemfehlers fehlgeschlagen.",
        "api_error_counterfactual": "Ein erfolgreicher LLM-Aufruf, der eine Entscheidungssynthese erzeugt.",
        "api_error_adv_1": "Sicherer Standardwert, wenn Synthese nicht verfügbar ist",
        "api_error_adv_2": "Bewahrt Kapital",
        "api_error_summary": "Entscheidungssynthese fehlgeschlagen — Rückfall auf Nicht-Handel aus Sicherheitsgründen.",
        "src_l1": "L1 Makro",
        "src_l2": "L2 Fundamental",
        "src_l3": "L3 Grünes Licht",
        "l1_bullish": "bullisch",
        "l1_bearish": "bärisch",
    },
}


CONTRARIAN_PROMPT = """你是独立风控分析师。对以下投资决策方案提出2-3个具体的反对意见。
每个反对意见包含：风险描述、潜在损失幅度（百分比）、触发条件。
用中文。输出JSON: {"challenges": [{"risk": "...", "loss_pct": X.X, "trigger": "..."}]}
Output ONLY JSON."""


DECISION_SYSTEM_PROMPT = """You are a decision synthesis engine. Your job is to produce the final decision cards that a human investor will review.

You receive:
- Layer 1 narrative analysis
- Layer 2 fundamental analysis with ticker candidates
- Layer 3 technical review (green/yellow/red lights)
- Red Team challenges
- Signal resonance verdict

Output JSON:
{
  "decision_cards": [
    {
      "ticker": "TICKER",
      "direction": "long|short",
      "position_size_pct": 0.0,
      "entry_low": 0.0,
      "entry_high": 0.0,
      "stop_loss": 0.0,
      "target_price": 0.0,
      "max_hold_days": 30,
      "reward_risk_ratio": 0.0,
      "thesis": "1-sentence thesis",
      "risk_statement": "1-sentence risk",
      "red_team_note": "key objection",
      "cash_reframing": "if I had cash today..."
    }
  ],
  "no_trade_card": {
    "thesis": "why not trading is best",
    "supporting_evidence": ["reason1", "reason2"],
    "counterfactual": "what would make us trade",
    "structural_advantages": ["edge1", "edge2"],
    "pre_mortem": "Assume 1 year later the traded position lost 50%. Write step-by-step what broke.",
    "no_trade_score": 0.0
  },
  "summary": "1-paragraph overall assessment"
}

IMPORTANT: The no-trade card must be equally rigorous as the decision cards — not an afterthought. Include a pre-mortem narrative (assume 1yr later, traded position lost 50% — what broke?). Score no-trade strength 0-100.
Position size: never exceed 25% total heat limit. Combined stop-losses across all positions ≤ 25% total equity.
All prices must be verifiable. Never fabricate."""


async def generate_contrarian_challenges(decision: DecisionOutput) -> list[dict]:
    """Run a contrarian LLM call challenging the decision thesis.

    Args:
        decision: The DecisionOutput from main synthesis (reads tickers,
                  directions, and theses from decision_cards).

    Returns:
        List of challenge dicts with keys: risk, loss_pct, trigger.
        Returns empty list on any failure (non-blocking).
    """
    if not decision.decision_cards:
        return []

    cards_text = "\n".join(
        f"- {c.ticker} ({c.direction}): {c.thesis[:200]}"
        for c in decision.decision_cards[:5]
    )
    user_prompt = f"待审查的投资方案:\n{cards_text}\n\n请提出2-3个具体的反对意见。"

    try:
        result = await chat_pro(
            system_prompt=CONTRARIAN_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=8192,
            reasoning_effort="minimal",
        )
        content = strip_markdown_fences(result.get("content", ""))
        data = json.loads(content)
        challenges = data.get("challenges", [])
        # Validate each challenge has required keys
        validated = []
        for ch in challenges:
            if isinstance(ch, dict) and "risk" in ch and "loss_pct" in ch and "trigger" in ch:
                validated.append({
                    "risk": str(ch["risk"]),
                    "loss_pct": float(ch["loss_pct"]),
                    "trigger": str(ch["trigger"]),
                })
        return validated
    except Exception:
        logger.warning("Contrarian challenge generation failed (non-blocking)", exc_info=True)
        return []


@monitor(source="decision", impact=ImpactScope.MAIN_PIPELINE)
async def generate_decision(
    l1: Layer1Result,
    l2: Layer2Result,
    l3: Layer3BatchResult,
    red_team: RedTeamReport,
    resonance: ResonanceResult,
) -> DecisionOutput:
    """Generate final decision cards and no-trade card."""
    if not resonance.passed and not l3.green_lights:
        paper = _pick_paper_trade(l1, l2, l3, red_team, resonance)
        return DecisionOutput(
            no_trade_card=NoTradeCard(
                thesis=_t("no_signal_thesis"),
                supporting_evidence=[f"DSR={resonance.dsr}, PBO={resonance.pbo}"],
                counterfactual=_t("no_signal_counterfactual"),
                structural_advantages=[_t("no_signal_adv_1"), _t("no_signal_adv_2")],
                pre_mortem="",
                no_trade_score=100.0,
            ),
            paper_trade=paper,
            summary=_t("no_signal_summary"),
        )
    user_prompt = _build_decision_prompt(l1, l2, l3, red_team, resonance)
    try:
        # P3-2b: use dynamically assembled prompt from SHARP rule registry
        dynamic_prompt = _get_decision_prompt()
        result = await chat_pro(
            system_prompt=dynamic_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=16384,
        )
        decision = _parse_decision_response(result["content"])
        decision.contrarian_challenges = await generate_contrarian_challenges(decision)
        return decision
    except Exception as e:
        logger.warning("Decision generation failed: %s", e)
        paper = _pick_paper_trade(l1, l2, l3, red_team, resonance)
        return DecisionOutput(
            no_trade_card=NoTradeCard(
                thesis=_t("api_error_thesis"),
                supporting_evidence=[f"Error: {str(e)[:200]}"],
                counterfactual=_t("api_error_counterfactual"),
                structural_advantages=[_t("api_error_adv_1"), _t("api_error_adv_2")],
                no_trade_score=100.0,
            ),
            paper_trade=paper,
            summary=_t("api_error_summary"),
        )


def _pick_paper_trade(l1, l2, l3, red_team, resonance) -> PaperTrade | None:
    """When no_trade, pick the best-conviction direction for virtual (paper) trading.

    Scans L2 candidates + L3 lights to find the ticker with strongest directional signal.
    Used for post-hoc review (复盘) without risking real capital.
    """
    candidates: list[dict] = []

    # From L2 ticker candidates
    for t in getattr(l2, 'ticker_candidates', []) or []:
        candidates.append({
            "ticker": str(t),
            "direction": getattr(t, 'direction', 'neutral'),
            "confidence": getattr(t, 'confidence', 0.0),
            "thesis": getattr(t, 'thesis', ''),
            "source": _t("src_l2"),
        })

    # From L3 green lights (strongest signal)
    for r in getattr(l3, 'results', []) or []:
        ticker = getattr(r, 'ticker', '')
        if ticker in getattr(l3, 'green_lights', []):
            candidates.append({
                "ticker": str(ticker),
                "direction": getattr(r, 'direction', 'long'),
                "confidence": 0.65,
                "thesis": getattr(r, 'summary', ''),
                "source": _t("src_l3"),
            })

    # From L1 sentiment if available
    l1_dir = getattr(l1, 'sentiment_direction', 'neutral')
    if l1_dir in ('bullish', 'bearish') and not candidates:
        direction = 'long' if l1_dir == 'bullish' else 'short'
        l1_label = _t("l1_bullish") if l1_dir == 'bullish' else _t("l1_bearish")
        for r in getattr(l3, 'results', []) or []:
            candidates.append({
                "ticker": str(getattr(r, 'ticker', 'SPY')),
                "direction": direction,
                "confidence": 0.45,
                "thesis": f"{_t('src_l1')}: {l1_label}",
                "source": _t("src_l1"),
            })
            break

    if not candidates:
        return None

    # Sort by confidence descending
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    best = candidates[0]
    return PaperTrade(
        ticker=best["ticker"],
        direction=best["direction"],
        confidence=best["confidence"],
        thesis=best["thesis"],
        source=best["source"],
    )


def _build_decision_prompt(
    l1: Layer1Result, l2: Layer2Result, l3: Layer3BatchResult,
    red_team: RedTeamReport, resonance: ResonanceResult,
) -> str:
    green = [r.ticker for r in l3.green_lights]
    challenges_str = "\n".join(
        f"- [{c.severity}] {defang_text(c.challenge)}" for c in red_team.challenges[:5]
    )

    defanged_tickers = [defang_text(t) for t in l2.ticker_candidates[:10]]

    return f"""## Signal Resonance
Verdict: {resonance.verdict} | DSR: {resonance.dsr} | PBO: {resonance.pbo}

## Layer 1 Narrative
Quadrant: {defang_text(l1.matrix_quadrant)} | Sentiment: {defang_text(l1.sentiment_direction)} | Price-in: {l1.price_in_score}

## Layer 2 Fundamentals
Tickers: {', '.join(defanged_tickers)}

## Layer 3 Technical (GREEN lights only)
{', '.join(green) if green else 'None — no ticker passed L3'}

## Red Team Challenges
{challenges_str if challenges_str else 'No challenges raised'}

Produce decision cards for GREEN-light tickers only. Generate a parallel no-trade card with equal rigor."""


def _parse_decision_response(content: str) -> DecisionOutput:
    content = strip_markdown_fences(content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return DecisionOutput(summary="Failed to parse decision output")
    cards = []
    for d in data.get("decision_cards", []):
        cards.append(DecisionCard(
            ticker=d.get("ticker", ""),
            direction=d.get("direction", "long"),
            position_size_pct=float(d.get("position_size_pct", 0)),
            entry_low=float(d.get("entry_low", 0)),
            entry_high=float(d.get("entry_high", 0)),
            stop_loss=float(d.get("stop_loss", 0)),
            target_price=float(d.get("target_price", 0)),
            max_hold_days=int(d.get("max_hold_days", 30)),
            reward_risk_ratio=float(d.get("reward_risk_ratio", 0)),
            thesis=d.get("thesis", ""),
            risk_statement=d.get("risk_statement", ""),
            red_team_note=d.get("red_team_note", ""),
            cash_reframing=d.get("cash_reframing", ""),
        ))
    ntc_data = data.get("no_trade_card", {})
    no_trade = None
    if ntc_data:
        no_trade = NoTradeCard(
            thesis=ntc_data.get("thesis", ""),
            supporting_evidence=ntc_data.get("supporting_evidence", []),
            counterfactual=ntc_data.get("counterfactual", ""),
            structural_advantages=ntc_data.get("structural_advantages", []),
            pre_mortem=ntc_data.get("pre_mortem", ""),
            no_trade_score=float(ntc_data.get("no_trade_score", 0)),
        )
    return DecisionOutput(
        decision_cards=cards,
        no_trade_card=no_trade,
        summary=data.get("summary", ""),
    )
