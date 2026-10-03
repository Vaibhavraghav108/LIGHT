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
    HOTKEY = "hotkey"
    SWITCH_WINDOW = "switch_window"
    MINIMIZE_WINDOW = "minimize_window"
    MAXIMIZE_WINDOW = "maximize_window"
    RESTORE_WINDOW = "restore_window"
    SHOW_DESKTOP = "show_desktop"
    MEDIA_PLAY_PAUSE = "media_play_pause"
    MEDIA_FORWARD = "media_forward"
    MEDIA_BACKWARD = "media_backward"
    MEDIA_FULLSCREEN = "media_fullscreen"
    MEDIA_EXIT_FULLSCREEN = "media_exit_fullscreen"
    MEDIA_MUTE = "media_mute"
    MEDIA_VOLUME_UP = "media_volume_up"
    MEDIA_VOLUME_DOWN = "media_volume_down"
    MEDIA_NEXT = "media_next"
    MEDIA_PREVIOUS = "media_previous"
    AGENT_TASK = "agent_task"
    MOVE_MOUSE = "move_mouse"
    WAIT = "wait"
    STOP = "stop"


@dataclass
class Command:
    action: Action
    target: str | None = None