#!/usr/bin/env python3
"""
Frontload Passthrough Fast-Path Gate

Design (from user_proxy_design.json, lines 161-162):
  - `should_frontload(user_first_message: str) -> bool`
  - Returns False (skip frontload) if the message is:
      - Single-file, single-operation
      - No new module creation
      - No architecture keywords (refactor, extract, redesign, restructure)
      - No API surface changes
      - No config changes
  - Returns True for anything else
  - Simple keyword + pattern matching, no LLM needed

Usage:
    python frontload_gate.py "fix typo in README.md"
    python frontload_gate.py "refactor the entire pipeline module"

No external dependencies beyond Python stdlib.
"""

import argparse
import re
import sys

# ──────────────────────────────────────────────────────────────────────────────
# Architecture / refactoring keywords — if any of these appear, frontload is
# triggered because the operation may have broad impact.
# ──────────────────────────────────────────────────────────────────────────────
ARCHITECTURE_KEYWORDS = [
    "refactor",
    "extract",
    "redesign",
    "restructure",
    "reorganize",
    "decouple",
    "split.*module",
    "merge.*module",
    "introduce pattern",
    "abstract",
    "rewrite",
    "migrate",
    "rearchitect",
    "layered architecture",
    "plugin",
    "middleware",
    "pipeline (design|layer|step|stage|component|overhaul)",
    "pipeline arch",
    "data pipeline",
    "new module",
    "create module",
    "add module",
]

# ──────────────────────────────────────────────────────────────────────────────
# API surface change indicators
# ──────────────────────────────────────────────────────────────────────────────
API_SURFACE_KEYWORDS = [
    "api endpoint",
    "api route",
    "api (surface|response|contract|change|version|schema)",
    "add.*endpoint",
    "remove.*endpoint",
    "modify.*(endpoint|handler|route)",
    "add.*route",
    "new.*route",
    "route.*(handler|definition|config)",
    "handler",
    "controller",
    "middleware",
    "request.*(format|schema|structure|body|header)",
    "response.*(format|schema|structure|body|header)",
    "serialize",
    "deserialize",
    "schema",
    "public method",
    "public function",
    "export",
    "interface",
    "signature",
    "breaking change",
    "deprecat",
    "contract",
    "modify.*(interface|signature|schema|contract)",
    "change.*signature",
]

# ──────────────────────────────────────────────────────────────────────────────
# Config change indicators
# ──────────────────────────────────────────────────────────────────────────────
CONFIG_KEYWORDS = [
    "config",
    "settings",
    "dotenv",
    "\\.env",
    "environment variable",
    "env var",
    "env file",
    "secret",
    "credential",
    "token",
    "api key",
    "apikey",
    "feature flag",
    "toggle",
    "deploy",
    "ci/cd",
    "pipeline config",
    "docker",
    "compose",
    "k8s",
    "kubernetes",
    "terraform",
    "helm",
    "makefile",
    "build",
    "package\\.json",
    "setup\\.py",
    "pyproject\\.toml",
    "cargo\\.toml",
    "dependency",
    "pin",
    "lockfile",
    "\\.yaml$",
    "\\.yml$",
    "\\.toml$",
    "\\.json$",
]

# ──────────────────────────────────────────────────────────────────────────────
# Single-file, single-operation pattern detectors
# ──────────────────────────────────────────────────────────────────────────────
# These patterns suggest the user wants something trivial — a single file,
# a single operation, no cascading effects.

SINGLE_OPERATION_PATTERNS = [
    r"\bfix\s+(a\s+)?typo\b",
    r"\badd\s+(a\s+)?comment\b",
    r"\brename\s+(?!.*\b(module|package|directory|folder|project)\b)",
    r"\bchange\s+(the\s+)?text\b",
    r"\bupdate\s+(a\s+)?docstring\b",
    r"\bformat\s+(a\s+)?file\b",
    r"\blint\b",
    r"\bremove\s+(a\s+)?(debug\s+)?print\b",
    r"\bdelete\s+(a\s+)?(comment|debug)\b",
    r"\bfix\s+import\b",
    r"\bsort\s+imports\b",
    r"\badd\s+type\s+hint\b",
    r"\bbump\s+version\b",
    r"\bupdate\s+changelog\b",
    r"\bupdate\s+readme\b",
    r"\bcorrect\s+spelling\b",
    r"\bs/[\w.]+/[\w.]*/",  # sed-style inline replacement
]

