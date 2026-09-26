"""MarketMind health check — syntax, imports, config validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root


def check_syntax() -> int:
    import ast
    src_dir = Path(__file__).resolve().parents[1]
    errors = 0
    for py_file in src_dir.rglob("*.py"):
        try:
            # utf-8-sig: ~50 files start with a BOM, which Python's importer accepts
            ast.parse(py_file.read_text(encoding="utf-8-sig"))
            print(f"  OK  {py_file}")
        except SyntaxError as e:
            print(f"  FAIL {py_file}: {e}")
            errors += 1
    return errors


def check_imports() -> int:
    errors = 0
    modules = [
        "marketmind.config.settings",
        "marketmind.config.asset_universe",
        "marketmind.config.source_authority",
        "marketmind.gateway.async_client",
        "marketmind.gateway.token_budget",
        "marketmind.gateway.response_parser",
        "marketmind.pipeline.scout",
        "marketmind.pipeline.cache",
        "marketmind.pipeline.flash_preprocessor",
        "marketmind.pipeline.layer1_narrative",
        "marketmind.pipeline.layer2_fundamental",
        "marketmind.pipeline.layer3_technical",
        "marketmind.pipeline.red_team",
        "marketmind.pipeline.resonance",
        "marketmind.pipeline.decision",
        "marketmind.pipeline.position_patrol",
        "marketmind.integrity.watchdog",
        "marketmind.integrity.fact_checker",
        "marketmind.storage.archivist",
        "marketmind.storage.session",
        "marketmind.ui.async_bridge",
        "marketmind.ui.progress",
        "marketmind.ui.gate_panel",
        "marketmind.ui.dashboard_panel",
        "marketmind.ui.decision_card",
        "marketmind.ui.position_card",
        "marketmind.ui.pause_screen",
        "marketmind.ui.main_window",
        # Phase B: Shadow Ecosystem
        "marketmind.shadows.shadow_state",
        "marketmind.shadows.shadow_agent",
        "marketmind.shadows.shadow_mother",
        "marketmind.shadows.ranking_engine",
        "marketmind.shadows.expert_shadows",
        "marketmind.shadows.daredevil_shadows",
        "marketmind.shadows.catfish_agent",
        "marketmind.shadows.challenger_engine",
        "marketmind.shadows.knowledge_filter",
        "marketmind.shadows.paper_live_gap",
        "marketmind.shadows.emergency_quota",
        "marketmind.shadows.collusion_detector",
        "marketmind.shadows.cash_reframing",
        "marketmind.shadows.missed_path",
        "marketmind.ui.shadow_panel",
        "marketmind.ui.shadow_status_card",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"  OK  {mod}")
        except Exception as e:
            print(f"  FAIL {mod}: {e}")
            errors += 1
    return errors


def main():
    print("=== MarketMind Health Check ===\n")
    print("[SYNTAX]")
    syntax_errors = check_syntax()
    print(f"\nSyntax: {syntax_errors} errors")
    if syntax_errors == 0:
        print("\n[IMPORTS]")
        import_errors = check_imports()
        print(f"\nImports: {import_errors} errors")
    return 1 if syntax_errors else 0


if __name__ == "__main__":
    sys.exit(main())
