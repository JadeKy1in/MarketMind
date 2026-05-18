# Red Team Audit: Gate 1 Interaction Design — Architecture & Integration

**Date**: 2026-05-18
**Auditor**: Red Team (Architecture + Integration focus)
**Plan audited**: `docs/superpowers/plans/2026-05-18-gate1-interaction-design.md`
**Referenced files**:
- `projects/marketmind/app.py` (465 lines) — current pipeline, `run_daily()` + `run_interactive()`
- `projects/marketmind/pipeline-manifest.yaml` — authoritative pipeline (SINGLE SOURCE OF TRUTH)
- `projects/marketmind/storage/archivist.py` (138 lines) — JSON archive + FTS5
- `projects/marketmind/storage/session.py` (113 lines) — checkpoint persistence
- `projects/marketmind/ui/gate_panel.py` (74 lines) — existing GUI gate panel
- `projects/marketmind/ui/main_window.py` — existing GUI Gate 1 placeholder
- `projects/marketmind/ui/async_bridge.py` — GUI async bridge pattern
- `projects/marketmind/shadows/shadow_mother.py` — missed_path integration
- `projects/marketmind/shadows/missed_path.py` — counterfactual tracking

---

## Executive Summary

**Verdict: CRITICAL** — 3 CRITICAL issues must be resolved before implementation can begin. 4 HIGH, 4 MEDIUM, and 3 LOW issues identified.

The plan describes a well-researched user interaction flow (反苏格拉底, 80/10/10, hypothesis cards, Parking Lot pivot) backed by four solid research documents. However, the plan is a **UX design document**, not an **implementation plan**. It maps neatly to how users should experience Gate 1 but does not map to how the software must change to support that experience. The three CRITICAL findings are fundamental gaps between the UX vision and the current codebase architecture. Implementation as described (~30 lines in app.py + 3 new modules) is not possible; resolving the CRITICAL issues requires an architectural decision — choosing between a headless pipeline extension, a CLI interactive path, or a GUI interactive path — followed by a revised implementation plan.

---

## Findings

### CRITICAL

#### C1. Pipeline Insertion Point Does Not Exist — Headless Architecture Gap

**Severity**: CRITICAL
**Filed against**: Plan Section 一 (Gate 1位置), Section 六 (实施步骤, Step 5)

The plan proposes inserting Gate 1 "between Stage 3 and Stage 4" in `run_daily()`. This is architecturally impossible in the current codebase.

**Evidence**:
- `app.py:run_daily()` (lines 23-321) is a single `async` function that runs Stage 0 through Stage 10 in sequence without any checkpoint, pause, or yield point. It is invoked via `asyncio.run(run_daily(...))` from `main()` (line 460).
- Stage 3 (HVR investigation, lines 140-168) produces `hypotheses`, `actionable`, `monitor`, `priced_in` — then immediately continues to Stage 4 (L1 narrative, line 171).
- There is no `await` on user input, no checkpoint save/load, and no mechanism to suspend and resume. The function runs from start to finish in a single `asyncio.run()` call.
- `run_daily()` is designed for **headless/batch** execution: print progress, write archive, exit. The `--mode daily` CLI flag maps directly to this.

**What would actually be needed**:
1. Split `run_daily()` into `run_stages_0_3()` and `run_stages_4_10()` — two separate `async` functions.
2. `run_stages_0_3()` must save ALL intermediate state (news_items, triage_results, hypotheses, actionable, monitor, priced_in) as JSON to a checkpoint file.
3. A new `run_gate1()` function loads the checkpoint, runs the interactive dialogue, writes the decision, and saves updated session state.
4. `run_stages_4_10()` loads the checkpoint + gate1 decision, then continues.
5. `main()` needs a new mode (e.g., `--mode gate1` or `--mode full-with-gates`) that orchestrates these three steps.

**The plan's estimate of "~30 lines in app.py" is wrong by an order of magnitude.** The actual integration requires ~150-200 lines of orchestration code plus a new CLI entry point.

