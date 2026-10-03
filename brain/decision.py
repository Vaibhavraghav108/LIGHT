import re
from brain.commands import Action, Command
from config import KNOWN_APPS, STOP_COMMANDS, WEBSITES


KEY_COMMANDS = {
    "enter": "enter",
    "press enter": "enter",
    "hit enter": "enter",
    "space": "space",
    "press space": "space",
    "backspace": "backspace",
    "press backspace": "backspace",
    "escape": "esc",
    "press escape": "esc",
    "esc": "esc",
    "press esc": "esc",
    "tab": "tab",
    "press tab": "tab",
    "delete": "delete",
    "press delete": "delete",
    "up": "up",
    "press up": "up",
    "arrow up": "up",
    "up arrow": "up",
    "down": "down",
    "press down": "down",
    "arrow down": "down",
    "down arrow": "down",
    "left": "left",
    "press left": "left",
    "arrow left": "left",
    "left arrow": "left",
    "right": "right",
    "press right": "right",
    "arrow right": "right",
    "right arrow": "right",
}

RESULT_ORDINALS = {
    "first": "1",
    "1st": "1",
    "one": "1",
    "1": "1",
    "second": "2",
    "2nd": "2",
    "two": "2",
    "2": "2",
    "third": "3",
    "3rd": "3",
    "three": "3",
    "3": "3",
    "fourth": "4",
    "4th": "4",
    "four": "4",
    "4": "4",
    "fifth": "5",
    "5th": "5",
    "five": "5",
    "5": "5",
}

# Handy occasionally inserts conversational filler into short movement commands
# (for example, "move now slightly left"). These patterns are deliberately
# restricted to an explicit direction and known size modifiers; arbitrary
# phrases beginning with "move" must still be rejected rather than guessed.
_MOVE_DIRECTION_PATTERN = r"(?:up|down|left|right)"
_MOVE_MODIFIER_PATTERN = (
    r"(?:(?:a\s+)?little|slightly|(?:a\s+)?bit|tiny\s+bit|"
    r"nudge|short|(?:a\s+)?lot|far|way|much|big)"
)


def _normalise_spoken_relative_move(text: str) -> str | None:
    """Return a safe relative-movement target for natural shorthand, if any.

    This supports STT variants such as ``move now slightly right more`` while
    requiring exactly one cardinal direction. Returning ``None`` leaves the
    phrase to the normal safety path instead of turning casual speech into a
    physical mouse action.
    """
    match = re.match(r"^move\s+(?:now\s+|please\s+)?(.+?)$", text, re.IGNORECASE)
    if not match:
        return None

    target = match.group(1).strip().lower()
    # "more" is frequently a transcription flourish after a qualified move.
    # The actual size remains controlled by "slightly", "a little", etc.
    target = re.sub(r"\s+(?:more|please)$", "", target).strip()

    modifier_first = re.fullmatch(
        rf"(?:{_MOVE_MODIFIER_PATTERN}\s+)?{_MOVE_DIRECTION_PATTERN}", target
    )
    direction_first = re.fullmatch(
        rf"{_MOVE_DIRECTION_PATTERN}(?:\s+{_MOVE_MODIFIER_PATTERN})?", target
    )
    if modifier_first or direction_first:
        return target
    return None