# --------------------------------------------------------------------------
# Also check: does the message reference exactly one file?
# A pattern like "fix typo in src/foo/bar.py" suggests single file.
FILE_EXTENSIONS = r"(?:py|js|ts|tsx|jsx|rs|go|java|rb|php|c|cpp|h|hpp|css|scss|html|md|txt|yml|yaml|toml|json|xml|ini|cfg|conf)"

# Pattern A: explicit "in <filepath>" or "for <filepath>"
EXPLICIT_FILE_PATTERNS = [
    rf"\bin\s+[\w/\-.@]+\.{FILE_EXTENSIONS}\b",
    rf"\bfor\s+[\w/\-.@]+\.{FILE_EXTENSIONS}\b",
]

# Pattern B: bare filename.ext appearing as a standalone token
# (e.g. "fix typos in README.md and main.py" — "main.py" has no "in" before it)
BARE_FILE_PATTERNS = [
    rf"[\w/\-@]+\.{FILE_EXTENSIONS}\b",
]

# --------------------------------------------------------------------------
# File creation indicators — suggest new module or new file being born
NEW_MODULE_CREATION_KEYWORDS = [
    "create",
    "new file",
    "new module",
    "scaffold",
    "generate",
    "add file",
    "add module",
    "write.*script",
    "build.*new",
]


def _normalize(message):
    """Lowercase and strip for keyword matching."""
    return (message or "").strip().lower()


def _has_keyword(message, keywords):
    """Return True if any keyword regex matches the message."""
    msg = _normalize(message)
    for kw in keywords:
        try:
            if re.search(kw, msg):
                return True
        except re.error:
            # Fallback: literal substring match
            if kw.lower() in msg:
                return True
    return False


def _count_file_references(message):
    """Count distinct file references in the message.

    Detects two forms:
      A. Explicit: "in foo.py", "for bar.rs"
      B. Bare: standalone filename.ext tokens (e.g. "main.py", "config.yaml")

    Returns count of unique filenames found. Normalizes "in foo.py" → "foo.py"
    so EXPLICIT and BARE matches deduplicate correctly.
    """
    msg = _normalize(message)
    found = set()

    # Pattern to strip leading prepositions from EXPLICIT matches
    _strip_re = re.compile(r"^(in|for|at|from|to|of)\s+", re.IGNORECASE)

    for pattern in EXPLICIT_FILE_PATTERNS:
        for m in re.finditer(pattern, msg):
            raw = m.group(0)
            found.add(_strip_re.sub("", raw))

    for pattern in BARE_FILE_PATTERNS:
        for m in re.finditer(pattern, msg):
            found.add(m.group(0))

    return len(found)


def _has_new_module_creation(message):
    """Check if message indicates creating a new module/file."""
    return _has_keyword(message, NEW_MODULE_CREATION_KEYWORDS)


def _has_architecture_keywords(message):
    """Check for architecture/refactoring trigger words."""
    return _has_keyword(message, ARCHITECTURE_KEYWORDS)


def _has_api_surface_changes(message):
    """Check for API surface change indicators."""
    return _has_keyword(message, API_SURFACE_KEYWORDS)


def _has_config_changes(message):
    """Check for config change indicators."""
    return _has_keyword(message, CONFIG_KEYWORDS)


def _is_single_operation(message):
    """Check if the message matches a single-operation pattern."""
    return _has_keyword(message, SINGLE_OPERATION_PATTERNS)


def should_frontload(user_first_message):
    """Determine whether the User Proxy Agent should perform frontloading.

    Args:
        user_first_message: The user's first message in the session.

    Returns:
        True  — frontload (the message warrants broader context + architecture
                consideration before the proxy acts).
        False — passthrough fast-path (trivial, single-file, safe to skip
                frontloading overhead).
    """
    msg = _normalize(user_first_message)

    if not msg:
        # Empty message → default to frontload (safer)
        return True

    # ── Step 1: Check for high-signal triggers (any one → frontload) ───────

    if _has_architecture_keywords(msg):
        return True

    if _has_new_module_creation(msg):
        return True

    if _has_api_surface_changes(msg):
        return True

    if _has_config_changes(msg):
        return True

    # ── Step 2: Check for multi-file scope signals (even without explicit
    #            file references) ───────────────────────────────────────────

    multi_file_words = ["all", "every", "across", "throughout", "project", "repo"]
    if any(w in msg for w in multi_file_words):
        return True

    # ── Step 3: Check if this is purely a single-file, single-operation ────

    file_count = _count_file_references(msg)

    if file_count == 0:
        # No file reference at all — could be a question, or a broad request.
        # If it matches no single-operation patterns either, frontload.
        if not _is_single_operation(msg):
            return True
        # Even without an explicit file, single-operation keywords suggest
        # a targeted, low-risk request.
        return False

    if file_count == 1:
        # One file reference + single operation → fast-path
        if _is_single_operation(msg):
            return False
        # One file reference but no single-op pattern → might still be simple.
        # (Multi-file scope words already checked above.)
        return False

    # Multiple file references → frontload
    return True