**Recommendation**: The plan must specify which of three integration paths is chosen:
- **Path A (Two-phase CLI)**: `python app.py --mode pre-gate1` (runs Stages 0-3, saves checkpoint, exits) then `python app.py --mode gate1` (loads checkpoint, runs Gate 1 dialogue, saves decision). Stages 4-10 run after Gate 1 confirms. This preserves `run_daily()` as headless and adds new modes.
- **Path B (Single interactive session)**: A new `run_full_interactive_session()` that wraps the full pipeline with a Gate 1 interaction in the middle. Uses async I/O for user input (e.g., `asyncio.to_thread(sys.stdin.readline)`). This is closer to what `run_interactive()` attempts but with a completely rearchitected flow.
- **Path C (GUI-only)**: Gate 1 is only available through the GUI (`main_window.py` already has `_run_gate1()` as a placeholder). The CLI `--mode daily` remains headless. The plan would then be modifying `main_window._run_gate1()` to wire the real pipeline.

#### C2. Async/Sync Boundary — Blocking `input()` Inside `async` Pipeline

**Severity**: CRITICAL
**Filed against**: Plan Section 二 (对话流程), Section 五 (新增模块 — gate1_interaction.py)

Gate 1 is an interactive dialogue that waits for user keystrokes. The plan provides zero specification for how this synchronous blocking I/O integrates with an async pipeline.

**Evidence**:
- `gate1_interaction.py` is described as a "对话循环: 呈现卡片→引导问题→用户选择→归档". The natural implementation is a `while` loop calling `input()`.
- `input()` blocks the calling **thread**. In an `async` function running on an event loop, blocking the thread freezes ALL other coroutines — including Shadow ecosystem analysis, background scheduler ticks, and any parallel HTTP requests.
- The existing `run_interactive()` (lines 335-373) demonstrates the problem: it defines `cli_handler` as `lambda prompt: input()` and calls it from within async functions. This works only because nothing else runs concurrently during interactive mode. But if shadows are active (they run in Stage 0 and Stage 5 in `run_daily()`), a blocking `input()` would freeze shadow analysis.
- `app.py:run_daily()` runs shadow initialization (Stage 0, lines 48-90) and shadow analysis (Stage 6, lines 232-244). If Gate 1 is inserted at Stage 3/4 boundary, shadow initialization has already happened. Any active background scheduler threads or pending async tasks would be affected.

**What is needed but unspecified**:
1. For CLI: Use `asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)` to make `input()` non-blocking to the event loop. Or use `asyncio.to_thread()` (Python 3.9+).
2. For GUI: The existing `AsyncBridge` pattern (daemon thread + queue + `root.after()` polling) already solves this — but the plan doesn't mention the GUI at all.
3. Specification of WHAT runs concurrently with Gate 1. If nothing runs concurrently (pipeline is suspended during interaction), the synchronous `input()` is acceptable even if technically impure — but this must be **explicitly stated** as a design constraint.

**Recommendation**: The plan must specify the concurrency model. If the pipeline suspends entirely during Gate 1 (no shadows, no background tasks, no HTTP), state this explicitly and document that `input()` blocks the event loop by design. If concurrent tasks must continue, specify the `asyncio.to_thread()` wrapper and test with active shadows.

#### C3. Pipeline Numbering Mismatch — Plan vs. Authoritative Manifest

**Severity**: CRITICAL
**Filed against**: Plan Section 一 (Gate 1位置)

The plan uses stage numbers that match `app.py`'s inline comments but conflict with `pipeline-manifest.yaml`, which is declared the "SINGLE SOURCE OF TRUTH."

**Evidence**:

| Plan Reference | app.py Comment | pipeline-manifest.yaml ID |
|---|---|---|
| Stage 1-3 (pre-Gate 1) | Scout, Flash, HVR | `stage_1_scout`, `stage_2_flash`, **no investigation stage** |
| Stage 4 (post-Gate 1) | L1 Narrative | `stage_3_layer1` |
| Stage 5 (post-Gate 1) | L2 + L3 | `stage_4_layer2_layer3` |
| Stage 8 (post-Gate 1) | Decision | `stage_8_decision` |

The investigation loop (`pipeline/investigation_loop.py`) has NO corresponding stage in the manifest. The manifest jumps from `stage_2_flash` to `stage_3_layer1`. Meanwhile, the plan treats the investigation loop as Stage 3 and L1 as Stage 4.

**Impact**: Any engineer implementing Gate 1 who consults the manifest (as they should — it is the authoritative document) would place Gate 1 between `stage_3_layer1` and `stage_4_layer2_layer3` — which is AFTER L1, not before it. This would produce a completely different pipeline flow than the plan intends.

