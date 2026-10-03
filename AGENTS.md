# AGENTS.md — AI Engineering Contract & Operating Guidelines

> **CRITICAL CONTRACT**: This file is the primary developer and AI agent contract for working in the **LIGHT** repository. Any AI agent, coding assistant, or engineer modifying this codebase must read, understand, and strictly abide by the rules, architectural invariants, and verification procedures defined herein.

---

## 1. Project Identity

**LIGHT** is a production-grade, local-first, voice-controlled Windows and browser automation assistant.

- **Primary Goal**: Deliver instantaneous, hands-free computer and browser control using ambient, continuous voice dictation without requiring cloud APIs, subscription keys, or heavyweight cognitive overhead.
- **Product Classification**: Low-latency desktop utility and browser copilot combining deterministic parsing (<1ms) with local small language models (Qwen3 1.7B via Ollama) and an isolated autonomous web agent (Browser Use).
- **Core Philosophy**:
  - **Local-First & Private**: Voice audio, transcriptions, LLM inference, and browser automation run entirely on the local machine.
  - **Speed as a Feature**: Common commands execute deterministically in milliseconds; background listening never halts or stutters during execution.
  - **Fail-Safe & Verifiable**: Physical actions (typing, clicking, navigating) are verified before success is reported. Emergency `STOP` preemption guarantees that the user retains absolute control at all times.

---

## 2. Current Architecture Overview

LIGHT operates as a multi-tier producer-consumer automation pipeline:

```text
Physical Voice Input
        │
        ▼
Handy Desktop App (Local STT & VAD) ──► SQLite `history.db`
                                             │
┌────────────────────────────────────────────┘
▼
Dedicated Voice Listener Thread (`core/loop.py::_listener_worker`)
        │ (non-blocking polling @ 150ms + debouncing)
        ▼
Thread-Safe Command Queue (`core/queue_manager.py`)
        │ (preemption check: STOP/CANCEL -> priority queue)
        ▼
Decision Engine / Brain (`brain/laya.py`, `brain/decision.py`)
        ├── 1. Multi-step deterministic parser (<1ms)
        ├── 2. Single-step deterministic parser (<1ms)
        ├── 3. Local Qwen3 1.7B Planner via Ollama (`brain/llm.py`)
        ├── 4. Complex deterministic search fallback
        └── 5. Laya intent classifier (strict prefix-guarded fallback)
        │
        ▼
Executor Pipeline (`core/executor.py`)
        ├── Desktop Subsystem (`computer/apps.py`, `keyboard.py`, `mouse.py`, `screen.py`)
        ├── Deterministic Browser (`browser/browser.py` via Playwright Chromium)
        └── Autonomous Web Agent (`browser/agent.py` via Browser Use + Ollama)
        │
        ▼
Observation & Verification
        ├── Window focus & foreground verification
        ├── Candidate ranking (text, href, domain, official semantics)
        └── Post-click semantic destination verification
```