def _is_valid_url_target(candidate: str) -> bool:
    """Validate that a URL candidate has a valid host/domain structure."""
    if not candidate or " " in candidate:
        return False
    stripped = candidate.lower().strip()
    for scheme in ("https://", "http://"):
        if stripped.startswith(scheme):
            stripped = stripped[len(scheme):]
            break
    host = stripped.split("/", 1)[0].split(":", 1)[0]
    if host == "localhost" or host.startswith("127.0.0.1"):
        return True
    return bool(re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", host))


_ACTION_VERB_LOOKAHEAD = (
    r"(?:click|open|close|search|find|move|hover|point|scroll|go|navigate|"
    r"read|copy|select|paste|type|press|hit|wait|stop|cancel|exit|quit|"
    r"shut\s*down|refresh|reload|back|forward|"
    r"switch|minimize|maximize|restore|show|pause|play|resume|skip|rewind|"
    r"mute|unmute|louder|quieter|volume|next|previous|prev|"
    r"ctrl|control|alt|win|windows)"
)

_AGENT_TASK_PATTERN = re.compile(
    r"^(?:please\s+)?(?:"
    r"(?:deep\s+)?research\b|"
    r"investigate\b|"
    r"browse\s+and\s+(?:find|compare|research|summarize|browse)\b|"
    r"compare\b|"
    r"summarize\b|"
    r"(?:find|look\s*up)\s+.+?\s+and\s+(?:tell\s+me|show\s+me|give\s+me|summarize|compare)\b|"
    r"look\s*up\s+.+?\s+(?:and\s+tell\s+me|on\s+the\s+web)\b|"
    r"find\s+(?:the\s+)?official\s+.+?\s+(?:page|website|site|repo|repository|docs|documentation)\b|"
    r"find\s+(?:the\s+)?(?:\d+|five|three|four|ten|top|best|several)\s+.+?\s+(?:and\s+(?:compare|summarize)|on\s+the\s+web)\b"
    r")",
    re.IGNORECASE,
)


def _is_agent_task(text: str) -> bool:
    if not text:
        return False
    return bool(_AGENT_TASK_PATTERN.search(text.strip()))


def _parse_hotkey(text: str) -> str | None:
    """
    Parse spoken hotkey combinations like:
    'press ctrl c', 'ctrl v', 'alt tab', 'win d', 'press ctrl shift esc', 'alt f4'.
    Returns canonical hotkey string like 'ctrl+c', 'alt+tab', 'win+d', or None.
    """
    t = text.strip().lower()
    t = re.sub(r"^(?:press|hit|hotkey)\s+", "", t).strip()
    t_clean = re.sub(r"\s*(?:\+|and)\s*", " ", t)
    tokens = t_clean.split()
    if not (2 <= len(tokens) <= 4):
        return None
    modifiers = {"ctrl", "control", "alt", "win", "windows", "shift"}
    if tokens[0] not in modifiers:
        return None
    normalized_tokens = []
    for tok in tokens[:-1]:
        if tok not in modifiers:
            return None
        norm = "ctrl" if tok == "control" else ("win" if tok == "windows" else tok)
        normalized_tokens.append(norm)
    last = tokens[-1]
    if last in {"escape", "esc"}:
        last = "esc"
    valid_key_pattern = (
        r"^[a-z0-9]$|^f\d{1,2}$|"
        r"^(?:tab|esc|enter|space|backspace|delete|up|down|left|right|home|end|pageup|pagedown)$"
    )
    if not re.match(valid_key_pattern, last):
        return None
    normalized_tokens.append(last)
    return "+".join(normalized_tokens)


_CONVERSATIONAL_PREFIX_RE = re.compile(
    rf"^(?:(?:okay|ok|alright|all\s+right|please|now|well|so|"
    rf"can\s+you(?:\s+please)?|could\s+you(?:\s+please)?|would\s+you(?:\s+please)?|will\s+you(?:\s+please)?)\s+)+(?={_ACTION_VERB_LOOKAHEAD}\b)",
    re.IGNORECASE,
)

_MULTI_CLAUSE_SPLIT_RE = re.compile(
    rf"(?:\s*[,;]+\s*(?:and\s+(?:then\s+)?|then\s+)?(?={_ACTION_VERB_LOOKAHEAD}\b))"
    rf"|(?:\s+\b(?:and\s+then|then|and)\s+(?={_ACTION_VERB_LOOKAHEAD}\b))",
    re.IGNORECASE,
)


def preprocess_text(text: str) -> str:
    """Clean raw speech transcription while preserving case for typed text."""
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = cleaned.rstrip(".!?").strip()

    if not cleaned.lower().startswith("type "):
        cleaned = re.sub(r"\s*[,;]+\s*", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = _CONVERSATIONAL_PREFIX_RE.sub("", cleaned).strip()

    return cleaned


def is_explicit_stop_or_cancel(text: str) -> bool:
    """Return True if raw spoken text is an explicit high-priority STOP/CANCEL command."""
    cleaned = preprocess_text(text).lower()
    return cleaned in STOP_COMMANDS


def is_site_ready_in_state(state, site: str | None) -> bool:
    """
    Return True only if `state` proves the browser is currently open on a real,
    non-blank page matching `site` (e.g. 'youtube' or 'google').
    Returns False if browser is closed, state is None, or current_url is 'about:blank'.
    """
    if state is None or not site:
        return False
    if not getattr(state, "browser_open", False):
        return False
    current_site = (getattr(state, "current_site", None) or "").strip().lower()
    if current_site != site.strip().lower():
        return False
    current_url = (getattr(state, "current_url", None) or "").strip().lower()
    if not current_url or current_url == "about:blank" or current_url.startswith(("about:", "chrome://", "edge://", "brave://")):
        return False
    return True


def normalize_command_plan(
    commands: list[Command],
    state=None,
    raw_text: str = "",
) -> list[Command]:
    """
    Post-understanding Plan Normalization & Dependency Resolution Layer.
    - Ensures prerequisite `OPEN_URL` is inserted before `SEARCH` if the target site
      (e.g. YouTube) is not already active and ready in `state` (or `about:blank`).
    - Removes redundant `OPEN_URL` if `state` proves the browser is already open and
      ready on that exact site.
    - Preserves sequential dependency ordering: OPEN_URL -> SEARCH -> CLICK_RESULT.
    """
    if not commands:
        return []

    raw_lower = (raw_text or "").lower()
    active_site: str | None = None
    if state is not None:
        candidate_site = getattr(state, "current_site", None)
        if is_site_ready_in_state(state, candidate_site):
            active_site = candidate_site.strip().lower()

    normalized: list[Command] = []

    for cmd in commands:
        if cmd.action == Action.OPEN_URL and cmd.target:
            target_low = cmd.target.lower().strip()
            target_site = None
            for site_key, site_url in WEBSITES.items():
                if site_key in target_low or target_low == site_url.lower():
                    target_site = site_key
                    break

            # If browser is already open and ready on this exact site, skip redundant OPEN_URL
            # when part of a multi-step search workflow
            if target_site and active_site == target_site and len(commands) > 1:
                continue

            normalized.append(cmd)
            if target_site:
                active_site = target_site
            continue

        if cmd.action == Action.SEARCH and cmd.target:
            t_str = cmd.target.strip()
            t_low = t_str.lower()

            if t_low.startswith("youtube:"):
                required_site = "youtube"
                clean_query = t_str[8:].strip()
            elif t_low.startswith("google:"):
                required_site = "google"
                clean_query = t_str[7:].strip()
            elif t_low.startswith("github:"):
                required_site = "github"
                clean_query = t_str[7:].strip()
            elif "github" in raw_lower or active_site == "github":
                required_site = "github"
                clean_query = t_str
            elif "youtube" in raw_lower or active_site == "youtube":
                required_site = "youtube"
                clean_query = t_str
            else:
                required_site = "google"
                clean_query = t_str

            # Canonicalize target representation
            if required_site == "youtube":
                canonical_target = f"youtube:{clean_query}"
            elif required_site == "github":
                canonical_target = f"github:{clean_query}"
            elif t_low.startswith("google:"):
                canonical_target = f"google:{clean_query}"
            else:
                canonical_target = clean_query

            # Insert prerequisite OPEN_URL if required_site is not currently active & ready
            is_about_blank = (
                state is not None
                and (getattr(state, "current_url", None) or "").strip().lower() == "about:blank"
            )
            is_closed = state is not None and not getattr(state, "browser_open", False)
            needs_open_url = (active_site != required_site) and (
                len(commands) > 1
                or is_about_blank
                or (is_closed and ("youtube" in raw_lower or "github" in raw_lower) and "and" in raw_lower)
            )
            if needs_open_url and required_site in WEBSITES:
                normalized.append(Command(Action.OPEN_URL, WEBSITES[required_site]))
                active_site = required_site

            normalized.append(Command(Action.SEARCH, canonical_target))
            active_site = required_site
            continue

        normalized.append(cmd)

    return normalized


def parse_multi_command(text: str, state=None) -> list[Command] | None:
    """
    Fast-path parser for multi-step compound voice commands such as:
    'Open YouTube, search for Python tutorials, click the first video and scroll down.'
    Returns a sequential list of Commands if all clauses resolve deterministically,
    or None if single-step or ambiguous (leaving complex phrasing to Qwen3 1.7B).
    """
    if not text:
        return None

    raw = text.strip().rstrip(".!?").strip()
    if raw.lower().startswith(("type ", "copy ", "select ")) or _is_agent_task(raw):
        return None

    clauses = [c.strip() for c in _MULTI_CLAUSE_SPLIT_RE.split(raw) if c and c.strip()]
    if len(clauses) < 2:
        return None

    planning_state = (
        state.clone_for_planning()
        if state is not None and hasattr(state, "clone_for_planning")
        else state
    )

    commands: list[Command] = []
    trailing_incomplete: str | None = None
    for i, clause in enumerate(clauses):
        try:
            cmd = parse_deterministic_command(clause, state=planning_state)
        except Exception:
            if i == len(clauses) - 1 and len(commands) >= 1:
                cleaned_clause = preprocess_text(clause).lower()
                if cleaned_clause in {"open", "click", "click on", "select", "find", "search", "search for"}:
                    trailing_incomplete = cleaned_clause
                    break
            return None
        if cmd is None:
            if i == len(clauses) - 1 and len(commands) >= 1:
                cleaned_clause = preprocess_text(clause).lower()
                if cleaned_clause in {"open", "click", "click on", "select", "find", "search", "search for"}:
                    trailing_incomplete = cleaned_clause
                    break
            return None
        commands.append(cmd)
        if planning_state is not None and hasattr(planning_state, "record_command"):
            try:
                planning_state.record_command(clause, cmd)
            except Exception:
                pass

    if len(commands) < 1 or (len(commands) < 2 and trailing_incomplete is None):
        return None

    if trailing_incomplete and state is not None:
        state.pending_incomplete_action = trailing_incomplete
        last_cmd = commands[-1]
        state.pending_goal = last_cmd.target or last_cmd.action.value

    return normalize_command_plan(commands, state=state, raw_text=text)


def parse_complex_fallback(text: str, state=None) -> list[Command] | None:
    """
    Deterministic fallback for natural multi-step search-and-open phrases
    (e.g., 'Find a beginner Python tutorial on YouTube and open the most relevant result')
    used when Qwen3 is disabled or unavailable.
    """
    if not text:
        return None

    cleaned = preprocess_text(text)
    m = re.match(
        r"^(?:find|search(?:\s+for)?|look\s+for)\s+(?:a\s+|an\s+)?(.+?)\s+on\s+(youtube|google)(?:\s+(?:and\s+(?:then\s+)?|then\s+)(.+))?$",
        cleaned,
        re.IGNORECASE,
    )
    if not m:
        return None

    query = m.group(1).strip()
    site = m.group(2).lower().strip()
    tail_clause = (m.group(3) or "").strip()
    if not query:
        return None

    raw_commands: list[Command] = [
        Command(Action.SEARCH, f"{site}:{query}")
    ]

    if tail_clause:
        tail_cmd = parse_deterministic_command(tail_clause, state=state)
        if tail_cmd is not None:
            raw_commands.append(tail_cmd)

    return normalize_command_plan(raw_commands, state=state, raw_text=text)


def parse_deterministic_command(text: str, state=None) -> Command | None:
    """
    Resolve clear, unambiguous voice commands deterministically
    before falling back to the Laya model.
    """
    cleaned = preprocess_text(text)
    if not cleaned:
        raise ValueError("Empty command")

    text_lower = cleaned.lower()

    # Reject bare incomplete verbs immediately rather than letting a classifier guess
    if text_lower in {
        "open",
        "close",
        "type",
        "find",
        "click on",
        "go to",
        "navigate to",
        "search",
        "search for",
        "search on youtube",
        "search on google",
        "copy text",
        "copy from",
        "select from",
        "switch",
        "switch to",
    }:
        raise ValueError(f"Incomplete command: '{cleaned}'")

    # 1. Explicit STOP commands
    if text_lower in STOP_COMMANDS:
        return Command(Action.STOP, None)

    # Hotkey combinations (e.g., 'press ctrl c', 'alt tab', 'win d')
    hotkey = _parse_hotkey(cleaned)
    if hotkey is not None:
        return Command(Action.HOTKEY, hotkey)

    # Window controls
    if text_lower in {"show desktop", "go to desktop", "minimize all", "minimize all windows", "hide all windows"}:
        return Command(Action.SHOW_DESKTOP, None)

    if text_lower in {"minimize", "minimize window", "minimize this window", "minimize the window", "minimize current window", "minimize app"}:
        return Command(Action.MINIMIZE_WINDOW, None)

    if text_lower in {"maximize", "maximize window", "maximize this window", "maximize the window", "maximize current window", "maximize app"}:
        return Command(Action.MAXIMIZE_WINDOW, None)

    if text_lower in {"restore", "restore window", "restore this window", "restore the window", "restore current window", "unmaximize window", "un-maximize window"}:
        return Command(Action.RESTORE_WINDOW, None)

    switch_match = re.match(r"^switch\s+(?:window\s+)?to\s+(.+)$", cleaned, re.IGNORECASE)
    if switch_match:
        win_target = switch_match.group(1).strip()
        return Command(Action.SWITCH_WINDOW, win_target)
    if text_lower in {"switch window", "switch windows", "switch app", "switch application"}:
        return Command(Action.SWITCH_WINDOW, None)

    # Media controls
    if text_lower in {
        "pause", "pause video", "pause the video", "pause playback", "pause music", "pause media",
        "play video", "play the video", "resume", "resume video", "resume the video", "resume playback"
    }:
        return Command(Action.MEDIA_PLAY_PAUSE, None)

    if text_lower in {"fullscreen", "full screen", "go fullscreen", "go full screen", "enter fullscreen", "enter full screen", "make it fullscreen", "fullscreen video", "full screen video"}:
        return Command(Action.MEDIA_FULLSCREEN, None)

    if text_lower in {"exit fullscreen", "exit full screen", "leave fullscreen", "leave full screen", "unfullscreen", "close fullscreen"}:
        return Command(Action.MEDIA_EXIT_FULLSCREEN, None)

    if text_lower in {"mute", "mute video", "mute audio", "unmute", "unmute video", "unmute audio"}:
        return Command(Action.MEDIA_MUTE, None)

    if text_lower in {"volume up", "turn volume up", "increase volume", "louder", "turn it up", "raise volume"}:
        return Command(Action.MEDIA_VOLUME_UP, None)

    if text_lower in {"volume down", "turn volume down", "decrease volume", "quieter", "turn it down", "lower volume"}:
        return Command(Action.MEDIA_VOLUME_DOWN, None)

    if text_lower in {"next video", "next track", "next song", "skip video"}:
        return Command(Action.MEDIA_NEXT, None)

    if text_lower in {"previous video", "previous track", "previous song", "prev video", "prev track"}:
        return Command(Action.MEDIA_PREVIOUS, None)

    fwd_match = re.match(
        r"^(?:skip|forward|fast\s+forward|jump\s+forward|seek\s+forward)(?:\s+(?:by\s+)?(\d+)(?:\s+seconds?|\s+secs?)?)?$",
        cleaned,
        re.IGNORECASE,
    )
    if fwd_match:
        sec = fwd_match.group(1) or "10"
        return Command(Action.MEDIA_FORWARD, sec)

    if text_lower in {"rewind", "seek back", "skip back"}:
        return Command(Action.MEDIA_BACKWARD, "10")

    bwd_match = re.match(
        r"^(?:rewind|backward|skip\s+back(?:ward)?|jump\s+back(?:ward)?|seek\s+back(?:ward)?|go\s+back)\s+(?:by\s+)?(\d+)(?:\s+seconds?|\s+secs?)?$",
        cleaned,
        re.IGNORECASE,
    )
    if bwd_match:
        sec = bwd_match.group(1) or "10"
        return Command(Action.MEDIA_BACKWARD, sec)

    # Autonomous agent task (research & compare across web)
    if _is_agent_task(cleaned):
        return Command(Action.AGENT_TASK, cleaned)

    # 2. Direct keyboard commands
    if text_lower in KEY_COMMANDS:
        return Command(Action.PRESS_KEY, KEY_COMMANDS[text_lower])

    # 3. Browser navigation
    if text_lower in {"go back", "navigate back", "back", "browser back"}:
        return Command(Action.GO_BACK, None)

    if text_lower in {"go forward", "navigate forward", "forward", "browser forward"}:
        return Command(Action.GO_FORWARD, None)

    if text_lower in {"refresh", "refresh page", "reload", "reload page"}:
        return Command(Action.REFRESH, None)

    # 4. Browser / Screen observation & Copy/Paste commands
    if text_lower in {"read page title", "read title", "get page title", "what is the page title"}:
        return Command(Action.READ_TITLE, None)

    if text_lower in {"read page text", "read visible page text", "read visible text", "read text", "read page"}:
        return Command(Action.READ_TEXT, None)

    if text_lower in {"paste", "paste text", "paste it", "paste here"}:
        return Command(Action.PASTE, None)

    if text_lower in {"copy", "copy selection", "copy selected text"}:
        return Command(Action.COPY_TEXT, None)

    # "Copy from <start> till/to/until <end>"
    copy_range_match = re.match(
        r"^(?:copy|select)\s+(?:text\s+)?from\s+['\"]?(.+?)['\"]?\s+(?:till|until|to|up\s+to)\s+['\"]?(.+?)['\"]?$",
        cleaned,
        re.IGNORECASE,
    )
    if copy_range_match:
        start_phrase = copy_range_match.group(1).strip()
        end_phrase = copy_range_match.group(2).strip()
        if start_phrase and end_phrase:
            return Command(Action.COPY_TEXT, f"{start_phrase}|||{end_phrase}")
        raise ValueError("Both start and end phrases are required for copy-from-till.")

    if text_lower.startswith(("copy from ", "select from ", "copy text from ")):
        raise ValueError(
            "Incomplete copy-range command. Expected: 'copy from <start> till <end>'."
        )

    # "Copy text <phrase>" or "Copy <phrase>"
    copy_direct_match = re.match(
        r"^copy(?:\s+(?:the\s+)?(?:text|sentence|paragraph|line|phrase))?\s+['\"]?(.+?)['\"]?$",
        cleaned,
        re.IGNORECASE,
    )
    if copy_direct_match:
        phrase = copy_direct_match.group(1).strip()
        if phrase:
            return Command(Action.COPY_TEXT, phrase)

    # 5. Click Nth search result or named search target
    if re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:most\s+relevant|top|best)\s+(?:search\s+)?(?:result|video|link)$",
        text_lower,
    ):
        return Command(Action.CLICK_RESULT, "1")

    # "click result one", "click result 1", "open result 1"
    result_num_match = re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:search\s+|relevant\s+)?(?:result|video|link)\s+(?:number\s+)?(\w+)$",
        text_lower,
    )
    if result_num_match:
        ordinal = result_num_match.group(1)
        if ordinal in RESULT_ORDINALS:
            return Command(Action.CLICK_RESULT, RESULT_ORDINALS[ordinal])

    # "click the first result", "click first result"
    result_match = re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:result\s+)?(\w+)(?:\s+(?:search|relevant|top|best))?(?:\s+result|\s+video|\s+link)$",
        text_lower,
    )
    if result_match and ("result" in text_lower or "video" in text_lower or "link" in text_lower):
        ordinal = result_match.group(1)
        if ordinal in RESULT_ORDINALS:
            return Command(Action.CLICK_RESULT, RESULT_ORDINALS[ordinal])

    # "search LangGraph and open the official repository" or "official repository" -> CLICK_RESULT("official repository")
    official_match = re.match(
        r"^(?:(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?)?official\s+(?:([\w\-]+)\s+)?(repository|repo|website|site|page|docs|documentation|link|result)$",
        text_lower,
    )
    if official_match:
        prefix = f"{official_match.group(1)} " if official_match.group(1) else ""
        return Command(Action.CLICK_RESULT, f"official {prefix}{official_match.group(2)}".strip())

    # "click the first element", "click first element", "click element 1", "click on first element"
    elem_ordinal_match = re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:(?:(\w+)\s+(?:clickable\s+)?(?:element|item))|(?:(?:clickable\s+)?(?:element|item)\s+(\w+)))$",
        text_lower,
    )
    if elem_ordinal_match:
        ord_token = elem_ordinal_match.group(1) or elem_ordinal_match.group(2)
        if ord_token in RESULT_ORDINALS:
            idx = RESULT_ORDINALS[ord_token]
            if state is not None and (
                getattr(state, "last_search_query", None)
                or (getattr(state, "current_site", None) in {"youtube", "google", "github"} and "search" in (getattr(state, "current_url", "") or "").lower())
            ):
                return Command(Action.CLICK_RESULT, idx)
            return Command(Action.CLICK_ELEMENT, f"element {idx}")

    # 6. Search commands (GitHub, YouTube, Google, or context-aware)
    gh_search = re.match(r"^search\s+(?:on\s+)?github\s+(?:for\s+)?(.+)$", cleaned, re.IGNORECASE)
    if gh_search:
        query = gh_search.group(1).strip()
        if not query:
            raise ValueError("No search query specified.")
        return Command(Action.SEARCH, f"github:{query}")

    yt_search = re.match(r"^search\s+(?:on\s+)?youtube\s+(?:for\s+)?(.+)$", cleaned, re.IGNORECASE)
    if yt_search:
        query = yt_search.group(1).strip()
        if not query:
            raise ValueError("No search query specified.")
        return Command(Action.SEARCH, f"youtube:{query}")

    google_search = re.match(r"^search\s+(?:on\s+)?google\s+(?:for\s+)?(.+)$", cleaned, re.IGNORECASE)
    if google_search:
        query = google_search.group(1).strip()
        if not query:
            raise ValueError("No search query specified.")
        return Command(Action.SEARCH, f"google:{query}")

    generic_search = re.match(r"^search\s+(?:for\s+)?(.+)$", cleaned, re.IGNORECASE)
    if generic_search:
        query = generic_search.group(1).strip()
        if not query:
            raise ValueError("No search query specified.")
        if state is not None and getattr(state, "current_site", None) == "youtube":
            return Command(Action.SEARCH, f"youtube:{query}")
        if state is not None and getattr(state, "current_site", None) == "github":
            return Command(Action.SEARCH, f"github:{query}")
        return Command(Action.SEARCH, query)

    # 7. Find element on page (only for direct element targets, not complex 'find ... on YouTube and ...' requests)
    if not re.search(r"\b(?:on\s+youtube|on\s+google|and\s+(?:open|click|search|scroll|play))\b", text_lower):
        find_match = re.match(
            r"^find\s+(?:the\s+)?(?:element\s+|text\s+|button\s+|link\s+)?(.+?)(?:\s+button|\s+link|\s+option)?$",
            cleaned,
            re.IGNORECASE,
        )
        if find_match:
            target = find_match.group(1).strip()
            if target:
                return Command(Action.FIND_ELEMENT, target)

    # 8. Click element vs simple mouse click
    if text_lower in {"click", "left click", "mouse click", "click mouse"}:
        return Command(Action.CLICK, None)

    click_elem_match = re.match(
        r"^click\s+(?:on\s+)?(?:the\s+)?(?:element\s+|button\s+|link\s+|option\s+)?(.+?)(?:\s+button|\s+link|\s+option)?$",
        cleaned,
        re.IGNORECASE,
    )
    if click_elem_match:
        target = click_elem_match.group(1).strip()
        if target.lower().startswith("the "):
            target = target[4:].strip()
        t_low = target.lower()

        # Guard: ordinal element targets must resolve to index, never literal text search
        ord_elem_m = re.match(
            r"^(?:the\s+)?(?:(?:(\w+)\s+(?:clickable\s+)?(?:element|item))|(?:(?:clickable\s+)?(?:element|item)\s+(\w+)))$",
            t_low,
        )
        if ord_elem_m:
            tok = ord_elem_m.group(1) or ord_elem_m.group(2)
            if tok in RESULT_ORDINALS:
                idx = RESULT_ORDINALS[tok]
                if state is not None and (
                    getattr(state, "last_search_query", None)
                    or (getattr(state, "current_site", None) in {"youtube", "google"} and "search" in (getattr(state, "current_url", "") or "").lower())
                ):
                    return Command(Action.CLICK_RESULT, idx)
                return Command(Action.CLICK_ELEMENT, f"element {idx}")

        if t_low in RESULT_ORDINALS:
            idx = RESULT_ORDINALS[t_low]
            if state is not None and (
                getattr(state, "last_search_query", None)
                or (getattr(state, "current_site", None) in {"youtube", "google"} and "search" in (getattr(state, "current_url", "") or "").lower())
            ):
                return Command(Action.CLICK_RESULT, idx)
            return Command(Action.CLICK_ELEMENT, f"element {idx}")

        if t_low not in {"mouse", "here"}:
            return Command(Action.CLICK_ELEMENT, target)

    # 9. Common websites, arbitrary URLs, & known applications
    for prefix in ("open ", "go to ", "navigate to ", "go for "):
        if text_lower.startswith(prefix):
            rest = cleaned[len(prefix):].strip()
            rest_lower = rest.lower()
            if not rest_lower:
                raise ValueError("No target specified to open.")

            if rest_lower in WEBSITES:
                return Command(Action.OPEN_URL, WEBSITES[rest_lower])

            if _is_valid_url_target(rest):
                return Command(Action.OPEN_URL, rest)

            if rest_lower.startswith(("http://", "https://", "www.")):
                raise ValueError(f"Invalid URL specified: '{rest}'")

            if prefix == "open " and rest_lower in KNOWN_APPS:
                return Command(Action.OPEN_APP, KNOWN_APPS[rest_lower])

    # 10. Close applications
    if text_lower.startswith("close "):
        app_target = cleaned[6:].strip()
        if not app_target:
            raise ValueError("No application specified.")
        return Command(Action.CLOSE_APP, KNOWN_APPS.get(app_target.lower(), app_target))

    # 11. Type text
    if text_lower.startswith("type "):
        type_target = cleaned[5:].strip()
        if not type_target:
            raise ValueError("No text specified.")
        return Command(Action.TYPE, type_target)

    # 12. Scroll up / down
    if text_lower in {"scroll down", "scroll page down", "page down"}:
        return Command(Action.SCROLL, "down")
    if text_lower in {"scroll up", "scroll page up", "page up"}:
        return Command(Action.SCROLL, "up")

    # 13. Move mouse / cursor / hover
    move_match = re.match(
        r"^(?:move\s+(?:the\s+)?(?:mouse|cursor)|hover|point)(?:\s+(?:to|onto|over|on|at|towards))?\s*(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if move_match:
        move_target = move_match.group(1).strip()
        if not move_target:
            move_target = "center"
        return Command(Action.MOVE_MOUSE, move_target)

    natural_move_target = _normalise_spoken_relative_move(cleaned)
    if natural_move_target is not None:
        return Command(Action.MOVE_MOUSE, natural_move_target)

    # 14. Wait
    if text_lower == "wait" or text_lower.startswith("wait "):
        digits = re.findall(r"\d+", text_lower)
        seconds = digits[0] if digits else "2"
        return Command(Action.WAIT, seconds)

    return None


def extract_target(text: str, action: Action) -> str | None:
    """Extract the target argument from raw text for a given Action."""
    cleaned = preprocess_text(text)
    text_lower = cleaned.lower()

    if action == Action.OPEN_APP:
        if not text_lower.startswith("open "):
            return None
        return cleaned[5:].strip()

    if action == Action.CLOSE_APP:
        if not text_lower.startswith("close "):
            return None
        return cleaned[6:].strip()

    if action == Action.OPEN_URL:
        if re.search(r"\bofficial\s+(?:repository|repo|website|site|page|docs|documentation|link|result)\b", text_lower):
            return None
        for prefix in ("open ", "go to ", "navigate to "):
            if text_lower.startswith(prefix):
                return cleaned[len(prefix):].strip()
        return None

    if action == Action.TYPE:
        if not text_lower.startswith("type "):
            return None
        return cleaned[5:].strip()

    if action == Action.PRESS_KEY:
        if text_lower.startswith("press "):
            return cleaned[6:].strip().lower()
        if text_lower.startswith("hit "):
            return cleaned[4:].strip().lower()
        return cleaned.lower()

    if action == Action.SCROLL:
        if "down" in text_lower:
            return "down"
        if "up" in text_lower:
            return "up"
        return None

    if action == Action.MOVE_MOUSE:
        move_match = re.match(
            r"^(?:move\s+(?:the\s+)?(?:mouse|cursor)|hover|point)(?:\s+(?:to|onto|over|on|at|towards))?\s*(.*)$",
            cleaned,
            re.IGNORECASE,
        )
        if move_match:
            rest = move_match.group(1).strip()
            return rest or "center"
        return _normalise_spoken_relative_move(cleaned)

    if action == Action.WAIT:
        digits = re.findall(r"\d+", text_lower)
        return digits[0] if digits else "2"

    if action == Action.HOTKEY:
        return _parse_hotkey(cleaned)

    if action == Action.SWITCH_WINDOW:
        switch_match = re.match(r"^switch\s+(?:window\s+)?to\s+(.+)$", cleaned, re.IGNORECASE)
        return switch_match.group(1).strip() if switch_match else None

    if action in {
        Action.MINIMIZE_WINDOW,
        Action.MAXIMIZE_WINDOW,
        Action.RESTORE_WINDOW,
        Action.SHOW_DESKTOP,
        Action.MEDIA_PLAY_PAUSE,
        Action.MEDIA_FULLSCREEN,
        Action.MEDIA_EXIT_FULLSCREEN,
        Action.MEDIA_MUTE,
        Action.MEDIA_VOLUME_UP,
        Action.MEDIA_VOLUME_DOWN,
        Action.MEDIA_NEXT,
        Action.MEDIA_PREVIOUS,
    }:
        return None

    if action == Action.MEDIA_FORWARD:
        fwd_match = re.search(r"\b(\d+)\b", cleaned)
        return fwd_match.group(1) if fwd_match else "10"

    if action == Action.MEDIA_BACKWARD:
        bwd_match = re.search(r"\b(\d+)\b", cleaned)
        return bwd_match.group(1) if bwd_match else "10"

    if action == Action.AGENT_TASK:
        return cleaned

    return None


def validate_command(text: str, command: Command) -> Command:
    """
    Validate a Laya-predicted Command so random speech never causes
    accidental computer or browser actions.
    """
    cleaned = preprocess_text(text)
    text_lower = cleaned.lower()
    action = command.action
    target = command.target

    if action == Action.STOP:
        raise ValueError(
            "Laya predicted STOP, but the command was not an explicit stop command."
        )

    if action == Action.OPEN_APP:
        if not text_lower.startswith("open "):
            raise ValueError(
                "Laya predicted OPEN_APP, but the command does not start with 'open'."
            )
        if not target:
            raise ValueError("No application specified.")

    elif action == Action.CLOSE_APP:
        if not text_lower.startswith("close "):
            raise ValueError(
                "Laya predicted CLOSE_APP, but the command does not start with 'close'."
            )
        if not target:
            raise ValueError("No application specified.")

    elif action == Action.OPEN_URL:
        if not text_lower.startswith(("open ", "go to ", "navigate to ")):
            raise ValueError(
                "Laya predicted OPEN_URL, but the command does not look like a URL command."
            )
        if re.search(r"\bofficial\s+(?:[\w\-]+\s+)?(?:repository|repo|website|site|page|docs|documentation|link|result)\b", text_lower):
            raise ValueError(
                f"Laya predicted OPEN_URL for search result phrase: '{text}'. Redirect to CLICK_RESULT."
            )
        if not target or not (_is_valid_url_target(target) or target.lower() in WEBSITES):
            raise ValueError(f"Invalid or missing URL target: '{target}'")

    elif action == Action.TYPE:
        if not text_lower.startswith("type "):
            raise ValueError(
                "Laya predicted TYPE, but the command does not start with 'type'."
            )
        if not target:
            raise ValueError("No text specified.")

    elif action == Action.PRESS_KEY:
        if not text_lower.startswith(("press ", "hit ")) and text_lower not in KEY_COMMANDS:
            raise ValueError(
                "Laya predicted PRESS_KEY, but the command is not a valid key command."
            )
        if not target:
            raise ValueError("No key specified.")

    elif action == Action.HOTKEY:
        if not target:
            raise ValueError("No hotkey combination specified.")

    elif action == Action.AGENT_TASK:
        if not target:
            raise ValueError("No agent task specified.")

    elif action == Action.CLICK:
        if "click" not in text_lower:
            raise ValueError(
                "Laya predicted CLICK, but 'click' was not in the command."
            )

    elif action == Action.SCROLL:
        if "scroll" not in text_lower or target not in {"up", "down"}:
            raise ValueError("Invalid scroll command or direction.")

    elif action == Action.MOVE_MOUSE:
        explicit_move = re.match(
            r"^(?:move\s+(?:the\s+)?(?:mouse|cursor)|hover|point)\b",
            text_lower,
        )
        if not explicit_move and _normalise_spoken_relative_move(cleaned) is None:
            raise ValueError(
                "Laya predicted MOVE_MOUSE, but the command is not a safe mouse movement phrase."
            )

    elif action == Action.WAIT:
        if not text_lower.startswith("wait"):
            raise ValueError(
                "Laya predicted WAIT, but the command does not start with 'wait'."
            )

    return command
