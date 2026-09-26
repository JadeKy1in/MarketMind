"""Source independence graph for cross-source corroboration.

Groups sources that share ownership/parent company, so the corroboration
engine can count them as ONE independent source rather than many.

Red Team finding C3: Without this, a Sybil attack where one parent company
controls N sources can fabricate "consensus" at N independent votes.
"""

# Groups of sources that share ownership/parent company.
# Sources in the same group count as ONE independent source for corroboration.
SOURCE_OWNERSHIP_GROUPS: dict[str, list[str]] = {
    "dow_jones": ["MarketWatch"],
    "google_news_proxies": [
        "Caixin (via Google News)", "PBOC (via Google News)",
        "China Economy (via Google News)", "Euronews (via Google News)",
        "Eurostat (via Google News)", "India RBI (via Google News)",
        "South Africa SARB (via Google News)", "World Bank (via Google News)",
        "IMF (via Google News)", "OPEC Oil (via Google News)",
        "ECB (via Google News)", "Precious Metals (via Google News)",
        "Agriculture (via Google News)", "Natural Gas (via Google News)",
        "Healthcare (via Google News)", "Crypto (via Google News)",
        "Nikkei Asia",
    ],
    "ec_official": ["EC Press Corner"],
}


def _get_group(name: str) -> str | None:
    """Return the group key a source belongs to, or None if independent."""
    for group_key, members in SOURCE_OWNERSHIP_GROUPS.items():
        if name in members:
            return group_key
    return None


def count_independent_sources(source_names: list[str]) -> int:
    """Count how many independent ownership groups are represented.

    Sources within the same ownership group are counted as ONE.
    Sources not in any group are each counted as independent.

    Args:
        source_names: List of source name strings (e.g. ["MarketWatch", "Reuters"])

    Returns:
        Number of independent source groups represented.
    """
    groups_seen: set[str] = set()
    independent_count = 0

    for name in source_names:
        group = _get_group(name)
        if group is not None:
            groups_seen.add(group)
        else:
            independent_count += 1

    return independent_count + len(groups_seen)


def are_sources_independent(name_a: str, name_b: str) -> bool:
    """Check if two sources are from different ownership groups.

    Two sources are independent if they belong to different groups
    or if at least one is unaffiliated (not in any group).

    Args:
        name_a: First source name
        name_b: Second source name

    Returns:
        True if the sources are independent, False if they share ownership.
    """
    group_a = _get_group(name_a)
    group_b = _get_group(name_b)

    # Both in the same group → not independent
    if group_a is not None and group_a == group_b:
        return False

    # Different groups, or one/both unaffiliated → independent
    return True
