import re
import threading
import time

from brain.commands import Action, Command
from brain.decision import RESULT_ORDINALS
from browser.browser import BrowserController
from browser.agent import AutonomousBrowserAgent
from computer.apps import AppController
from computer.keyboard import KeyboardController
from computer.mouse import MouseController
from computer.screen import ScreenController
from config import DEFAULT_WAIT_SECONDS
from core.state import LightState, BrowserOwnership
from core.tasks import TaskStatus
from core.queue_manager import CommandStatus
from utils.logger import log_executor

class Executor:

    def __init__(self, state: LightState | None = None, ai_provider=None):
        self.apps = AppController()
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.browser = BrowserController()
        self.browser_agent = AutonomousBrowserAgent(ai_provider=ai_provider)
        self.screen = ScreenController()
        self.state = state if state is not None else LightState()
        self.last_verification_ms: float = 0.0
        self.last_stop_interrupt_ms: float = 0.0
        self._agent_thread: threading.Thread | None = None
        self._agent_lock = threading.Lock()
        self.last_agent_result: str | None = None
        self.last_agent_error: str | None = None
        self._closing = threading.Event()
        self._agent_cancel_event = None
        self.verification_started_at = 0.0
        self.verification_completed_at = 0.0

    def _sleep_interruptible(self, seconds: float, cancel_event=None):
        """
        Wait for `seconds` while remaining immediately interruptible (<5ms)
        by `cancel_event.set()` when STOP/Cancel is spoken.
        """
        if seconds <= 0:
            return
        if cancel_event is None:
            time.sleep(seconds)
            return

        t0 = time.perf_counter()
        if cancel_event.wait(timeout=seconds):
            self.last_stop_interrupt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            log_executor(f"WAIT interrupted by STOP/Cancel after {self.last_stop_interrupt_ms}ms.")

    def _verify_and_recover(self, command: Command, cancel_event=None):
        """
        Lightweight OBSERVE -> ACT -> VERIFY -> RECOVER checks for browser operations.
        Never adds heavy artificial delays.
        """
        v_start = time.perf_counter()
        try:
            action = command.action
            if action in {
                Action.OPEN_URL,
                Action.SEARCH,
                Action.CLICK_RESULT,
                Action.CLICK_ELEMENT,
                Action.GO_BACK,
                Action.GO_FORWARD,
                Action.REFRESH,
            }:
                self.verification_started_at = v_start
                if cancel_event is not None and cancel_event.is_set():
                    return
                if not self.browser.is_active():
                    # Recover if browser session dropped unexpectedly
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    self.browser.start()
                if cancel_event is not None and cancel_event.is_set():
                    return
                current_url = self.browser.get_current_url()
                if action == Action.OPEN_URL and not current_url and command.target:
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    self.browser.open_url(command.target)
                self.verification_completed_at = time.perf_counter()
        finally:
            self.last_verification_ms = round((time.perf_counter() - v_start) * 1000.0, 2)

    def execute(
        self,
        command: Command,
        raw_text: str | None = None,
        cancel_event=None,
        request=None,
    ) -> str:
        action = command.action
        target = command.target
        self.last_verification_ms = 0.0
        self.verification_started_at = 0.0
        self.verification_completed_at = 0.0
        if action != Action.STOP and (self._closing.is_set() or
                                      (cancel_event is not None and cancel_event.is_set())):
            return "CANCELLED"

        # ==========================================
        # APPLICATIONS
        # ==========================================

        if action == Action.OPEN_APP:
            if target and target.lower().strip() in {
                "brave",
                "brave browser",
                "chrome",
                "google chrome",
            }:
                self.browser.start()
                self.screen.wait_for_window_and_focus("chrome", timeout=2.0)
                self.state.current_browser = "chrome"
                self.state.current_app = "chrome"
                self.state.browser_open = True
                log_executor("Started Playwright Chromium/Chrome browser session.")
            else:
                self.apps.open(target, wait_and_focus=True, screen_controller=self.screen)
                canonical = self.apps._canonical_app_key(target)
                self.state.current_app = canonical
                fg = self.screen.get_foreground_window_info()
                self.state.active_window = fg.get("title") or canonical
                log_executor(f"Opened {canonical} and verified in foreground.")

        elif action == Action.CLOSE_APP:
            if target and any(b in target.lower() for b in ("brave", "chrome")):
                self.browser.close()
                self.state.browser_open = False
                self.state.current_browser = None
            else:
                self.apps.close(target)

        # ==========================================
        # KEYBOARD & HOTKEYS
        # ==========================================

        elif action == Action.TYPE:
            is_browser_fg = self.screen.is_browser_foreground(self.browser)
            if is_browser_fg and self.browser.is_active():
                if not self.browser.type_in_browser(target):
                    self.keyboard.type_text(target)
            else:
                self.keyboard.type_text(target)

        elif action == Action.PRESS_KEY:
            self.keyboard.press(target)

        elif action == Action.HOTKEY:
            if not target:
                raise ValueError("No keys specified for hotkey.")
            keys = [k.strip() for k in target.replace("+", " ").replace(",", " ").split() if k.strip()]
            self.keyboard.hotkey(*keys)

        # ==========================================
        # WINDOW CONTROL
        # ==========================================

        elif action == Action.SWITCH_WINDOW:
            if not target:
                raise ValueError("No target window specified.")
            success = self.screen.switch_to_window(target)
            if not success:
                raise RuntimeError(f"Window matching '{target}' was not found.")
            self.state.current_app = target.lower().strip()
            fg = self.screen.get_foreground_window_info()
            self.state.active_window = fg.get("title") or target

        elif action == Action.MINIMIZE_WINDOW:
            self.screen.minimize_foreground_window()

        elif action == Action.MAXIMIZE_WINDOW:
            self.screen.maximize_foreground_window()

        elif action == Action.RESTORE_WINDOW:
            self.screen.restore_foreground_window()

        elif action == Action.SHOW_DESKTOP:
            self.screen.show_desktop()

        # ==========================================
        # MOUSE & SCROLL
        # ==========================================

        elif action == Action.CLICK:
            self.mouse.click()

        elif action == Action.SCROLL:
            if self.browser.is_active():
                self.browser.scroll(target)
            elif request is not None and getattr(request, "capability_plan", None) is not None:
                # A browser-only capability must never fall through to desktop effects.
                raise RuntimeError("Browser scroll capability requires an active browser")
            else:
                self.mouse.scroll(target)

        elif action == Action.MOVE_MOUSE:
            if not target:
                raise ValueError("No mouse movement target specified.")

            if self.mouse.can_handle_directly(target):
                self.mouse.move_by_command(target)
            else:
                self.browser.move_mouse_to_element(target, self.mouse)

        # ==========================================
        # PLAYWRIGHT CHROMIUM / CHROME AUTOMATION
        # ==========================================

        elif action == Action.OPEN_URL:
            self.browser.open_url(target)

        elif action == Action.GO_BACK:
            self.browser.go_back()

        elif action == Action.GO_FORWARD:
            self.browser.go_forward()

        elif action == Action.REFRESH:
            self.browser.refresh()

        elif action == Action.SEARCH:
            if not target:
                raise ValueError("No search query provided.")

            if target.lower().startswith("youtube:"):
                query = target[8:].strip()
                self.browser.search(query, engine="youtube")
            elif target.lower().startswith("google:"):
                query = target[7:].strip()
                self.browser.search(query, engine="google")
            elif target.lower().startswith("github:"):
                query = target[7:].strip()
                self.browser.search(query, engine="github")
            elif self.state.current_site == "youtube":
                self.browser.search(target, engine="youtube")
            elif self.state.current_site == "github":
                self.browser.search(target, engine="github")
            else:
                self.browser.search(target)

        elif action == Action.CLICK_RESULT:
            if (
                self.state.last_status == "ERROR"
                and self.state.last_action in {Action.SEARCH, Action.OPEN_URL}
            ):
                raise RuntimeError(
                    f"Cannot execute CLICK_RESULT because prerequisite {self.state.last_action.name} failed."
                )
            search_context = self.state.last_search_query
            target_str = str(target).strip() if target is not None else "1"
            if target_str.isdigit() or target_str.lower() in RESULT_ORDINALS:
                index = int(target_str) if target_str.isdigit() else RESULT_ORDINALS.get(target_str.lower(), 1)
                try:
                    kwargs = {"mouse_controller": self.mouse}
                    if cancel_event is not None:
                        kwargs["cancel_event"] = cancel_event
                    self.browser.click_result(index, **kwargs)
                except TypeError:
                    self.browser.click_result(index)
            else:
                try:
                    kwargs = {
                        "mouse_controller": self.mouse,
                        "search_context": search_context,
                    }
                    if cancel_event is not None:
                        kwargs["cancel_event"] = cancel_event
                    self.browser.click_result(target, **kwargs)
                except TypeError:
                    self.browser.click_result(target, mouse_controller=self.mouse)

        elif action == Action.CLICK_ELEMENT:
            t_low = (target or "").strip().lower()
            ord_elem_m = re.match(
                r"^(?:the\s+)?(?:(?:(\w+)\s+(?:clickable\s+)?(?:element|item))|(?:(?:clickable\s+)?(?:element|item)\s+(\w+)))$",
                t_low,
            )
            if ord_elem_m:
                tok = ord_elem_m.group(1) or ord_elem_m.group(2)
                if tok in RESULT_ORDINALS:
                    idx = RESULT_ORDINALS[tok]
                    if self.state is not None and (
                        getattr(self.state, "last_search_query", None)
                        or (getattr(self.state, "current_site", None) in {"youtube", "google", "github"} and "search" in (getattr(self.state, "current_url", "") or "").lower())
                    ):
                        return self.execute(Command(Action.CLICK_RESULT, idx), raw_text=raw_text, cancel_event=cancel_event)
                    target = f"element {idx}"
            elif t_low in RESULT_ORDINALS:
                idx = RESULT_ORDINALS[t_low]
                if self.state is not None and (
                    getattr(self.state, "last_search_query", None)
                    or (getattr(self.state, "current_site", None) in {"youtube", "google", "github"} and "search" in (getattr(self.state, "current_url", "") or "").lower())
                ):
                    return self.execute(Command(Action.CLICK_RESULT, idx), raw_text=raw_text, cancel_event=cancel_event)
                target = f"element {idx}"
            try:
                self.browser.click_element(target, mouse_controller=self.mouse)
            except TypeError:
                self.browser.click_element(target)

        elif action == Action.FIND_ELEMENT:
            found = self.browser.find_element(target)
            if not found:
                raise RuntimeError(f"Element not found on page: '{target}'")

        elif action == Action.READ_TITLE:
            if self.browser.is_active():
                self.browser.get_title()
            else:
                title = self.screen.get_active_window_title() or "Unknown Window"
                log_executor(f"Active window title: {title}")

        elif action == Action.READ_TEXT:
            self.browser.get_visible_text()

        elif action == Action.COPY_TEXT:
            if self.browser.is_active() or target:
                self.browser.copy_text_range(target)
            else:
                self.keyboard.hotkey("ctrl", "c")

        elif action == Action.PASTE:
            self.keyboard.hotkey("ctrl", "v")

        # ==========================================
        # MEDIA CONTROLS
        # ==========================================

        elif action == Action.MEDIA_PLAY_PAUSE:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_play_pause()
            else:
                import pyautogui
                pyautogui.press("playpause")

        elif action == Action.MEDIA_FORWARD:
            seconds = 10.0
            if target:
                try:
                    seconds = float(target)
                except ValueError:
                    seconds = 10.0
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_seek(seconds)
            else:
                import pyautogui
                pyautogui.press("right")

        elif action == Action.MEDIA_BACKWARD:
            seconds = 10.0
            if target:
                try:
                    seconds = float(target)
                except ValueError:
                    seconds = 10.0
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_seek(-seconds)
            else:
                import pyautogui
                pyautogui.press("left")

        elif action == Action.MEDIA_FULLSCREEN:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_fullscreen(True)
            else:
                import pyautogui
                pyautogui.press("f")

        elif action == Action.MEDIA_EXIT_FULLSCREEN:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_fullscreen(False)
            else:
                import pyautogui
                pyautogui.press("escape")

        elif action == Action.MEDIA_MUTE:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_mute()
            else:
                import pyautogui
                pyautogui.press("volumemute")

        elif action == Action.MEDIA_VOLUME_UP:
            import pyautogui
            pyautogui.press("volumeup", presses=2)

        elif action == Action.MEDIA_VOLUME_DOWN:
            import pyautogui
            pyautogui.press("volumedown", presses=2)

        elif action == Action.MEDIA_NEXT:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_next()
            else:
                import pyautogui
                pyautogui.press("nexttrack")

        elif action == Action.MEDIA_PREVIOUS:
            if self.screen.is_browser_foreground(self.browser) or self.browser.has_video_element():
                self.browser.media_previous()
            else:
                import pyautogui
                pyautogui.press("prevtrack")

        # ==========================================
        # AUTONOMOUS AGENT TASK
        # ==========================================

        elif action == Action.AGENT_TASK:
            if cancel_event is not None and cancel_event.is_set():
                log_executor("Agent task cancelled before start: CANCELLED")
                return "CANCELLED"

            agent_cancel_event = cancel_event if cancel_event is not None else self._closing

            def _agent_worker():
                try:
                    log_executor(f"[AGENT_TASK] Background worker started for: '{target}'")
                    res = self.browser_agent.run_task(task_instruction=target, cancel_event=agent_cancel_event)
                    final_res = res.get("final_result", "") if isinstance(res, dict) else str(res)
                    is_cancelled = res.get("cancelled", False) if isinstance(res, dict) else (final_res == "CANCELLED")
                    is_success = (
                        res.get("success", False)
                        if isinstance(res, dict)
                        else (final_res.startswith("AGENT_COMPLETED") if isinstance(final_res, str) else False)
                    )
                    is_cancelled = is_cancelled or agent_cancel_event.is_set()

                    if is_cancelled:
                        self.last_agent_result = "CANCELLED"
                        log_executor(f"Agent task cancelled: {final_res}")
                    elif not is_success:
                        self.last_agent_result = "FAILED"
                        self.last_agent_error = final_res or "Agent task failed to complete goal."
                        log_executor(f"Agent task failed: {final_res}")
                    else:
                        self.last_agent_result = "COMPLETED"
                        self.last_agent_error = None
                        log_executor(f"Agent task completed: {final_res}")
                except Exception as err:
                    self.last_agent_result = "ERROR"
                    self.last_agent_error = str(err)
                    log_executor(f"Agent task unhandled error: {err}")
                finally:
                    if request is not None:
                        request.execution_completed_at = time.perf_counter()
                        if request.task:
                            request.task.mark("execution_finished", request.execution_completed_at)
                            request.task.mark("agent_terminated", request.execution_completed_at)
                        if agent_cancel_event.is_set() or self.last_agent_result == "CANCELLED":
                            request.cancel("Agent cancelled")
                        elif self.last_agent_result == "COMPLETED":
                            request.status = CommandStatus.COMPLETED
                            if request.task:
                                request.task.finish_step()  # agent-reported, not independently verified
                        else:
                            request.status = CommandStatus.FAILED
                            if request.task:
                                request.task.fail(TaskStatus.FAILED, "Agent execution failed")
                    with self.state._lock:
                        self.state.agent_running = False
                        try:
                            browser_active = bool(
                                self.browser and hasattr(self.browser, "is_active") and self.browser.is_active()
                            )
                        except Exception:
                            browser_active = False
                        if browser_active and not self._closing.is_set():
                            self.state.set_browser_ownership(BrowserOwnership.LIGHT)
                        else:
                            self.state.set_browser_ownership(BrowserOwnership.NONE)

            worker_thread = threading.Thread(
                target=_agent_worker,
                name="LIGHT-AgentWorker",
                daemon=True,
            )
            with self._agent_lock:
                if self.state.agent_running or (self._agent_thread is not None and self._agent_thread.is_alive()):
                    log_executor(
                        f"[AGENT_TASK] Duplicate agent task rejected: an autonomous agent task is already active. Ignoring '{target}'."
                    )
                    return "REJECTED"
                with self.state._lock:
                    self.state.agent_running = True
                    self.state.set_browser_ownership(BrowserOwnership.AGENT)
                self.last_agent_result = None
                self.last_agent_error = None
                self._agent_cancel_event = agent_cancel_event
                self._agent_thread = worker_thread
                worker_thread.start()
            self.state.record_command(raw_text, command)
            return "OK"

        # ==========================================
        # WAIT
        # ==========================================

        elif action == Action.WAIT:
            seconds = float(target) if target else DEFAULT_WAIT_SECONDS
            log_executor(f"Waiting {seconds} seconds...")
            self._sleep_interruptible(seconds, cancel_event=cancel_event)
            if cancel_event is not None and cancel_event.is_set():
                return "CANCELLED"
            self.state.record_command(raw_text, command)
            return "OK"

        # ==========================================
        # STOP
        # ==========================================

        elif action == Action.STOP:
            self._closing.set()
            if self._agent_cancel_event is not None:
                self._agent_cancel_event.set()
            if hasattr(self, "browser_agent") and self.browser_agent:
                try:
                    if hasattr(self.browser_agent, "cancel"):
                        self.browser_agent.cancel()
                except Exception:
                    pass
            with self._agent_lock:
                worker = self._agent_thread
            if worker and worker.is_alive() and worker is not threading.current_thread():
                worker.join(timeout=0.2)
            with self.state._lock:
                self.state.agent_running = bool(worker and worker.is_alive())
                self.state.set_browser_ownership(
                    BrowserOwnership.AGENT if self.state.agent_running else BrowserOwnership.NONE)
            self.browser.close()
            self.state.record_command(raw_text, command)
            return "STOP"

        else:
            raise ValueError(f"Unsupported action: {action}")

        # Lightweight post-action verification
        if cancel_event is not None and cancel_event.is_set():
            return "CANCELLED"
        self._verify_and_recover(command, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return "CANCELLED"

        # Update short-term context and observation state
        self.state.record_command(raw_text, command)
        self.state.sync_observation(browser=self.browser, screen=self.screen)

        return "OK"

    def join_agent(self, timeout: float = 1.0) -> bool:
        """
        Wait for active background agent worker to finish, up to `timeout` seconds.
        Returns True if thread is no longer alive, False if timed out.
        """
        with self._agent_lock:
            worker = self._agent_thread
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
            return not worker.is_alive()
        return True

    def close(self, timeout: float = 0.5):
        """Request cleanup; return False for a surviving agent or failed browser close."""
        self._closing.set()
        if self._agent_cancel_event is not None:
            self._agent_cancel_event.set()
        if hasattr(self, "browser_agent") and self.browser_agent:
            try:
                if hasattr(self.browser_agent, "cancel"):
                    self.browser_agent.cancel()
            except Exception:
                pass
        with self._agent_lock:
            worker = self._agent_thread
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=timeout)
        with self.state._lock:
            self.state.agent_running = bool(worker and worker.is_alive())
            self.state.set_browser_ownership(
                BrowserOwnership.AGENT if self.state.agent_running else BrowserOwnership.NONE)
        browser_closed = True
        try:
            self.browser.close()
        except Exception:
            browser_closed = False
        return browser_closed and not bool(worker and worker.is_alive())

    async def execute_async(
        self,
        command: Command,
        raw_text: str | None = None,
        cancel_event=None,
        request=None,
    ) -> str:
        """
        Asynchronous executor entry point compatible with an active asyncio event loop.
        Dispatches to execute() which handles background worker threads, desktop controls,
        and browser operations safely.
        """
        return self.execute(command, raw_text=raw_text, cancel_event=cancel_event, request=request)