For the exhaustive technical specification, data flow diagrams, and component dependencies, consult [`docs/ARCHITECTURE.md`](file:///c:/Projects/LIGHT/docs/ARCHITECTURE.md).

---

## 3. Core Engineering Principles

Every engineer and AI assistant modifying LIGHT must honor these sixteen foundational principles:

1. **Preserve Existing Functionality**: LIGHT is an active, working product. Never break, remove, or degrade existing capabilities.
2. **Prefer Incremental, Minimal Changes**: Always make the smallest safe change that accomplishes the goal. Avoid sprawling diffs.
3. **Avoid Unnecessary Rewrites**: Do not redesign or replace core systems merely because you would have implemented them differently.
4. **Keep Deterministic Paths Deterministic**: High-frequency commands (`"open youtube"`, `"scroll down"`, `"press enter"`, `"click search bar"`) must execute deterministically in <1ms without involving an LLM.
5. **Justify LLM Usage**: The local Qwen3 1.7B planner is reserved for complex, multi-clause natural language search and navigation instructions. Never route simple commands to the LLM.
6. **Low Latency is a First-Class Requirement**: Ingestion to execution must feel instantaneous. Audio polling must never be blocked by downstream execution.
7. **Continuous Listening is Non-Negotiable**: The background voice ingestion thread (`_listener_worker`) must remain decoupled from synchronous or asynchronous action execution.
8. **STOP / CANCEL Has Absolute Priority**: When a user says `"Stop"`, `"Cancel"`, or `"Exit"`, any running browser task, wait interval, or queued action must abort within <5ms.
9. **Never Claim Success Without Verification**: A dispatched mouse click or key press is not proof of success. Elements must be verified in viewport, foreground windows must be confirmed, and landing URLs must match expected semantics.
10. **Browser Targets Must Never Be Blindly Clicked**: Ambiguous or named result requests (`"click official repository"`, `"open docs"`) must rank visible candidate links using semantic relevance scoring and fail safely if confidence is low.
11. **Browser Use Must Respect Browser Ownership**: Browser Use runs in an isolated session under `BrowserOwnership.AGENT` and must never corrupt or conflict with LIGHT's primary Playwright session (`BrowserOwnership.LIGHT`).
12. **Existing Tests Are the Product Contract**: All unit and integration tests represent hard product requirements. Tests must never be deleted, commented out, or weakened to make a build pass.
13. **Critical Workflows Require Regression Tests**: Whenever a bug is discovered or an edge case is hardened, an accompanying regression test must be added to the test suite.
14. **Validate Critical Execution Paths**: Changes affecting `core/loop.py`, `core/queue_manager.py`, `core/executor.py`, or `browser/browser.py` require end-to-end testing across both synchronous and asynchronous modes.
15. **Preserve Local-First Behavior**: LIGHT must function completely offline (or over localhost Ollama). Never introduce mandatory cloud APIs or remote telemetry.
16. **Do Not Add Cloud Dependencies Casually**: Keep core dependencies lean. Do not add OpenAI, Anthropic, or external cloud SDKs to default execution paths.

---

## 4. Before Modifying Code

Before writing a single line of code or editing an existing file, follow this protocol:

1. **Read This Document (`AGENTS.md`)**: Ensure you are aligned with project constraints and invariants.
2. **Read Relevant System Documentation**:
   - Technical Architecture: [`docs/ARCHITECTURE.md`](file:///c:/Projects/LIGHT/docs/ARCHITECTURE.md)
   - Safety & Invariants: [`docs/SAFETY.md`](file:///c:/Projects/LIGHT/docs/SAFETY.md)
   - Testing Guide: [`docs/TESTING.md`](file:///c:/Projects/LIGHT/docs/TESTING.md)
   - Historical Decisions: [`docs/DECISIONS.md`](file:///c:/Projects/LIGHT/docs/DECISIONS.md)
   - Solved Issues: [`docs/TROUBLESHOOTING.md`](file:///c:/Projects/LIGHT/docs/TROUBLESHOOTING.md)
3. **Inspect the Live Repository**: Check current files and Git history (`git status`, `git log -n 5`). Code in the repository is the final source of truth.
4. **Identify Affected Components**: Map out inbound and outbound dependencies.
5. **Identify and Run Existing Tests**: Run relevant tests before making changes to establish a known clean baseline.
6. **Formulate a Minimal Plan**: Plan the smallest possible safe modification.

---

## 5. After Modifying Code

After modifying code, complete the full verification and reporting cycle:

1. **Add or Update Tests**: Ensure new behavior or bug fixes are covered by explicit regression tests.
2. **Run Targeted Tests**: Verify the specific test classes directly affected by your changes.
3. **Run the Full Test Discovery Suite**:
   ```powershell
   .\lightenv\Scripts\python.exe -m unittest discover -s tests -v
   ```
   Ensure zero failures, zero errors, and that only expected opt-in tests are skipped.
4. **Update Documentation**:
   - If user-facing or subsystem features changed, update [`docs/FEATURES.md`](file:///c:/Projects/LIGHT/docs/FEATURES.md).
   - If an architectural decision or invariant was established, add an ADR to [`docs/DECISIONS.md`](file:///c:/Projects/LIGHT/docs/DECISIONS.md).
   - If a new bug was diagnosed and resolved, record symptoms, root cause, and fix in [`docs/TROUBLESHOOTING.md`](file:///c:/Projects/LIGHT/docs/TROUBLESHOOTING.md).
   - Always log meaningful milestones and changes in [`docs/CHANGELOG.md`](file:///c:/Projects/LIGHT/docs/CHANGELOG.md).
5. **Inspect the Git Diff**: Run `git diff` and verify that no unintended edits, formatting churn, or leftover debugging statements exist in product files.
6. **Report Honestly**: Disclose exact files changed, tests run, test outputs, and any observed risks or limitations. Never claim a test passed unless you executed it and observed the result.

---

## 6. Forbidden Behavior

The following actions are strictly prohibited in this repository:

- ❌ **Deleting, skipping, or modifying existing assertions to make failing tests pass**.
- ❌ **Disabling verification mechanisms** (such as bypassing `verify_destination`, skipping focus checks, or faking element coordinates).
- ❌ **Silently changing architectural boundaries** (e.g. converting deterministic parsers into LLM prompts).
- ❌ **Rewriting major modules** without explicit user consent.
- ❌ **Introducing external cloud API requirements** or requiring API keys for core operation.
- ❌ **Claiming tests passed or actions succeeded without running them**.
- ❌ **Modifying unrelated subsystems** while working on an isolated bug fix or feature task.
- ❌ **Force-pushing (`git push --force`)**, amending published commits, rewriting Git history, or destructively resetting branches.

---

## 7. Documentation Directory Map

Detailed project documentation is structured under the [`docs/`](file:///c:/Projects/LIGHT/docs/) directory:

- [`docs/PRODUCT_SPEC.md`](file:///c:/Projects/LIGHT/docs/PRODUCT_SPEC.md) — What LIGHT is intended to be: product vision, user experience, and core requirements.
- [`docs/ARCHITECTURE.md`](file:///c:/Projects/LIGHT/docs/ARCHITECTURE.md) — How LIGHT is built: comprehensive technical architecture, data flows, and component specs.
- [`docs/FEATURES.md`](file:///c:/Projects/LIGHT/docs/FEATURES.md) — Comprehensive feature inventory, implementation status, and command examples.
- [`docs/CHANGELOG.md`](file:///c:/Projects/LIGHT/docs/CHANGELOG.md) — Human-readable development milestones and categorized evolution history.
- [`docs/DECISIONS.md`](file:///c:/Projects/LIGHT/docs/DECISIONS.md) — Architecture Decision Records (ADRs) detailing why critical decisions were made.
- [`docs/ROADMAP.md`](file:///c:/Projects/LIGHT/docs/ROADMAP.md) — Current status, completed milestones, active hardening, and future directions.
- [`docs/TESTING.md`](file:///c:/Projects/LIGHT/docs/TESTING.md) — Multi-tier test suite architecture, test execution commands, and critical workflows.
- [`docs/SAFETY.md`](file:///c:/Projects/LIGHT/docs/SAFETY.md) — Safety invariants, preemption guarantees, verification rules, and failure modes.
- [`docs/TROUBLESHOOTING.md`](file:///c:/Projects/LIGHT/docs/TROUBLESHOOTING.md) — Exhaustive guide to historical bugs, root causes, fixes, and regression tests.