# ===========================================================================
#  CLI
# ===========================================================================

def _color_result(result, message):
    """Format a terminal-friendly result line."""
    label = "FRONTLOAD" if result else "FAST-PATH"
    status = "YES" if result else "NO"
    print(f"[{label}] frontload={status}  |  \"{message}\"")


def main():
    parser = argparse.ArgumentParser(
        prog="frontload_gate",
        description="Frontload gate for User Proxy Agent — "
                    "decides whether to perform frontloading based on "
                    "the user's first message.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0 — fast-path (no frontload needed)
  1 — frontload (message warrants broader context)
  2 — empty input

Examples:
  python frontload_gate.py "fix typo in README.md"
  python frontload_gate.py "refactor the pipeline layer"
  python frontload_gate.py --test          # run self-tests
        """,
    )
    parser.add_argument(
        "message", nargs="*", default=None,
        help="The user's first message (can be quoted)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run self-tests to verify gate logic",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only output the boolean result (no formatting)",
    )
    args = parser.parse_args()

    # ── Self-test mode ─────────────────────────────────────────────────────
    if args.test:
        _run_self_tests()
        return

    # ── Normal mode ────────────────────────────────────────────────────────
    message = " ".join(args.message) if args.message else ""
    result = should_frontload(message)

    if args.quiet:
        print("true" if result else "false")
    else:
        _color_result(result, message)

    sys.exit(1 if result else 0)


# ===========================================================================
#  Self-tests
# ===========================================================================

def _run_self_tests():
    """Internal self-tests covering all decision branches."""
    test_cases = [
        # ── Fast-path cases (should_frontload → False) ─────────────────
        # Single file, single operation
        ("fix typo in README.md", False),
        ("fix a typo in src/main.py", False),
        ("add comment to utils/helpers.py", False),
        ("rename getData to get_data in models.py", False),
        ("update docstring in pipeline/gate1.py", False),
        ("remove debug print from app.py", False),
        ("sort imports in all files", True),  # "all" → multi-file scope
        ("add type hint to process.py", False),
        ("correct spelling in docs/guide.md", False),
        ("delete a debug comment from api/routes.py", False),
        ("change the text on the homepage", False),

        # ── Frontload cases (should_frontload → True) ──────────────────
        # Architecture keywords
        ("refactor the pipeline module", True),
        ("extract the parser from gate1.py", True),
        ("redesign the shadow ranking system", True),
        ("restructure the entire project layout", True),
        ("decouple the database layer", True),
        ("rewrite the authentication middleware", True),
        ("abstract away the HTTP client", True),

        # New module creation
        ("create a new module for caching", True),
        ("add a new file for types", True),
        ("scaffold the API tests", True),
        ("write a script to migrate data", True),
        ("build a new notification system", True),

        # API surface changes
        ("add an endpoint for user profiles", True),
        ("change the API response format", True),
        ("deprecate the old route handler", True),
        ("modify the request schema", True),
        ("breaking change to the public interface", True),

        # Config changes
        ("update the config file", True),
        ("change settings.py", True),
        ("add a new environment variable", True),
        ("pin httpx to version 0.28", True),
        ("update package.json dependencies", True),
        ("modify the docker compose file", True),
        ("add a feature flag for dark mode", True),
        ("change the CI/CD pipeline", True),

        # Multiple file references
        ("fix typos in README.md and src/main.py", True),

        # Ambiguous / no file ref, no single-op pattern
        ("analyze the performance", True),
        ("review the codebase", True),

        # Multi-file scope words
        ("fix typo across all python files", True),

        # Edge cases
        ("", True),   # empty → frontload (safe default)
        ("   ", True),  # whitespace → frontload
    ]

    passed = 0
    failed = 0

    for i, (message, expected) in enumerate(test_cases):
        result = should_frontload(message)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] test {i+1:02d}: expected={expected} got={result}  |  \"{message}\"")

    print()
    print(f"{passed} passed, {failed} failed out of {len(test_cases)} tests.")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
