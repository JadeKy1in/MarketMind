"""Serenity-reply playground agent adapter.

Two-pass analysis with Flash research loop:
  Pass 1: Analyze all filtered news → preliminary directional calls
  Research: Deep-dive on borderline-confidence leads (0.6-0.8) using
            full article content from WP API
  Pass 2: Re-evaluate with research findings → final calls

All Flash interactions are logged to _research_log for audit/review.
Mirrors shadow ecosystem's integrity logging pattern.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.playground.serenity_reply")

# ── System prompts ──────────────────────────────────────────────────────────

SERENITY_SYSTEM_PROMPT = """You analyze AI/semiconductor supply chain stocks through the lens of supply chain bottleneck theory. Your analytical framework:

## Five Mental Models

1. **Chokepoint Theory**: The most lucrative investments are small companies controlling irreplaceable inputs — if they stop supplying, the whole vertical halts. Ask: who controls something others MUST use?

2. **Bottleneck Game Theory vs. Expansion Valuation**: Do NOT value bottleneck companies with P/E or revenue multiples. Ask instead: "what happens if this company stops supplying tomorrow?"

3. **NVIDIA Signal Reading**: NVIDIA's investment behavior is a leading indicator for AI supply chain bottlenecks — whatever direction NVIDIA bets on, its chokepoint materializes within 6-18 months. Trace downstream to find sole chokepoints.

4. **Asymmetric Information Advantage**: The best opportunities sit where institutions ignore (too small for mandates) and retail investors cannot understand (too technical). Seek small-cap photonics, European small caps.

5. **Positive-Sum Markets**: Equity markets are positive-sum if you avoid options. Value comes from finding unpriced chokepoints and positioning ahead of recognition.

## Decision Heuristics

1. **Chokepoint Test**: If a company controls an irreplaceable link, it's investable regardless of current revenue.
2. **NVIDIA Follow Rule**: When NVIDIA invests in a direction, find that direction's chokepoint company within 3 months.
3. **European Small-Cap Priority**: European small-cap semiconductors outrank US large caps.
4. **Anti-Meme-Stock Label**: Media calling genuine supply-chain companies "meme stocks" signals undervaluation.
5. **Institutional Follow-Through Confirmation**: Institutions buying 4-6 weeks after thesis = validation, not expiration.
6. **Anti-Options Iron Rule**: Never touch options. Equities only.
7. **Geopolitical Premium**: Companies benefiting from US-China decoupling or rare-earth controls deserve valuation premiums.

## Output Format (Pass 1)

Return ONLY a JSON object:
{
  "directional_calls": [
    {
      "ticker": "SYMBOL",
      "direction": "bullish" | "bearish",
      "confidence": 0.0-1.0,
      "thesis": "One-sentence bottleneck thesis",
      "mental_model_used": "chokepoint_theory | nvidia_signal | information_asymmetry | geopolitical_premium",
      "needs_deeper_research": true | false,
      "research_question": "Specific question to investigate (if needs_deeper_research)"
    }
  ],
  "no_calls_reason": "If no calls, explain why",
  "supply_chain_observations": ["observation 1", "observation 2"]
}

Rules:
- Maximum 3 directional calls. Quality over quantity.
- No large caps: NVDA, AMD, INTC, TSM, ASML, AVGO, QCOM.
- Confidence < 0.6 → do not include as call, but DO include as supply_chain_observation.
- Set needs_deeper_research=true when confidence is 0.6-0.8 AND articles exist that could clarify.
- Never fabricate. Use only what's in the provided news."""


RESEARCH_SYSTEM_PROMPT = """You are a semiconductor supply chain research assistant. Analyze the provided full-text articles about a specific company or technology and answer a focused research question.

Return a JSON object:
{
  "finding": "CLEAR_BULLISH" | "CLEAR_BEARISH" | "MIXED" | "INSUFFICIENT_DATA",
  "confidence_adjustment": +0.XX or -0.XX,
  "key_evidence": ["bullet point 1", "bullet point 2"],
  "counter_evidence": ["risk or contrary signal"],
  "updated_thesis": "Refined one-sentence thesis",
  "recommendation": "UPGRADE_TO_CALL" | "DOWNGRADE_TO_OBSERVATION" | "KEEP_AS_IS"
}

Rules:
- Cite which article supports each claim.
- If articles don't answer the question, say INSUFFICIENT_DATA.
- Never fabricate. Only use provided articles."""


