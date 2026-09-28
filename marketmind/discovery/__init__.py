"""Data-first discovery: cold official series -> anomalies -> priced-in check (docs/S10_DESIGN.md §1, §2, §4).

- `series.py`   registry of cold official series (fetch -> [(date, value)], proxies, priors, keywords)
- `anomaly.py`  pure-code statistics and anomaly rules, news coverage
- `priced_in.py` pure-code "already priced in?" buckets per anomaly x proxy
- `runner.py`   `run_discovery()` writes data/discovery/<date>.json and exposes the
                candidate / prompt helpers the main pipeline uses

No LLM calls anywhere in this package: every number comes from code.
"""