**Recommendation**: The plan MUST reference `pipeline-manifest.yaml` stage IDs, not `app.py` inline comments. Either:
- Update the manifest to include an `stage_2b_investigation` entry, then reference `stage_2b` and `stage_3` in the plan; OR
- Insert Gate 1 after the stage that produces the data Gate 1 needs (currently the investigation loop) and reference that manifest stage ID.

---

### HIGH

#### H1. HypothesisResult Data Model Gap — Card Fields Missing

**Severity**: HIGH
**Filed against**: Plan Section 二 (假设卡片), Section 五 (hypothesis_card.py)

The plan's hypothesis card template (Section 二, Step 2) requires specific fields that do not exist on `HypothesisResult` (defined in `pipeline/investigation_loop.py:69-92`).

**Mapping of card fields to data model**:

| Card Field | Required | Available on HypothesisResult? |
|---|---|---|
| 方向 (direction) | Yes | **NO** — `HypothesisResult` has `hypothesis: str` (free text), not a structured direction label |
| 置信度 (confidence) | Yes | Yes — `confidence: float` |
| 核心逻辑 (core logic) | Yes | Partial — `refined_hypothesis: str` could serve, but is free text |
| Layer1 市场定价 (market pricing) | Yes | **NO** — `HypothesisResult` has `expectation_gap: float` but not the narrative description "利率期货仅定价20%加息概率" |
| Layer2 基本面 (fundamentals) | Yes | **NO** — Stored inside `verification: VerificationResult` (opaque type from `verification_chain.py`) |
| Layer3 多源 (multi-source) | Yes | **NO** — Same as above |
| Layer4 历史 (historical) | Yes | **NO** — Same as above |
| 反对意见 (bear case) | Yes | Yes — `bear_case: str` |
| 看空置信度 (bear confidence) | Yes | Yes — `bear_case_confidence: float` |
| 风险等级 (risk level) | Yes | **NO** — Not in the data model at all |
| 时间窗口 (time window) | Yes | **NO** — Not in the data model at all |

**6 of 11 required card fields have no corresponding data in HypothesisResult.** The plan assumes `hypothesis_card.py` can "generate hypothesis cards from HVR output" but the HVR output is structurally incomplete for this purpose.

**Evidence**: `pipeline/investigation_loop.py:84-92` defines 10 fields on `HypothesisResult` — none include risk level, time window, structured direction labels, or the 4-layer verification breakdown as separate text fields. The `VerificationResult` type (from `pipeline/verification_chain.py`) was not reviewed as part of this audit but is the internal container for layers — `hypothesis_card.py` would need to import it and destructure its fields.

**Recommendation**: Before implementing `hypothesis_card.py`, audit `VerificationResult` to confirm it exposes layer breakdowns as accessible fields. If it does not, either:
- Extend `HypothesisResult` to include the missing fields; OR
- Have `hypothesis_card.py` invoke the Pro LLM to generate missing fields from the raw hypothesis text (adds latency + token cost).

#### H2. Write Non-Atomic — Crash Survival Is Not Guaranteed

**Severity**: HIGH
**Filed against**: Plan Section 三 (白盒归档 — gate1_decision.json), Section 六 (Checkpoint Persistence)

The plan states Gate 1 decision must survive crashes. The current archivist does not provide atomic writes.

**Evidence**: `storage/archivist.py:47-52`:
```python
def save_json(self, subdir: str, filename: str, data: Any) -> Path:
    dir_path = self.today_path() / subdir
    dir_path.mkdir(parents=True, exist_ok=True)
    filepath = dir_path / f"{filename}.json"
    filepath.write_text(json.dumps(data, ...), encoding="utf-8")
    return filepath
```

`Path.write_text()` opens the file and writes directly — it does NOT write to a temp file and rename. If the OS or Python process crashes mid-write, the file will contain a partial/invalid JSON document. On next load, `json.loads()` will raise `json.JSONDecodeError`, and the session state is lost.

**Contrast with `storage/session.py:50-54`** — same problem:
```python
filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
```

**What is needed**: Atomic write pattern:
```python
tmp = filepath.with_suffix('.tmp')
tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
tmp.replace(filepath)  # Atomic on POSIX + NTFS
```

**Recommendation**: Fix `archivist.save_json()` AND `SessionManager.save()` to use atomic writes before implementing Gate 1. The plan should explicitly require this as a dependency (Step 0 prerequisite).

#### H3. Archivist `ensure_dirs()` Does Not Create `gates/` Directory

**Severity**: HIGH
**Filed against**: Plan Section 三 (归档结构), Section 五 (gate_archiver.py)

