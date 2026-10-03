import json
import re
import time
import urllib.error
import urllib.request

from brain.commands import Action, Command
from brain.decision import (
    RESULT_ORDINALS,
    _ACTION_VERB_LOOKAHEAD,
    _is_valid_url_target,
    is_explicit_stop_or_cancel,
    preprocess_text,
)
from config import (
    KNOWN_APPS,
    LLM_BASE_URL,
    LLM_ENABLED,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    WEBSITES,
)
from utils.logger import log_debug, log_llm, log_warning

ALLOWED_LLM_ACTIONS = {action.name: action for action in Action}

_SYSTEM_PROMPT = """You are LIGHT's structured action planner.
Convert the user's spoken computer/browser request into JSON: {"actions": [{"action": "...", "target": "..."}]}.
Allowed actions ONLY:
OPEN_APP, CLOSE_APP, OPEN_URL, GO_BACK, GO_FORWARD, REFRESH, SEARCH, CLICK_RESULT, CLICK_ELEMENT, FIND_ELEMENT, READ_TITLE, READ_TEXT, COPY_TEXT, PASTE, TYPE, CLICK, SCROLL, PRESS_KEY, MOVE_MOUSE, WAIT, STOP, HOTKEY, SWITCH_WINDOW, MINIMIZE_WINDOW, MAXIMIZE_WINDOW, RESTORE_WINDOW, SHOW_DESKTOP, MEDIA_PLAY_PAUSE, MEDIA_FORWARD, MEDIA_BACKWARD, MEDIA_FULLSCREEN, MEDIA_EXIT_FULLSCREEN, MEDIA_MUTE, MEDIA_VOLUME_UP, MEDIA_VOLUME_DOWN, MEDIA_NEXT, MEDIA_PREVIOUS, AGENT_TASK.

Rules:
- Include EVERY step requested by the user in order.
- Example: "Find a beginner Python tutorial on YouTube and open the most relevant result" ->
  {"actions": [{"action": "OPEN_URL", "target": "youtube"}, {"action": "SEARCH", "target": "beginner Python tutorial"}, {"action": "CLICK_RESULT", "target": "1"}]}
- If the input is casual conversation, return {"actions": []}."""


def is_likely_command_candidate(text: str) -> bool:
    """
    Guard so obvious casual conversation ('How are you?', 'I am hungry',
    'What are you doing?', 'I like YouTube') never triggers an LLM call or action.
    """
    cleaned = preprocess_text(text)
    if not cleaned:
        return False
    lower = cleaned.lower()

    # Conversational questions/statements that must never become commands
    if re.match(
        r"^(?:how\s+are\s+you|who\s+are\s+you|what\s+are\s+you\s+doing|i\s+am\s+|i'm\s+|i\s+like\s+|i\s+love\s+|i\s+think\s+|that\s+is|that's|it\s+is|it's|thank\s+you|thanks|hello|hi|hey)\b",
        lower,
    ):
        return False

    # Must contain at least one action keyword to justify invoking the LLM
    return bool(re.search(rf"\b{_ACTION_VERB_LOOKAHEAD}\b", lower, re.IGNORECASE))


