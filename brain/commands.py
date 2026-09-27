from dataclasses import dataclass
from enum import Enum


class Action(Enum):
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    GO_BACK = "go_back"
    GO_FORWARD = "go_forward"
    REFRESH = "refresh"
    SEARCH = "search"
    CLICK_RESULT = "click_result"
    CLICK_ELEMENT = "click_element"
    FIND_ELEMENT = "find_element"
    READ_TITLE = "read_title"
    READ_TEXT = "read_text"
    COPY_TEXT = "copy_text"
    PASTE = "paste"
    TYPE = "type"
    CLICK = "click"
    SCROLL = "scroll"
    PRESS_KEY = "press_key"
    MOVE_MOUSE = "move_mouse"
    WAIT = "wait"
    STOP = "stop"


@dataclass
class Command:
    action: Action
    target: str | None = None