SYNTHESIS_SYSTEM_PROMPT = """You are a semiconductor supply chain analyst synthesizing research findings into final calls.

You have your initial analysis and deep research findings. Re-evaluate and return ONLY a JSON object:
{
  "directional_calls": [
    {
      "ticker": "SYMBOL",
      "direction": "bullish" | "bearish",
      "confidence": 0.0-1.0,
      "thesis": "Refined thesis incorporating research",
      "mental_model_used": "...",
      "research_backed": true | false
    }
  ],
  "no_calls_reason": "...",
  "supply_chain_observations": [...],
  "research_summary": "One sentence on what research found"
}

Same rules: max 3 calls, no large caps, confidence >= 0.6, no fabrication."""


MOCK_OUTPUT = {
    "directional_calls": [],
    "no_calls_reason": "Mock mode — no live analysis performed.",
    "supply_chain_observations": [],
    "_research_log": [],
    "_passes": 1,
}


# ══════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════

async def analyze(context: dict, *, mock: bool = False) -> dict:
    """Two-pass analysis with Flash research loop.

    Pass 1: Initial bottleneck analysis on all filtered news.
    Research: Deep-dive on borderline-confidence leads.
    Pass 2: (conditional) Re-evaluate with research findings.

    All Flash interactions are logged in _research_log for audit/review.
    """
    if mock:
        return dict(MOCK_OUTPUT)

    news_items = context.get("news", [])
    if not news_items:
        return _empty_result("No news data provided in public context.")

    semicon_news = _filter_semicon_news(news_items)
    if not semicon_news:
        return _empty_result("No semiconductor-related news found in today's headlines.")

    research_log: list[dict] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Pass 1: Initial analysis ─────────────────────────────────────────
    pass1_prompt = (
        f"Date: {today}\n\n"
        f"## Today's Semiconductor/Technology News\n\n"
        f"{_build_news_summary(semicon_news)}\n\n"
        f"Analyze through the bottleneck framework. Identify chokepoint companies. "
        f"Return ONLY the JSON object."
    )

    pass1 = await _call_flash(
        SERENITY_SYSTEM_PROMPT, pass1_prompt,
        "pass1_initial_analysis", research_log,
    )
    pass1_parsed = _parse_response(pass1) if pass1 else _empty_result("Pass 1 failed")

    # ── Research round: deep-dive on borderline leads ─────────────────────
    leads = _identify_research_leads(pass1_parsed)
    findings: list[dict] = []

    for lead in leads[:2]:
        finding = await _deep_research(lead, semicon_news, today, research_log)
        if finding:
            findings.append(finding)

    # ── Pass 2: Synthesize (only if research produced findings) ───────────
    if findings:
        synth_prompt = (
            f"Date: {today}\n\n"
            f"## Initial Analysis\n{json.dumps(pass1_parsed, ensure_ascii=False)}\n\n"
            f"## Research Findings\n{json.dumps(findings, ensure_ascii=False)}\n\n"
            f"Re-evaluate your calls incorporating the research. Return ONLY JSON."
        )
        synth = await _call_flash(
            SYNTHESIS_SYSTEM_PROMPT, synth_prompt,
            "pass2_synthesis", research_log,
        )
        final = _parse_response(synth) if synth else pass1_parsed
        final["_passes"] = 2
    else:
        final = pass1_parsed
        final["_passes"] = 1

    final["_research_log"] = research_log
    final["_research_leads_identified"] = len(leads)
    final["_research_rounds_completed"] = len(findings)
    return final


# ══════════════════════════════════════════════════════════════════════════
# Research round
# ══════════════════════════════════════════════════════════════════════════