The plan's archive structure adds a `gates/` subdirectory under `data/archive/YYYY/MM/DD/`. The existing archivist does not create this directory.

**Evidence**: `storage/archivist.py:42-45`:
```python
def ensure_dirs(self) -> Path:
    for sub in ("raw", "analysis", "decisions", "review"):
        (self.today_path() / sub).mkdir(parents=True, exist_ok=True)
    return self.today_path()
```

`gates/` is not in the list. If `gate_archiver.py` calls `archivist.save_json("gates", ...)`, the `save_json` method will create the directory (line 49: `dir_path.mkdir(parents=True, exist_ok=True)`) — so it works technically, but `gates/` is never initialized at pipeline start.

**The real issue**: `ensure_dirs()` is called once in `run_daily()` (line 33). If `gate_archiver.py` creates `gates/` independently (without calling `ensure_dirs()`), the directory structure has two authorities — the archivist for 4 subdirs, and gate_archiver for 1. If `ensure_dirs()` is later refactored, the `gates/` directory might silently break.

**Recommendation**: Add `"gates"` to the `ensure_dirs()` tuple. This makes directory structure a single concern.

#### H4. No Integration with Existing Session Checkpoint System

**Severity**: HIGH
**Filed against**: Plan Section 三 (归档), Section 六 (实施步骤)

The plan proposes `gate1_decision.json` as the checkpoint artifact but never references `storage/session.py`, which already has a mature checkpoint system with `SessionState`, `GateCheckpoint`, `save()`, `load()`, and `list_sessions()`.

**Evidence**: `storage/session.py`:
- `GateCheckpoint(gate_number=1, completed=True, data={"selected_direction": "tech"})` — exactly the structure Gate 1 needs.
- `SessionState.mode` — has `full | quick | catchup` (Section 四 of the plan).
- `SessionManager.save()` / `SessionManager.load()` — full serialization with round-trip test coverage (`tests/test_storage/test_session.py`).
- `SessionState.progress_summary` — already generates human-readable gate progress.

**The plan invents a new `gate1_decision.json` file when a perfectly suitable checkpoint mechanism already exists.** This creates two parallel checkpoint systems — one for session state, one for gate decisions — that must be kept in sync.

**Recommendation**: Gate 1 should use the existing `SessionManager` for checkpoint persistence. `gate1_decision.json` should be the **data** field inside `GateCheckpoint.data`, not a standalone file. This gives crash survival, session listing, and progress summary for free.

---

### MEDIUM

#### M1. Module Placement Violates Directory Semantics

**Severity**: MEDIUM
**Filed against**: Plan Section 五 (新增模块 — ui/gate1_interaction.py)

The plan places `gate1_interaction.py` in `ui/`. All existing `ui/` modules are CustomTkinter GUI widgets:
- `main_window.py`, `dashboard_panel.py`, `shadow_panel.py`, `shadow_status_card.py`, `shadow_charts.py`, `decision_card.py`, `position_card.py`, `gate_panel.py`, `pause_screen.py`, `async_bridge.py`, `progress.py`

`gate1_interaction.py` is described as a CLI dialogue loop (呈现卡片→引导问题→用户选择→归档). This is NOT a GUI widget — it is a pipeline stage that happens to involve user I/O. It belongs in `pipeline/`.

**Evidence**: `ui/gate_panel.py` already exists as the GUI counterpart. If `gate1_interaction.py` is placed in `ui/`, two completely different Gate 1 implementations (CLI and GUI) would coexist in the same directory with different architectural patterns — guaranteed confusion.

**Recommendation**: Place `gate1_interaction.py` in `pipeline/` (alongside `layer1_interactive.py`, `l2_interactive.py`, etc.) or create a new `interaction/` package. Reserve `ui/` for GUI widgets only.

#### M2. app.py Exceeds Entry-Point Hard Ceiling — Grandfather Clause Blocks New Feature Work

**Severity**: MEDIUM
**Filed against**: Plan Section 五 (修改 app.py)

`app.py` is 465 lines. Per modular architecture rules (root CLAUDE.md §3.1), CLI entry points have a soft threshold of 100 lines and a hard ceiling of 150 lines. `app.py` is covered by the grandfather clause (listed as 971 lines at May 15 baseline, now 465), which allows "extraction-only changes and bug fixes" but prohibits "new feature work."

