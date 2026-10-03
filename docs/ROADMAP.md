# LIGHT — Product & Engineering Roadmap

> **Status Notice**: This roadmap documents the architectural progression of **LIGHT**. Completed items reflect verified functionality in the repository. Planned items represent agreed engineering priorities without rigid deadlines.

---

## 1. Completed Milestones

### Foundation & Core Assistant (Phase 1)
- [x] Ambient voice loop polling local Handy SQLite `history.db`.
- [x] High-performance deterministic intent parsing (`brain/decision.py`) covering 25+ actions in <1ms.
- [x] Strict prefix-guarded machine learning fallback via `Laya` with casual speech rejection.
- [x] Playwright-based browser automation (Chromium/Chrome) with DPI-aware viewport mapping.
- [x] Windows application management (`Notepad`, `Calculator`, `Brave`, `Chrome`) with safe process handling.
- [x] Precision mouse controller with relative pixel nudges, screen anchor homing, and physical clicking.
- [x] Inclusive text range copying (`copy_text_range`) with DOM highlight cleanup.

### Producer-Consumer Queue & Intelligence (Phase 2)
- [x] Thread-safe `CommandQueue` separating background voice polling (150ms) from action execution.
- [x] Monotonic transcription ID tracking (`get_transcriptions_since`) eliminating dropped utterances.
- [x] Emergency `STOP` preemption delivering <5ms cancellation across workers.
- [x] Dependent queued action pruning on prerequisite failure (`cancel_dependent_after_failure`).
- [x] Local Qwen3 1.7B LLM integration via Ollama (`http://127.0.0.1:11434`) for multi-clause goal planning.
- [x] Deterministic plan normalization and token filtering (`<think>`, `/no_think`).
- [x] Google reCAPTCHA `/sorry/` detection with automatic DuckDuckGo fallback.

### Desktop Controls & Browser Workflow Reliability (Phase 3)
- [x] Subordinate autonomous web agent (`AutonomousBrowserAgent`) using Browser Use and local Ollama.
- [x] Event-loop-safe async agent execution (`execute_task`) preventing event loop conflicts.
- [x] Three-state browser ownership model (`NONE`, `LIGHT`, `AGENT`) preventing controller collisions.
- [x] Concurrent desktop commands (`OPEN_APP`, `HOTKEY`, `TYPE`, `MEDIA_*`) while agent browses in background.
- [x] GitHub repository search integration (`search_github`) and search results container detection.
- [x] Multi-feature search candidate scoring (+120 domain, +80 slug, +50 target) prioritizing official repos.
- [x] Semantic post-click destination verification (`verify_destination`) preventing false success reports.
- [x] Foreground-aware typing with window focus inspection (`computer/screen.py`).
- [x] Windows window state controls (minimize, maximize, restore, switch) and media playback keys.
- [x] Comprehensive test suite expansion to 119 discovered tests (115 passed, 4 opt-in skipped).

---

## 2. Current Hardening Focus

### Engineering Memory, CI & Stability (Active Phase)
- [x] Professional AI coding agent contract (`AGENTS.md`) and operational invariants.
- [x] Comprehensive system architecture, product specification, and decision records under `docs/`.
- [x] Windows GitHub Actions CI workflow running full unit and Playwright integration discovery suite.
- [x] Clean logs directory management (`logs/.gitkeep`) and `.gitignore` hygiene.
- [ ] Automated retry loop on alternative search candidates when initial semantic verification fails.
- [ ] Dynamic viewport scrolling during candidate ranking to inspect results below the initial fold.

---

## 3. Planned Near-Term Improvements

### Desktop & Multi-Monitor Refinements
- [ ] **Multi-Monitor DPI Normalization**: Extend coordinate mapping and screen homing across heterogeneous multi-monitor setups with varying scale factors (e.g. 150% laptop + 100% external monitor).
- [ ] **Dynamic Windows App Launcher**: Support launching unindexed installed Windows applications via Start Menu search indexing.
- [ ] **System Tray & Hotkey Status**: Lightweight desktop overlay indicating active state (`LISTENING`, `EXECUTING`, `AGENT_RUNNING`, `PAUSED`).

### Browser & Search Enhancements
- [ ] **Browser Use Step Tuning**: Fine-tune Browser Use step budgets and schema validation for local CPU execution.
- [ ] **Multi-Tab Session Coordination**: Allow deterministic tab switching and cross-tab query propagation.
- [ ] **Direct Documentation Indexing**: Offline quick-reference lookup for common programming frameworks.

---

## 4. Future / Exploratory Directions

### Standalone Speech & Local Vision
- [ ] **In-Process Whisper VAD**: Embed local Whisper voice activity detection directly within LIGHT, removing reliance on external Handy installations.
- [ ] **Local Vision UI Grounding**: Investigate compact local vision-language models (e.g. Qwen2-VL) for visual bounding-box grounding on complex non-web desktop user interfaces.
- [ ] **Voice Feedback (TTS)**: Optional local text-to-speech confirmation for completed research tasks.