def validate_llm_action(
    raw_text: str,
    item: dict,
    planning_state=None,
) -> Command:
    """
    Strictly validate and normalize a single action dict returned by Qwen3 1.7B.
    Raises ValueError if the action or target is unsafe or invalid.
    """
    if not isinstance(item, dict):
        raise ValueError("LLM action entry must be a JSON object.")

    action_raw = str(item.get("action") or "").strip().upper()
    if action_raw not in ALLOWED_LLM_ACTIONS:
        raise ValueError(f"Invalid or disallowed LLM action: '{action_raw}'")

    action = ALLOWED_LLM_ACTIONS[action_raw]
    raw_target = item.get("target")
    target = str(raw_target).strip() if raw_target is not None else None
    if target == "" or (target and target.lower() == "none"):
        target = None

    # Never allow LLM to trigger STOP unless the user explicitly spoke a stop word
    if action == Action.STOP:
        if not is_explicit_stop_or_cancel(raw_text):
            raise ValueError("LLM attempted STOP without explicit stop phrase.")
        return Command(Action.STOP, None)

    if action == Action.OPEN_APP:
        if not target:
            raise ValueError("LLM OPEN_APP requires a target application.")
        app_key = target.lower().strip()
        if app_key not in KNOWN_APPS:
            raise ValueError(f"Unknown application from LLM: '{target}'")
        return Command(Action.OPEN_APP, KNOWN_APPS[app_key])

    if action == Action.CLOSE_APP:
        if not target:
            raise ValueError("LLM CLOSE_APP requires a target application.")
        app_key = target.lower().strip()
        if app_key not in KNOWN_APPS and app_key != "browser":
            raise ValueError(f"Unknown application to close from LLM: '{target}'")
        return Command(Action.CLOSE_APP, KNOWN_APPS.get(app_key, "Brave"))

    if action == Action.OPEN_URL:
        if not target:
            raise ValueError("LLM OPEN_URL requires a target URL or website.")
        t_low = target.lower().strip()
        if t_low.startswith("/") or "no_think" in t_low or "<think>" in t_low:
            raise ValueError(f"Invalid control token in LLM OPEN_URL target: '{target}'")
        if re.search(r"\bofficial\s+(?:repository|repo|website|site|page|docs|documentation|link|result)\b", t_low):
            raise ValueError(f"Invalid OPEN_URL target for search result: '{target}'")
        if t_low in WEBSITES:
            return Command(Action.OPEN_URL, WEBSITES[t_low])
        for site_key, site_url in WEBSITES.items():
            if site_key in t_low:
                return Command(Action.OPEN_URL, site_url)
        if _is_valid_url_target(target):
            return Command(Action.OPEN_URL, target)
        raise ValueError(f"Invalid URL target from LLM: '{target}'")

    if action == Action.SEARCH:
        if not target:
            raise ValueError("LLM SEARCH requires a search query.")
        if not target.lower().startswith(("youtube:", "google:")):
            current_site = getattr(planning_state, "current_site", None) if planning_state else None
            if current_site == "youtube" or "youtube" in raw_text.lower():
                target = f"youtube:{target}"
        return Command(Action.SEARCH, target)

    if action == Action.CLICK_RESULT:
        if not target:
            return Command(Action.CLICK_RESULT, "1")
        t_low = target.lower().strip()
        if t_low in RESULT_ORDINALS:
            return Command(Action.CLICK_RESULT, RESULT_ORDINALS[t_low])
        if t_low.isdigit() and int(t_low) >= 1:
            return Command(Action.CLICK_RESULT, t_low)
        if any(w in t_low for w in ("first", "1", "relevant", "top", "best")):
            return Command(Action.CLICK_RESULT, "1")
        for word, idx_str in RESULT_ORDINALS.items():
            if re.search(rf"\b{re.escape(word)}\b", t_low):
                return Command(Action.CLICK_RESULT, idx_str)
        raise ValueError(f"Invalid CLICK_RESULT index from LLM: '{target}'")

    if action in {Action.CLICK_ELEMENT, Action.FIND_ELEMENT, Action.TYPE}:
        if not target:
            raise ValueError(f"LLM {action.name} requires a non-empty target.")
        return Command(action, target)

    if action == Action.SCROLL:
        direction = (target or "down").lower().strip()
        if direction not in {"up", "down"}:
            raise ValueError(f"Invalid SCROLL direction from LLM: '{target}'")
        return Command(Action.SCROLL, direction)

    if action == Action.PRESS_KEY:
        if not target:
            raise ValueError("LLM PRESS_KEY requires a key name.")
        return Command(Action.PRESS_KEY, target.lower().strip())

    if action == Action.MOVE_MOUSE:
        if not target:
            raise ValueError("LLM MOVE_MOUSE requires a target.")
        return Command(Action.MOVE_MOUSE, target)

    if action == Action.WAIT:
        digits = re.findall(r"\d+(?:\.\d+)?", str(target or "2"))
        return Command(Action.WAIT, digits[0] if digits else "2")

    if action in {
        Action.GO_BACK,
        Action.GO_FORWARD,
        Action.REFRESH,
        Action.READ_TITLE,
        Action.READ_TEXT,
        Action.PASTE,
    }:
        return Command(action, None)

    if action in {Action.COPY_TEXT, Action.CLICK}:
        return Command(action, target)

    raise ValueError(f"Unsupported LLM action: {action}")