**The plan's "~30 lines to insert Gate 1" is new feature work**, not extraction or bug fix. Per §3.1, any new feature work on grandfathered files requires extraction first.

**What must happen before Gate 1 can be added to app.py**:
1. Extract `BacktestRunner` integration (lines 389-418) into `pipeline/backtest_entry.py`.
2. Extract `run_gui()` (lines 324-332) into `ui/launcher.py`.
3. Extract `run_interactive()` (lines 335-373) into `pipeline/orchestration.py`.
4. After extraction, `app.py` should be ~150-200 lines (still over the hard ceiling, but within acceptable range for its role as a multi-mode dispatcher).

**Recommendation**: The plan should include an extraction step before Step 5 (accessing app.py). The estimated 30 lines of integration needs to acknowledge the prior extraction work.

#### M3. Mode Detection Algorithm Is Undefined

**Severity**: MEDIUM
**Filed against**: Plan Section 四 (三种会话模式)

The plan defines three modes (Full, Quick, Catchup) but provides zero specification for how the code detects which mode to use.

**Evidence**: Section 四 describes what each mode DOES but not how it is SELECTED:
- Full: "All hypothesis cards + <=3 guided questions"
- Quick: "Only highest confidence direction + 1 question"  
- Catchup: "Skip Gate 1, show N-day change summary"

The plan does not specify:
1. Is mode selected by user? (CLI flag? config? environment variable?)
2. Is mode auto-detected? (check `SessionManager.list_sessions()` for days since last session?)
3. What is the threshold for Catchup? ("N天未登录" — what is N? 3 days? 7 days?)
4. How does Catchup mode determine "N-day change summary"? Which data does it need?
5. Does Quick mode preserve the full analysis for later review or discard it?

**`session.py` already has `SessionState.mode` with valid values `full | quick | catchup` — but nothing sets it.** No code path populates this field. No CLI argument accepts `--mode quick`.

**Recommendation**: Add a `--session-mode` CLI argument to `app.py` with values `full|quick|catchup` (default: `full`). For Catchup auto-detection, implement in `SessionManager` by checking `last_activity` timestamps across all sessions.

#### M4. Conversation State Machine Is Undocumented

**Severity**: MEDIUM
**Filed against**: Plan Section 二 (对话流程)

The plan describes a 4-step linear dialogue flow but does not specify the state machine (states, transitions, edge cases, error recovery) needed to implement it.

**Missing specification**:
1. **States**: What are the named states of the conversation? (e.g., `PRESENTING_SUMMARY`, `SHOWING_CARDS`, `AWAITING_CHOICE`, `EXPLORING_DIRECTION`, `PIVOTING`, `CONFIRMING`)
2. **Transitions**: What user input triggers each transition? What if the user types something unexpected?
3. **Edge cases**:
   - User types gibberish → re-prompt or fallback?
   - User asks to see a card that doesn't exist → error message?
   - User wants to go back to the card list after exploring one direction → is this supported?
   - User requests 5 card details in a row without confirming → when does the loop terminate?
4. **Termination**: What user action terminates Gate 1 and triggers the transition to Stage 4-8? Is it explicit ("confirm direction X") or implicit?

**Without a state machine spec, `gate1_interaction.py` will be implemented ad-hoc and will miss edge cases.**

**Recommendation**: Include a state machine diagram or table in the plan (or in a separate `gate1-state-machine.md` derived from it) that covers at minimum: states, transitions, trigger inputs, default transition (timeout/fallback), and termination conditions.

---

### LOW

#### L1. No Ctrl+C / Interrupt Recovery Specification

**Severity**: LOW
**Filed against**: Plan Section 二, Section 六

What happens if the user presses Ctrl+C during Gate 1? The plan does not address signal handling.

**Current behavior**: Pressing Ctrl+C during `run_daily()` raises `KeyboardInterrupt`, which propagates up through `asyncio.run()`, terminating the process immediately. No state is saved. If Gate 1 dialogue is halfway through, the conversation and any partial selections are lost.

**Mitigation**: Gate 1 should register a SIGINT handler that saves partial state (conversation JSONL + gate1_decision.json with `status: "interrupted"`) before allowing the process to terminate.

**Recommendation**: Add signal handling spec to `gate1_interaction.py` requirements. Use `try/finally` around the interaction loop to guarantee a partial archive write on any exit path.

#### L2. No Timeout / Abandonment Specification

**Severity**: LOW
**Filed against**: Plan Section 二 (dialogue flow), Section 六

