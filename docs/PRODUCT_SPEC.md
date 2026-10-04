# LIGHT — Product Specification

> **Scope**: This document defines the functional and non-functional product requirements of **LIGHT** from a user experience, operational, and behavioral perspective. For technical implementation details and component design, refer to [`docs/ARCHITECTURE.md`](file:///c:/Projects/LIGHT/docs/ARCHITECTURE.md).

---

## 1. Product Vision

**LIGHT** is an ambient, voice-driven Windows and browser automation assistant engineered for instantaneous, hands-free computer interaction. It eliminates the friction of manual mouse-and-keyboard navigation by translating natural spoken commands into verified operating system and browser actions.

### Core Value Proposition
- **Zero Cloud Dependence**: Operates completely on the local machine with no external audio transmission, subscription API keys, or cloud latency bottlenecks.
- **Instantaneous Latency**: Common commands trigger immediately without waiting for large language model generation.
- **Ambient & Unobtrusive**: Listens continuously in the background through voice activity detection (VAD), processing commands as naturally as speaking to a human copilot.
- **Deterministic Trust**: Does not guess, hallucinate, or blindly click ambiguous UI elements. Actions are semantically validated against real system state.
- **Safe Interruption**: The user retains absolute authority with instantaneous emergency preemption (`"Stop"`, `"Cancel"`).

---

## 2. Target Users & Core Use Cases

### Target Personas
1. **Multitasking Software Engineers**: Developers navigating documentation, inspecting repositories, running tests, or switching applications without leaving their primary terminal/IDE or keyboard setup.
2. **Hands-Free Operators**: Users requiring accessibility assistance or complete hands-free navigation while multitasking, reading, or presenting.
3. **Power Users & Researchers**: Users synthesizing information across multiple browser tabs, searching complex topics, and issuing compound multi-step workflows.

### Primary Use Scenarios
- **Rapid Navigation**: `"Open GitHub"`, `"Go to YouTube"`, `"Open Notepad"`, `"Close Calculator"`.
- **Compound Search & Retrieval**: `"Open GitHub, search for LangGraph and open the official repository."`
- **Contextual Continuations**: Pausing after a search and issuing a natural follow-up: `"Official repository"`, `"First result"`, or `"Second video"`.
- **Hands-Free Desktop Controls**: Switching windows, typing notes into foreground text editors, scrolling documentation, adjusting volume, or executing keyboard shortcuts.
- **Autonomous Web Research**: Handing off open-ended, multi-step inquiries to an autonomous browser agent: `"Research three Python AI agent frameworks and compare them"`.

---

## 3. Product Experience & Functional Requirements

### 3.1 Continuous Voice Interaction
- **Ambient Background Dictation**: The system must run continuously without requiring the user to hold down a push-to-talk key or wake-word phrase like "Hey Siri" or "OK Google".
- **Intelligent Segmentation**: Speech is segmented via Voice Activity Detection (VAD) into logical utterances.
- **Duplicate Debouncing**: Immediate duplicate utterances produced by STT engines or microphone echo must be debounced unless explicitly repeatable (e.g. repeated `"Scroll down"`).
- **Casual Speech Tolerance**: Casual conversational utterances (`"How are you"`, `"That's interesting"`, `"Cricket"`) must be safely ignored without raising errors or executing spurious actions.

### 3.2 Low-Latency Philosophy
- High-frequency deterministic commands (`"open youtube"`, `"scroll down"`, `"press enter"`) must be parsed in **<1ms** and dispatched immediately.
- Background voice polling must operate on a dedicated thread, ensuring that in-flight browser navigations or desktop actions never introduce audio dropouts or microphone lag.

### 3.3 Hybrid Dual-Path Intelligence
1. **Deterministic Fast Path (Tier 1)**: Common navigation, window management, media controls, search shortcuts, and viewport clicks are parsed and validated deterministically.
2. **Local Small Language Model (Tier 2)**: Complex natural language compound requests that cannot be deterministically resolved are planned by a local Qwen3 1.7B model running via Ollama.
3. **Autonomous Agent Path (Tier 3)**: Broad, multi-step research or information synthesis tasks are routed to an autonomous browser agent (Browser Use).

### 3.4 Multi-Step Compound Commands & Contextual Continuity
- Users must be able to chain multiple discrete actions into a single natural sentence:
  - Example: `"Open YouTube, search for Coldplay and click the first result."`
- In-flight execution state (`current_site`, `current_url`, `last_search_query`) must be preserved across multi-utterance interactions so follow-up commands like `"Click official docs"` resolve correctly within the active search context.

### 3.5 Desktop & Window Management
- **Window Observation**: The system must recognize and track foreground active windows and process names.
- **Foreground-Aware Typing**: Text typing commands (`"type Hello World"`) must verify that a valid foreground target window exists to prevent typing text into hidden or background processes.
- **Application Lifecycle**: Support launching and cleanly closing registered Windows desktop applications (`Notepad`, `Calculator`, `Brave`, `Chrome`).
- **Media & System Keys**: Support system media playback controls (`"pause video"`, `"play"`, `"mute"`, `"volume up"`, `"go back 10 seconds"`).

### 3.6 Deterministic Browser Automation
- **Browser Lifecycle**: LIGHT manages its own Playwright-controlled browser session (Chromium/Chrome) with automatic recovery from headless or closed contexts.
- **Navigation Shortcuts**: Built-in support for primary web properties (`google`, `youtube`, `github`, `reddit`, `wikipedia`, `gmail`, `chatgpt`, `linkedin`) and general URL normalization.
- **Target-Based Result Selection**: When the user requests a named target (e.g., `"click official repository"`), the system must rank visible candidate links using search query context, anchor text, domain authority, and semantic keywords, rather than blindly clicking result #1.
- **Semantic Destination Verification**: After navigating to a target result, the system must inspect the destination page (URL, domain, title, content) to verify that it actually matches the user's intent. If verification fails, the action must fail loudly rather than falsely reporting success.

### 3.7 Autonomous Agent Tasks (`AGENT_TASK`)
- Reserved for open-ended research, synthesis, and exploratory browsing goals.
- Runs in an isolated browser session that respects explicit browser ownership boundaries (`NONE`, `LIGHT`, `AGENT`).
- Desktop commands and background voice listening must remain fully operational while an autonomous agent task is running in the background.

### 3.8 Absolute Interruption Authority (Emergency STOP)
- When a user utters an emergency phrase (`"Stop"`, `"Cancel"`, `"Quit"`, `"Exit"`, `"Abort"`), the system must:
  - Detect the intent within **<5ms**.
  - Immediately abort in-flight commands, waiting loops, or autonomous agent steps.
  - Cancel any queued dependent actions.
  - Reset browser ownership and state cleanly.

---

## 4. Non-Functional Requirements & Invariants

| Attribute | Requirement | Validation Method |
| :--- | :--- | :--- |
| **Ingestion Latency** | Voice polling loop intervals $\le 150\text{ ms}$; parsing $\le 1\text{ ms}$. | Performance logging (`log_perf`). |
| **Emergency Preemption** | STOP detection to cancellation event set $\le 5\text{ ms}$. | Dedicated cancellation unit tests. |
| **Privacy & Security** | Zero external audio streaming; all processing local. | Architectural inspection & firewall isolation. |
| **Platform Compatibility**| Windows 10/11 64-bit and macOS 13+ (Apple Silicon & Intel). | Cross-platform discovery test suite & smoke tests. |
| **Test Verification** | 100% pass rate across baseline test discovery suite. | Automated unittest discovery in CI. |
| **False Positive Guard** | Zero accidental execution of casual speech or unrelated single words. | Safety validation tests (`test_laya.py`). |

---

## 5. Requirements vs. Implementation Boundaries

To preserve architectural clarity, product requirements must not be confused with implementation mechanisms:

- **Requirement**: "Ambient continuous listening without push-to-talk."  
  **Implementation**: Background thread polling `VoiceInputProvider` (`HandyVoiceProvider` SQLite reader or fallback).
- **Requirement**: "Local intelligence without external API keys."  
  **Implementation**: Local Qwen3 1.7B running on Ollama at `http://127.0.0.1:11434`.
- **Requirement**: "Fast, reliable browser automation."  
  **Implementation**: Playwright Chromium with persistent session recycling and CDP fallback.
- **Requirement**: "Verified result selection."  
  **Implementation**: Multi-feature in-viewport scoring and post-click semantic destination verification.
- **Requirement**: "Unblocked normal command execution during autonomous agent tasks."
  **Implementation**: Managed background worker thread (`LIGHT-AgentWorker` in `core/executor.py`) with duplicate task protection and immediate consumer loop return.
