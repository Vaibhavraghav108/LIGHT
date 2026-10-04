import random
import time

import pyautogui
from computer.platform_factory import get_platform_controller

KEY_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "arrow up": "up",
    "arrow down": "down",
    "arrow left": "left",
    "arrow right": "right",
    "up arrow": "up",
    "down arrow": "down",
    "left arrow": "left",
    "right arrow": "right",
    "page up": "pageup",
    "page down": "pagedown",
}


class KeyboardController:

    def __init__(self, platform=None):
        self.platform = platform if platform is not None else get_platform_controller()

    def type_text(self, text: str):
        """
        Type text character-by-character with a small
        randomized delay, similar to human typing.
        """
        for char in text:
            pyautogui.write(char)

            # Human-like typing delay
            time.sleep(random.uniform(0.03, 0.12))

    def press(self, key: str):
        """
        Press a keyboard key.
        """
        normalized = key.lower().strip()
        normalized = KEY_ALIASES.get(normalized, normalized)
        pyautogui.press(normalized)

    def hotkey(self, *keys: str):
        """Press a keyboard shortcut in the currently focused application."""
        if not keys:
            raise ValueError("At least one key is required.")
        mapped = self.platform.map_hotkey(*keys)
        normalized = [KEY_ALIASES.get(k.lower().strip(), k.lower().strip()) for k in mapped]
        pyautogui.hotkey(*normalized)