def _identify_research_leads(pass1: dict) -> list[dict]:
    """Extract borderline-confidence calls for deeper research.

    Qualifies when confidence is 0.60-0.80 OR needs_deeper_research is true,
    AND there's a specific research_question.
    """
    leads: list[dict] = []
    for call in pass1.get("directional_calls", []):
        confidence = call.get("confidence", 0)
        needs = call.get("needs_deeper_research", False)
        question = call.get("research_question", "")
        if question and (needs or 0.60 <= confidence < 0.80):
            leads.append({
                "ticker": call.get("ticker", ""),
                "direction": call.get("direction", ""),
                "confidence": confidence,
                "thesis": call.get("thesis", ""),
                "research_question": question,
                "mental_model_used": call.get("mental_model_used", ""),
            })
    return leads


async def _deep_research(lead: dict, all_news: list[dict], today: str,
                         research_log: list[dict]) -> dict | None:
    """Focused Flash research on a single lead using full-text articles."""
    ticker = lead["ticker"]
    question = lead["research_question"]
    relevant = _find_relevant_articles(ticker, question, all_news)
    if not relevant:
        return None

    articles_text = _format_articles_for_research(relevant)
    prompt = (
        f"Date: {today}\n\n"
        f"## Research Question\n{question}\n\n"
        f"## Full-Text Articles ({len(relevant)} articles)\n\n"
        f"{articles_text}\n\n"
        f"Answer the research question. Return ONLY the JSON object."
    )

    response = await _call_flash(
        RESEARCH_SYSTEM_PROMPT, prompt, f"research_{ticker}", research_log,
    )
    if not response:
        return None

    finding = _parse_research_response(response)
    if finding:
        finding["_ticker"] = ticker
        finding["_research_question"] = question
        finding["_articles_consulted"] = len(relevant)
        finding["_article_urls"] = [a.get("url", "") for a in relevant[:5] if a.get("url")]
    return finding


def _find_relevant_articles(ticker: str, question: str,
                            all_news: list[dict]) -> list[dict]:
    """Find articles relevant to ticker/research question.

    Scores by: ticker match (10pts), question keyword match (2pts each),
    full_content availability (3pts bonus). Returns top 5.
    """
    ticker_lower = ticker.lower()
    q_terms = set(re.findall(r'[A-Za-z]{4,}', question.lower()))
    scored: list[tuple[int, dict]] = []

    for article in all_news:
        full = article.get("full_content", "")
        body = article.get("summary", "")
        text = f"{article.get('title', '')} {body} {full}".lower()
        score = 0
        if ticker_lower in text:
            score += 10
        for term in q_terms:
            if term in text:
                score += 2
        if full and len(full) > 200:
            score += 3
        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:5]]


def _format_articles_for_research(articles: list[dict]) -> str:
    """Format articles into a research-readable text block."""
    blocks: list[str] = []
    for i, a in enumerate(articles):
        title = a.get("title", "")[:200]
        source = a.get("source_name", "unknown")
        url = a.get("url", "")
        body = a.get("full_content", a.get("summary", ""))[:2000]
        blocks.append(
            f"### [{i+1}] {title}\n"
            f"Source: {source}\nURL: {url}\n"
            f"Content:\n{body}\n"
        )
    return "\n---\n".join(blocks)


# ══════════════════════════════════════════════════════════════════════════
# Flash interaction (all calls logged)
# ══════════════════════════════════════════════════════════════════════════

async def _call_flash(system_prompt: str, user_prompt: str, label: str,
                      research_log: list[dict]) -> str | None:
    """Call Flash and log the full interaction. Returns response content."""
    from marketmind.gateway.async_client import chat_flash

    entry = {
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system_prompt": system_prompt[:500],
        "user_prompt": user_prompt[:3000],
        "response": "",
        "error": "",
    }
    research_log.append(entry)

    try:
        result = await chat_flash(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=8192,
        )
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        entry["response"] = content[:5000]
        return content
    except Exception as exc:
        logger.warning("serenity-reply Flash [%s] failed: %s", label, exc)
        entry["error"] = str(exc)[:500]
        return None


