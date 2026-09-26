"""Data integrity verification system (Law 7 compliance)."""
from marketmind.integrity.watchdog import (
    NumericClaim, AgentIntegrityScore, inject_m1_protocol,
    extract_claims_m2, verify_claim_m3, update_score_m4, evaluate_strikes,
)
from marketmind.integrity.fact_checker import FactCheckReport, run_fact_check
