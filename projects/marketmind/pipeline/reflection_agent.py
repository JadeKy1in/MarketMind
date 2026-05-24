"""Reflection agent for post-mortem analysis of expired predictions.

Layer 3 of Phase I: Structured learning from verified outcomes.
Flash for success cases (cheap), Pro for failure cases (deep analysis).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope

from marketmind.gateway.async_client import chat_flash, chat_pro
from marketmind.pipeline.prediction_extractor import PredictableHypothesis


@dataclass
class StructuredLesson:
    lesson_id: str
    prediction_id: str
    outcome: str              # "SUCCESS" | "FAILURE"
    root_cause: str           # from taxonomy below
    updated_belief: str       # what the system should now believe differently
    entity: str               # affected asset/sector
    relevance_score: float    # 0-1 how useful for future analyses
    created_at: str
    decay_factor: float = 1.0


ROOT_CAUSE_TAXONOMY = {
    "MISSING_DATA": "事后出现新数据推翻了预测 — 分析时缺少关键信息",
    "FLAWED_CHAIN": "因果推理链条断裂 — A→B的逻辑不成立",
    "REGIME_CHANGE": "环境发生结构性变化 — 旧框架不再适用",
    "OVERCONFIDENCE": "预测方向正确但置信度过高 — 校准问题",
    "CORRECT_REASONING": "推理正确但幅度估计不足",
    "BLACK_SWAN": "不可预测的外部冲击",
    "DATA_SOURCE_ERROR": "数据源本身有误 — 并非分析错误",
}

_RELEVANCE_BY_CAUSE = {
    "CORRECT_REASONING": 0.8,
    "FLAWED_CHAIN": 0.7,
    "OVERCONFIDENCE": 0.6,
    "MISSING_DATA": 0.5,
    "DATA_SOURCE_ERROR": 0.4,
    "REGIME_CHANGE": 0.3,
    "BLACK_SWAN": 0.2,
}

_DECAY_FACTOR = 0.95
_MAX_BATCH_SIZE = 10

_REFLECTION_SYSTEM_PROMPT = (
    "你是一个投资分析反思系统。你的任务是对已经验证的预测进行事后分析，"
    "找出成功或失败的根本原因，并提出系统应该更新的信念。\n\n"
    "你需要：\n"
    "1. 判断预测成功/失败的根本原因（从给定的分类中选择）\n"
    "2. 指出系统应该更新什么具体信念\n"
    "3. 保持客观、具体，不泛泛而谈\n\n"
    "请以JSON格式回复，包含以下字段：\n"
    '{"root_cause": "分类名称", "updated_belief": "系统应该更新的具体信念", "entity": "受影响的资产/板块"}'
)


def _generate_lesson_id(prediction_id: str) -> str:
    raw = f"lesson_{prediction_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_entity(prediction: PredictableHypothesis) -> str:
    source = prediction.verification_source
    if ":" in source:
        return source.split(":", 1)[-1]
    return source


def _parse_reflection_response(raw_content: str) -> dict:
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[^{}]*"root_cause"[^{}]*\}', raw_content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"root_cause": "FLAWED_CHAIN", "updated_belief": raw_content[:200], "entity": "unknown"}


async def run_reflection(
    prediction: PredictableHypothesis,
    original_analysis: str,
) -> StructuredLesson | None:
    """Reflect on a single verified prediction and produce a structured lesson."""
    if prediction.status == "PENDING":
        return None

    now = datetime.now(timezone.utc)
    entity = _extract_entity(prediction)
    taxonomy_keys = list(ROOT_CAUSE_TAXONOMY.keys())

    if prediction.status == "VERIFIED_SUCCESS":
        outcome = "SUCCESS"
        user_prompt = (
            f"这个预测被验证为**正确**：\n\n"
            f"原始分析：{original_analysis[:2000]}\n\n"
            f"预测内容：{prediction.prediction}\n"
            f"置信度：{prediction.confidence}\n"
            f"实际结果：{prediction.actual_value}\n\n"
            f"请判断：\n"
            f"1. 推理过程是否真的合理？还是只是运气好？\n"
            f"2. 如果推理正确，我们应该强化什么信念？\n"
            f"3. 如果只是运气，根本原因是什么？\n\n"
            f"根本原因分类：{json.dumps(taxonomy_keys, ensure_ascii=False)}\n"
            f"请以JSON格式回复。"
        )
        result = await chat_flash(
            system_prompt=_REFLECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=1024,
        )
    elif prediction.status == "VERIFIED_FAILURE":
        outcome = "FAILURE"
        user_prompt = (
            f"这个预测被验证为**失败**：\n\n"
            f"原始分析：{original_analysis[:3000]}\n\n"
            f"预测内容：{prediction.prediction}\n"
            f"置信度：{prediction.confidence}\n"
            f"方向：{prediction.direction} {prediction.success_value}\n"
            f"实际结果：{prediction.actual_value}\n\n"
            f"请深入分析失败的根本原因，从以下分类中选择最匹配的一个：\n"
            f"{json.dumps(ROOT_CAUSE_TAXONOMY, ensure_ascii=False, indent=2)}\n\n"
            f"请以JSON格式回复。"
        )
        result = await chat_pro(
            system_prompt=_REFLECTION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
        )
    else:
        return None

    content = result.get("content", "")
    if not content:
        return None

    parsed = _parse_reflection_response(content)

    root_cause = parsed.get("root_cause", "FLAWED_CHAIN")
    if root_cause not in ROOT_CAUSE_TAXONOMY:
        root_cause = "FLAWED_CHAIN"

    relevance = _RELEVANCE_BY_CAUSE.get(root_cause, 0.5)

    return StructuredLesson(
        lesson_id=_generate_lesson_id(prediction.hypothesis_id),
        prediction_id=prediction.hypothesis_id,
        outcome=outcome,
        root_cause=root_cause,
        updated_belief=parsed.get("updated_belief", ""),
        entity=parsed.get("entity", entity),
        relevance_score=relevance,
        created_at=now.isoformat(),
        decay_factor=_DECAY_FACTOR,
    )


@monitor(source="reflection_agent", impact=ImpactScope.MAIN_PIPELINE)
async def run_batch_reflection(
    expired_predictions: list[PredictableHypothesis],
    store,  # LearningStore
) -> list[StructuredLesson]:
    """Process all expired predictions, save lessons to store.

    PENDING predictions are skipped. Non-PENDING but non-verified statuses
    (EXPIRED_UNVERIFIABLE, etc.) are skipped by run_reflection.
    Capped at _MAX_BATCH_SIZE reflections per run.
    """
    lessons: list[StructuredLesson] = []
    reflected_ids: set[str] = set()
    count = 0

    for p in expired_predictions:
        if p.status == "PENDING":
            continue
        if count >= _MAX_BATCH_SIZE:
            break
        if p.hypothesis_id in reflected_ids:
            continue

        lesson = await run_reflection(p, p.hypothesis_text)
        if lesson is None:
            continue

        store.save_lesson(vars(lesson))
        lessons.append(lesson)
        reflected_ids.add(p.hypothesis_id)
        count += 1

    return lessons