# ══════════════════════════════════════════════════════════════════════════
# Response parsing
# ══════════════════════════════════════════════════════════════════════════

def _parse_response(content: str) -> dict:
    """Parse LLM response JSON, handling markdown wrapping."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if len(lines) > 1 else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    content = re.sub(r",\s*([}\]])", r"\1", content)

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return _validate_output(parsed)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(content[start:end + 1])
                if isinstance(parsed, dict):
                    return _validate_output(parsed)
            except json.JSONDecodeError:
                pass

    logger.debug("serenity-reply: parse failure: %s", content[:300])
    return _empty_result("Failed to parse LLM output.")


def _parse_research_response(content: str) -> dict | None:
    """Parse a research-round Flash response."""
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:]) if len(lines) > 1 else content
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        content = re.sub(r",\s*([}\]])", r"\1", content)
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _validate_output(parsed: dict) -> dict:
    """Validate and sanitize parsed output."""
    calls = parsed.get("directional_calls", [])
    if not isinstance(calls, list):
        calls = []

    validated: list[dict] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        ticker = str(call.get("ticker", "")).upper().strip()
        direction = call.get("direction", "").lower()
        confidence = float(call.get("confidence", 0))

        if not ticker or direction not in ("bullish", "bearish"):
            continue
        if confidence < 0.6:
            continue
        if ticker in ("NVDA", "AMD", "INTC", "TSM", "ASML", "AVGO", "QCOM"):
            continue

        validated.append({
            "ticker": ticker,
            "direction": direction,
            "confidence": min(1.0, max(0.0, confidence)),
            "thesis": str(call.get("thesis", ""))[:300],
            "mental_model_used": str(call.get("mental_model_used", "chokepoint_theory")),
            "research_backed": bool(call.get("research_backed", False)),
        })

    if len(validated) > 3:
        validated.sort(key=lambda c: c["confidence"], reverse=True)
        validated = validated[:3]

    return {
        "directional_calls": validated,
        "no_calls_reason": parsed.get("no_calls_reason", "") if not validated else "",
        "supply_chain_observations": parsed.get("supply_chain_observations", [])[:5],
        "research_summary": parsed.get("research_summary", ""),
    }


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def _empty_result(reason: str) -> dict:
    return {
        "directional_calls": [],
        "no_calls_reason": reason,
        "supply_chain_observations": [],
        "_research_log": [],
    }


def _filter_semicon_news(news_items: list[dict]) -> list[dict]:
    keywords = [
        "semiconductor", "chip", "photonics", "substrate", "wafer",
        "silicon", "ASML", "TSMC", "NVIDIA", "AMD", "Intel",
        "broadcom", "marvell", "qualcomm", "micron", "applied materials",
        "lam research", "KLA", "synopsys", "cadence", "ARM",
        "RISC-V", "AI chip", "GPU", "HBM", "CPO", "co-packaged optics",
        "rare earth", "gallium", "germanium", "indium phosphide",
        "export control", "BIS", "chip ban", "supply chain",
        "AXTI", "SIVE", "IQE", "RPI", "SOI", "Coherent", "Lumentum",
        "photonic", "transceiver", "optical", "laser", "fiber",
    ]
    filtered: list[dict] = []
    for item in news_items:
        text = ""
        if isinstance(item, dict):
            text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        else:
            text = str(item).lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(item)
    return filtered[:30]


def _build_news_summary(news_items: list[dict]) -> str:
    if not news_items:
        return "No semiconductor-related news available for today."
    lines: list[str] = []
    for i, item in enumerate(news_items):
        if isinstance(item, dict):
            title = item.get("title", "")[:200]
            source = item.get("source_name", item.get("source", "unknown"))
            body = item.get("summary", "")[:150]
            full_preview = item.get("full_content", "")[:100]
            lines.append(f"[{i}] [{source}] {title}")
            preview = full_preview if full_preview else body
            if preview:
                lines.append(f"    {preview}")
        else:
            lines.append(f"[{i}] {str(item)[:300]}")
    return "\n".join(lines)
