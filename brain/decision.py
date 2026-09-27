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


_CONVERSATIONAL_PREFIX_RE = re.compile(
    r"^(?:(?:okay|ok|alright|all\s+right|please|hey\s+light|light|now|well|so)\s+)+(?=(?:click|open|close|search|find|move|hover|point|scroll|go|navigate|read|copy|select|paste|type|press|hit|wait|stop|exit|quit|refresh|reload|back|forward)\b)",
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
        "copy from",
        "select from",
    }:
        raise ValueError(f"Incomplete command: '{cleaned}'")

    # 1. Explicit STOP commands
    if text_lower in STOP_COMMANDS:
        return Command(Action.STOP, None)

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

    if text_lower.startswith(("copy from ", "select from ")):
        raise ValueError(
            "Incomplete copy-range command. Expected: 'copy from <start> till <end>'."
        )

    # 5. Click Nth search result
    result_match = re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:result\s+)?(\w+)(?:\s+search)?(?:\s+result|\s+video|\s+link)?$",
        text_lower,
    )
    if result_match and ("result" in text_lower or "video" in text_lower):
        ordinal = result_match.group(1)
        if ordinal in RESULT_ORDINALS:
            return Command(Action.CLICK_RESULT, RESULT_ORDINALS[ordinal])

    result_num_match = re.match(
        r"^(?:click|open|select)\s+(?:on\s+)?(?:the\s+)?(?:search\s+)?(?:result|video)\s+(?:number\s+)?(\w+)$",
        text_lower,
    )
    if result_num_match:
        ordinal = result_num_match.group(1)
        if ordinal in RESULT_ORDINALS:
            return Command(Action.CLICK_RESULT, RESULT_ORDINALS[ordinal])

    # 6. Search commands (Google, YouTube, or context-aware)
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
        return Command(Action.SEARCH, query)

    # 7. Find element on page
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
        if target.lower() not in {"mouse", "here"}:
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
