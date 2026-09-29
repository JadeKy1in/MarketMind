"""Shadow-ecosystem health monitor (docs/ECOSYSTEM_DESIGN.md): herding, output
diversity, source homogenisation, stagnation, zombies/integrity and whole-ecosystem
degradation, computed daily from the unified ledger. Monitoring only."""
from marketmind.ecosystem.runner import read_report, run_ecosystem

__all__ = ["read_report", "run_ecosystem"]