class QwenPlanner:
    """
    Optional local Qwen3 1.7B planner via Ollama.
    Only invoked when the fast deterministic parser cannot handle a complex/multi-step command.
    """

    def __init__(
        self,
        enabled: bool | None = None,
        provider: str = LLM_PROVIDER,
        model: str = LLM_MODEL,
        base_url: str = LLM_BASE_URL,
        timeout: float = LLM_TIMEOUT,
        transport=None,
    ):
        self.enabled = LLM_ENABLED if enabled is None else bool(enabled)
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._unavailable_until = 0.0
        self.last_latency_ms: float | None = None

    def _build_prompt(self, text: str, state=None) -> str:
        site = getattr(state, "current_site", None) or "none"
        app = getattr(state, "current_app", None) or "none"
        return f"State: site={site}, app={app}\nUser request: {text}"

    def _call_ollama(self, prompt: str) -> dict:
        if self._transport is not None:
            return self._transport(prompt)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": 180,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_body = resp.read().decode("utf-8")
            parsed = json.loads(raw_body)
            content = (
                parsed.get("message", {}).get("content")
                or parsed.get("response")
                or "{}"
            )
            if isinstance(content, str):
                cleaned_content = re.sub(r"/no_think", "", content, flags=re.IGNORECASE)
                cleaned_content = re.sub(r"<think>[\s\S]*?</think>", "", cleaned_content, flags=re.IGNORECASE).strip()
                json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_content)
                if json_match:
                    cleaned_content = json_match.group(1).strip()
                return json.loads(cleaned_content)
            return content

    def plan_actions(self, text: str, state=None) -> list[Command] | None:
        """
        Ask Qwen3 1.7B to plan 1 or more structured LIGHT commands.
        Returns a validated list of Commands, or None if LLM is disabled/unavailable/fails.
        """
        if not self.enabled:
            return None

        if not is_likely_command_candidate(text):
            return None

        now = time.monotonic()
        if self._transport is None and now < self._unavailable_until:
            return None

        start_ts = time.perf_counter()
        try:
            response_data = self._call_ollama(self._build_prompt(text, state=state))
            latency_ms = round((time.perf_counter() - start_ts) * 1000.0, 1)
            self.last_latency_ms = latency_ms
            log_llm(f"model={self.model} latency={latency_ms}ms")
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            # Back off for 15s when Ollama is offline so subsequent commands don't wait on socket timeout
            self._unavailable_until = time.monotonic() + 15.0
            log_debug(f"Ollama ({self.model}) unavailable, using fast path fallback: {err}")
            return None
        except Exception as err:
            log_warning(f"LLM planning failed, falling back gracefully: {err}")
            return None

        if not isinstance(response_data, dict):
            raise ValueError("LLM response was not a JSON object.")

        raw_actions = response_data.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            return None

        planning_state = (
            state.clone_for_planning()
            if state is not None and hasattr(state, "clone_for_planning")
            else state
        )

        validated_commands: list[Command] = []
        for item in raw_actions:
            cmd = validate_llm_action(text, item, planning_state=planning_state)
            validated_commands.append(cmd)
            if planning_state is not None and hasattr(planning_state, "record_command"):
                try:
                    planning_state.record_command(text, cmd)
                except Exception:
                    pass

        if not validated_commands:
            return None

        from brain.decision import normalize_command_plan
        return normalize_command_plan(validated_commands, state=state, raw_text=text)
