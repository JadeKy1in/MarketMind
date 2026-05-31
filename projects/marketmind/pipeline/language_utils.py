"""Shared language instruction helper — used by all pipeline stages that call LLM."""
from __future__ import annotations
import os as _os

_LANG_INSTRUCTIONS = {
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


def lang_instruction() -> str:
    """Return language directive for LLM output based on MARKETMIND_LANG env var."""
    lang = _os.environ.get("MARKETMIND_LANG", "zh")
    return _LANG_INSTRUCTIONS.get(lang, _LANG_INSTRUCTIONS["zh"])


def lang_note() -> str:
    """Return a ready-to-append language note for system prompts."""
    return f"\n\n[LANGUAGE: {lang_instruction()}]"
