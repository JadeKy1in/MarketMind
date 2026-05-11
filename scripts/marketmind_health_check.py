"""MarketMind health check — syntax, imports, config validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check_syntax() -> int:
    import ast
    src_dir = Path("projects/marketmind")
    errors = 0
    for py_file in src_dir.rglob("*.py"):
        try:
            ast.parse(py_file.read_text(encoding="utf-8"))
            print(f"  OK  {py_file}")
        except SyntaxError as e:
            print(f"  FAIL {py_file}: {e}")
            errors += 1
    return errors


def check_imports() -> int:
    errors = 0
    modules = [
        "projects.marketmind.config.settings",
        "projects.marketmind.config.asset_universe",
        "projects.marketmind.config.source_authority",
        "projects.marketmind.gateway.async_client",
        "projects.marketmind.gateway.token_budget",
        "projects.marketmind.gateway.response_parser",
        "projects.marketmind.pipeline.scout",
        "projects.marketmind.pipeline.cache",
        "projects.marketmind.pipeline.flash_preprocessor",
        "projects.marketmind.pipeline.layer1_narrative",
        "projects.marketmind.pipeline.layer2_fundamental",
        "projects.marketmind.pipeline.layer3_technical",
        "projects.marketmind.pipeline.red_team",
        "projects.marketmind.pipeline.resonance",
        "projects.marketmind.pipeline.decision",
        "projects.marketmind.pipeline.position_patrol",
        "projects.marketmind.integrity.watchdog",
        "projects.marketmind.integrity.fact_checker",
        "projects.marketmind.storage.archivist",
        "projects.marketmind.storage.session",
        "projects.marketmind.ui.async_bridge",
        "projects.marketmind.ui.progress",
        "projects.marketmind.ui.gate_panel",
        "projects.marketmind.ui.dashboard_panel",
        "projects.marketmind.ui.decision_card",
        "projects.marketmind.ui.position_card",
        "projects.marketmind.ui.pause_screen",
        "projects.marketmind.ui.main_window",
        # Phase B: Shadow Ecosystem
        "projects.marketmind.shadows.shadow_state",
        "projects.marketmind.shadows.shadow_agent",
        "projects.marketmind.shadows.shadow_mother",
        "projects.marketmind.shadows.ranking_engine",
        "projects.marketmind.shadows.expert_shadows",
        "projects.marketmind.shadows.daredevil_shadows",
        "projects.marketmind.shadows.catfish_agent",
        "projects.marketmind.shadows.challenger_engine",
        "projects.marketmind.shadows.knowledge_filter",
        "projects.marketmind.shadows.paper_live_gap",
        "projects.marketmind.shadows.emergency_quota",
        "projects.marketmind.shadows.collusion_detector",
        "projects.marketmind.shadows.cash_reframing",
        "projects.marketmind.shadows.missed_path",
        "projects.marketmind.ui.shadow_panel",
        "projects.marketmind.ui.shadow_status_card",
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