The plan describes a pipeline that runs Stages 0-3 autonomously, then waits at Gate 1 for the user. What if the user never arrives?

**Scenarios**:
- Pipeline runs at 08:00, user expected at 09:00 → Gate 1 waits 1 hour. Is that OK?
- Pipeline runs at 08:00, user is on vacation → Gate 1 waits indefinitely. Resources held (GPU/CPU/RAM, open DB connections, LLM context in memory).

**No timeout is specified.** Should Gate 1 auto-abandon after N minutes and write a `gate1_timeout.json` state? Should it auto-proceed with a default selection (highest confidence direction)?

**Recommendation**: Specify a configurable timeout (default: 30 minutes). On timeout, save the session state as `abandoned`, archive all computed data, and exit cleanly. The user can resume later via Catchup mode.

#### L3. Gate Archiver Format Divergence from Existing Archivist

**Severity**: LOW
**Filed against**: Plan Section 三 (白盒归档), Section 五 (gate_archiver.py)

The plan proposes JSONL (newline-delimited JSON) for conversation logs. The existing archivist writes single JSON objects (`save_json()` always writes one complete JSON document). This creates two serialization formats within the same archive directory.

**JSONL is a fine choice** — it is append-friendly and streaming-compatible, which suits a conversation log. But the plan should justify the divergence from the existing format.

**Additionally**: The plan mentions FTS5 retrieval ("FTS5检索" in research reference 4) but the existing FTS5 tables only index JSON archive documents — not JSONL gate conversations. If FTS5 search for gate conversations is desired, `gate_archiver.py` needs its own FTS5 virtual table (or the conversation needs to be indexed as a single document).

**Recommendation**: Document that JSONL is chosen for append-friendly streaming writes. Add FTS5 indexing requirement to `gate_archiver.py` if search across past gate conversations is needed. Otherwise, state that gate conversations are only file-searchable (grep), not FTS5-searchable.

---

## Cross-Cutting Observations

### O1. The Plan Ignores the Existing Interactive Path

The plan never references `run_interactive()` (lines 335-373), which was designed for staged user interaction with the pipeline. Nor does it reference `main_window._run_gate1()` (line 182), which is the GUI's Gate 1 placeholder. The plan reads as if Gate 1 is being invented from scratch when two partial implementations already exist.

### O2. The Shadow Ecosystem Already Expects Gate 1

`shadow_mother.py:130-154` already has `create_missed_path_shadows(rejected_directions)` — a method that takes the user's rejected Gate 1 directions and creates counterfactual tracking shadows. `missed_path.py` is fully implemented and tested. The plan does not mention wiring Gate 1 output into this existing integration point.

### O3. The Plan Research Is Solid; The Implementation Map Is Not

The four research documents (decision guidance, anti-Socratic design, time estimation, conversation archiving) provide excellent UX guidance. The UX vision is coherent and well-reasoned. The problem is purely architectural: the plan assumes a pipeline architecture that does not exist and requires ~200 lines of structural changes (not 30) to create.

---

## Summary Rating

| Finding | Severity | Category |
|---------|:--------:|----------|
| C1: No pipeline insertion point — headless architecture | **CRITICAL** | Architecture |
| C2: Async/sync boundary unaddressed | **CRITICAL** | Concurrency |
| C3: Stage numbering mismatch with manifest | **CRITICAL** | Documentation |
| H1: HypothesisResult missing card fields | HIGH | Data Model |
| H2: Write non-atomic — crash survival broken | HIGH | Persistence |
| H3: ensure_dirs() missing `gates/` | HIGH | Integration |
| H4: No integration with session checkpoint | HIGH | Architecture |
| M1: Module placed in wrong directory | MEDIUM | Structure |
| M2: app.py hard ceiling blocks new features | MEDIUM | Compliance |
| M3: Mode detection undefined | MEDIUM | Specification |
| M4: Conversation state machine missing | MEDIUM | Specification |
| L1: No Ctrl+C recovery | LOW | Resilience |
| L2: No timeout/abandonment | LOW | Resilience |
| L3: Format divergence undocumented | LOW | Consistency |

**Overall Rating**: **CRITICAL** (blocked on 3 CRITICAL findings)

**Next step**: Resolve C1 first (choose Path A/B/C), then rewrite the implementation plan with the concrete architectural changes. C2 and C3 resolve naturally once C1 is decided. H1-H4 should be addressed in parallel or as prerequisites before any code is written.
