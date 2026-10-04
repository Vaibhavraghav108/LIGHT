import re
import time
import pyautogui
from computer.platform_factory import get_platform_controller

# Enable DPI awareness across platforms
get_platform_controller().set_dpi_awareness()

# Prevent PyAutoGUI from raising FailSafeException when the user's cursor
# happens to be resting in a screen corner before a voice command runs.
pyautogui.FAILSAFE = False


SMALL_WORDS = {"a little", "little", "slightly", "a bit", "bit", "tiny bit", "nudge", "short"}
LARGE_WORDS = {"a lot", "far", "way", "much", "big"}

DIRECTION_VECTORS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


class MouseController:

    DEFAULT_STEP = 150
    SMALL_STEP = 45
    LARGE_STEP = 300
    SCREEN_MARGIN = 5

    def __init__(self, platform=None):
        self.platform = platform if platform is not None else get_platform_controller()
        self._last_known_pos: tuple[int, int] = (0, 0)

    def get_screen_size(self) -> tuple[int, int]:
        width, height = pyautogui.size()
        return int(width), int(height)

    def clamp_to_screen(self, x: int | float, y: int | float) -> tuple[int, int]:
        """Ensure coordinates never leave the physical screen boundaries."""
        width, height = self.get_screen_size()
        margin = self.SCREEN_MARGIN
        clamped_x = max(margin, min(int(round(x)), width - margin - 1))
        clamped_y = max(margin, min(int(round(y)), height - margin - 1))
        return clamped_x, clamped_y

    def get_position(self) -> tuple[int, int]:
        """Return the actual current OS mouse cursor coordinates (x, y)."""
        pos = pyautogui.position()
        px, py = int(pos[0]), int(pos[1])
        if (px, py) != (0, 0):
            self._last_known_pos = (px, py)
            return px, py
        # If (0, 0), consult platform fallback
        fallback = self.platform.get_cursor_position_fallback(self._last_known_pos)
        if fallback != (0, 0):
            return fallback
        return px, py

    def verify_and_correct_position(
        self,
        target_x: int | float,
        target_y: int | float,
        tolerance: int = 5,
    ) -> tuple[int, int]:
        """
        Verify that the physical OS cursor is within `tolerance` pixels of `(target_x, target_y)`.
        If outside tolerance, re-move the cursor to the clamped target before clicking.
        """
        clamped_x, clamped_y = self.clamp_to_screen(target_x, target_y)
        try:
            cur_x, cur_y = self.get_position()
            if abs(cur_x - clamped_x) > tolerance or abs(cur_y - clamped_y) > tolerance:
                pyautogui.moveTo(clamped_x, clamped_y, duration=0.04)
                self._last_known_pos = (clamped_x, clamped_y)
                cur_x, cur_y = self.get_position()
            return cur_x, cur_y
        except Exception:
            return clamped_x, clamped_y

    def click(self):
        """Left-click at the current mouse position."""
        pyautogui.click()

    def click_at(
        self,
        x: int | float | None = None,
        y: int | float | None = None,
        settle_delay: float = 0.035,
        hold_delay: float = 0.025,
        tolerance: int = 5,
    ) -> tuple[int, int]:
        """
        Verify cursor position at `(x, y)`, wait a brief stabilization delay (`settle_delay`),
        and perform a physical OS left-click (`mouseDown` + `mouseUp`).
        """
        if x is not None and y is not None:
            final_x, final_y = self.verify_and_correct_position(x, y, tolerance=tolerance)
        else:
            try:
                final_x, final_y = self.get_position()
            except Exception:
                final_x, final_y = (0, 0)

        if settle_delay > 0:
            time.sleep(settle_delay)

        try:
            pyautogui.mouseDown(x=final_x, y=final_y, button="left")
            if hold_delay > 0:
                time.sleep(hold_delay)
            pyautogui.mouseUp(x=final_x, y=final_y, button="left")
        except Exception:
            pyautogui.click(x=final_x, y=final_y)

        return final_x, final_y

    def scroll(self, direction: str):
        """Scroll up or down."""
        direction = direction.lower().strip()

        if direction == "down":
            pyautogui.scroll(-5)
        elif direction == "up":
            pyautogui.scroll(5)
        else:
            raise ValueError(f"Unknown scroll direction: {direction}")

    def move(self, x: int | float, y: int | float, duration: float = 0.3):
        """Smoothly move the physical cursor to clamped screen coordinates (x, y)."""
        clamped_x, clamped_y = self.clamp_to_screen(x, y)
        pyautogui.moveTo(clamped_x, clamped_y, duration=duration)
        self._last_known_pos = (clamped_x, clamped_y)
        return clamped_x, clamped_y

    def move_relative(self, dx: int | float, dy: int | float, duration: float = 0.25):
        """Move the mouse relative to its current position while staying inside screen bounds."""
        cur_x, cur_y = pyautogui.position()
        return self.move(cur_x + dx, cur_y + dy, duration=duration)

    def parse_relative_or_screen_command(self, target: str) -> dict | None:
        """
        Parse relative movement ('a little left', '100 pixels right', 'slightly up')
        or screen positions ('center', '500 500').
        Returns a dict describing the movement or None if target is a named UI element.
        """
        if not target:
            return None

        cleaned = target.lower().strip()
        for prefix in ("to the ", "to ", "onto the ", "onto ", "towards "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        # 1. Screen center / named corners
        if cleaned in {"center", "middle", "screen center", "the center", "the middle"}:
            width, height = self.get_screen_size()
            return {"mode": "absolute", "x": width // 2, "y": height // 2}

        if cleaned in {"top left", "upper left"}:
            return {"mode": "absolute", "x": 50, "y": 50}
        if cleaned in {"top right", "upper right"}:
            width, _ = self.get_screen_size()
            return {"mode": "absolute", "x": width - 50, "y": 50}
        if cleaned in {"bottom left", "lower left"}:
            _, height = self.get_screen_size()
            return {"mode": "absolute", "x": 50, "y": height - 50}
        if cleaned in {"bottom right", "lower right"}:
            width, height = self.get_screen_size()
            return {"mode": "absolute", "x": width - 50, "y": height - 50}

        # 2. Explicit (x, y) screen coordinates like "500 500" or "500, 500"
        coord_match = re.match(r"^(-?\d+)\s*[,\s]\s*(-?\d+)$", cleaned)
        if coord_match:
            return {
                "mode": "absolute",
                "x": int(coord_match.group(1)),
                "y": int(coord_match.group(2)),
            }

        # 3. Pixel-distance directional movement:
        # e.g., "100 pixels right", "50 px down", "right 100 pixels", "move 80 pixels up"
        px_first = re.match(
            r"^(?:by\s+)?(\d+)\s*(?:pixels?|px)?\s*(?:to\s+the\s+|to\s+)?(up|down|left|right)$",
            cleaned,
        )
        px_second = re.match(
            r"^(up|down|left|right)\s+(?:by\s+)?(\d+)\s*(?:pixels?|px)?$",
            cleaned,
        )
        if px_first or px_second:
            if px_first:
                distance = int(px_first.group(1))
                direction = px_first.group(2)
            else:
                direction = px_second.group(1)
                distance = int(px_second.group(2))

            vx, vy = DIRECTION_VECTORS[direction]
            return {"mode": "relative", "dx": vx * distance, "dy": vy * distance}

        # 4. Qualitative directional movement:
        # e.g., "left", "a little left", "slightly up", "a bit right", "far down"
        for direction, (vx, vy) in DIRECTION_VECTORS.items():
            if cleaned == direction or cleaned.endswith(f" {direction}") or cleaned.startswith(f"{direction} "):
                modifier = cleaned.replace(direction, "").strip()
                modifier = re.sub(r"\b(to|the|towards|in|direction)\b", "", modifier).strip()

                if not modifier:
                    step = self.DEFAULT_STEP
                elif any(w in modifier for w in SMALL_WORDS):
                    step = self.SMALL_STEP
                elif any(w in modifier for w in LARGE_WORDS):
                    step = self.LARGE_STEP
                else:
                    # Fallback if unknown words are attached (likely a UI element name containing "up"/"down")
                    continue

                return {"mode": "relative", "dx": vx * step, "dy": vy * step}

        return None

    def can_handle_directly(self, target: str) -> bool:
        """Return True if target is a relative move or screen coordinate rather than a DOM element."""
        return self.parse_relative_or_screen_command(target) is not None

    def move_by_command(self, target: str):
        """Execute a relative or coordinate-based mouse movement command."""
        if not target:
            raise ValueError("No mouse movement target specified.")

        parsed = self.parse_relative_or_screen_command(target)
        if parsed is None:
            raise ValueError(f"Unsupported mouse move target: {target}")

        if parsed["mode"] == "absolute":
            return self.move(parsed["x"], parsed["y"])

        return self.move_relative(parsed["dx"], parsed["dy"])