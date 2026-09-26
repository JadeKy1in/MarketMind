"""L1 ELITE Shadow Query — handle 'elite <domain>' user commands.

Extracted from layer1_interactive.py per modular architecture rules (§3.1).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.layer1_interactive import InteractiveState


async def handle_elite_query(user_text: str, state: "InteractiveState") -> None:
    """Query ELITE shadow opinions. Parses 'elite <domain>' or 'elite <name>'."""
    if state.elite_registry is None:
        print("\n[ELITE] 影子系统未初始化。请等待影子分析完成后重试。")
        return

    query = user_text.replace("elite", "").strip()
    if not query:
        query = user_text.replace("影子", "").strip()

    if not query:
        domains = list(state.elite_registry.DOMAIN_KEYWORDS.keys())
        print(f"\n[ELITE] 可用领域: {', '.join(domains[:10])}")
        print("输入 'elite <领域>' 查询影子意见（如 'elite gold'）")
        return

    matched_domains = state.elite_registry.detect_domain_trigger(query)
    if not matched_domains:
        domain_list = ", ".join(list(state.elite_registry.DOMAIN_KEYWORDS.keys())[:10])
        print(f"\n[ELITE] 未识别领域 '{query}'。可用领域: {domain_list}")
        return

    domain = matched_domains[0]
    contributions = getattr(state.elite_registry, '_contributions', {})

    matched = []
    for sid, contrib in contributions.items():
        if contrib.domain == domain or domain in contrib.domain:
            matched.append(contrib)

    if not matched:
        print(f"\n[ELITE] {domain} 领域影子正在分析中（预计30-60秒）。请稍后再试。")
        return

    print(f"\n┌─ ELITE 影子 — {domain} 领域 ─────────────────┐")
    for contrib in matched[:3]:
        name = getattr(contrib, 'shadow_name', 'unknown')
        text = getattr(contrib, 'opinion', '')[:300]
        print(f"│ [{name}] {text}")
    print(f"└{'─'*46}┘")
    print("（以上为影子独立分析意见，仅供参考）")
