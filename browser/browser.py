import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import pyperclip
from playwright.sync_api import sync_playwright

from config import (
    BROWSER_TIMEOUT_MS,
    HIGHLIGHT_DURATION_MS,
    BROWSER_TYPE_GUARD_MS,
    get_brave_candidate_paths,
)
from utils.logger import log_browser, log_debug, log_warning


RESULT_ORDINAL_MAP = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "1": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "2": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "3": 3,
    "fourth": 4,
    "4th": 4,
    "four": 4,
    "4": 4,
    "fifth": 5,
    "5th": 5,
    "five": 5,
    "5": 5,
}


class BrowserController:

    ELEMENT_ALIASES = {
        "shots": ["shorts"],
        "short": ["shorts"],
        "youtube shorts": ["shorts"],
        "microphone": ["search with your voice", "search by voice", "voice search", "microphone", "voice"],
        "mic": ["search with your voice", "search by voice", "voice search", "microphone"],
        "voice": ["search with your voice", "search by voice", "voice search"],
        "search icon": ["search"],
        "search button": ["search"],
        "menu": ["guide", "navigation", "menu"],
        "notifications": ["notifications"],
        "profile": ["you", "account", "profile"],
    }

    def __init__(
        self,
        headless: bool = False,
        executable_path: str | None = None,
        user_data_dir: str | None = None,
    ):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.headless = headless
        self.executable_path = executable_path
        if user_data_dir is not None:
            self.user_data_dir = user_data_dir
        elif not headless:
            default_profile = Path(__file__).resolve().parent.parent / ".light_chromium_profile"
            default_profile.mkdir(parents=True, exist_ok=True)
            self.user_data_dir = str(default_profile)
        else:
            self.user_data_dir = None
        self._calibration_offset = (0, 0)
        self.active_browser_label: str | None = None
        self.active_executable_path: str | None = None
        self._skip_persistent_context: bool = False
        self.last_search_query: str | None = None

    # ==========================================
    # FIND BROWSER & FALLBACK CANDIDATES
    # ==========================================

    def _find_brave(self) -> str:
        if self.executable_path and Path(self.executable_path).exists():
            return str(self.executable_path)

        for path in get_brave_candidate_paths():
            if path.exists():
                return str(path)

        raise FileNotFoundError(
            "Brave Browser was not found. Install Brave or set BRAVE_EXECUTABLE_PATH in .env."
        )

    def _get_launch_candidates(self) -> list[tuple[str, str | None]]:
        """
        Return ordered (label, executable_path) launch candidates:
        - In headed mode (normal use): prefer genuine Google Chrome first (to avoid
          Google reCAPTCHA / 'I'm not a robot' triggers on Chrome-for-Testing),
          then Playwright Chromium, then Workspace Chromium, then Brave.
        - In headless mode (automated tests): prefer Playwright Chromium first.
        """
        from config import get_chrome_candidate_paths, get_workspace_chromium_candidate_paths

        candidates: list[tuple[str, str | None]] = []
        seen: set[str | None] = set()

        if self.executable_path:
            candidates.append(("Custom Browser", str(self.executable_path)))
            seen.add(str(self.executable_path))

        if not self.headless:
            for path in get_chrome_candidate_paths():
                try:
                    if path.exists():
                        resolved = str(path)
                        if resolved not in seen:
                            candidates.append(("Chrome", resolved))
                            seen.add(resolved)
                except OSError:
                    continue

        # Playwright-managed Chromium
        candidates.append(("Playwright Chromium", None))
        seen.add(None)

        # Workspace-local Playwright Chromium binaries
        for path in get_workspace_chromium_candidate_paths():
            try:
                if path.exists():
                    resolved = str(path)
                    if resolved not in seen:
                        candidates.append(("Workspace Chromium", resolved))
                        seen.add(resolved)
            except OSError:
                continue

        # Installed Google Chrome (if not already added)
        for path in get_chrome_candidate_paths():
            try:
                if path.exists():
                    resolved = str(path)
                    if resolved not in seen:
                        candidates.append(("Chrome", resolved))
                        seen.add(resolved)
            except OSError:
                continue

        # Brave as final fallback
        for path in get_brave_candidate_paths():
            try:
                if path.exists():
                    resolved = str(path)
                    if resolved not in seen:
                        candidates.append(("Brave", resolved))
                        seen.add(resolved)
            except OSError:
                continue

        return candidates

    # ==========================================
    # STEALTH & ANTI-BOT ("I'M NOT A ROBOT" FIX)
    # ==========================================

    def _apply_stealth(self):
        """
        Mask Playwright automation indicators (navigator.webdriver, missing window.chrome, etc.)
        so Google and other websites do not trigger 'I'm not a robot' reCAPTCHA pages.
        """
        stealth_js = """
        (() => {
            try {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                if (!window.chrome) {
                    window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                }
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            } catch (e) {}
        })();
        """
        try:
            if self.context is not None and hasattr(self.context, "add_init_script"):
                self.context.add_init_script(stealth_js)
            elif self.page is not None and hasattr(self.page, "add_init_script"):
                self.page.add_init_script(stealth_js)
            if self.page is not None and hasattr(self.page, "evaluate"):
                self.page.evaluate(stealth_js)
        except Exception as err:
            log_debug(f"Stealth init script skipped: {err}")

    # ==========================================
    # START & CHECK BROWSER
    # ==========================================

    def is_active(self) -> bool:
        """Return True if the browser/context and page are currently open."""
        try:
            if getattr(self, "_attached_over_cdp", False):
                self._refresh_active_cdp_page()
            return (
                (self.browser is not None or self.context is not None)
                and self.page is not None
                and not self.page.is_closed()
            )
        except Exception as err:
            log_debug(f"Browser is_active check failed: {err}")
            return False

    def _refresh_active_cdp_page(self):
        """Select the currently visible user tab when attached over CDP."""
        if not self.browser or not getattr(self.browser, "contexts", None):
            return
        try:
            for ctx in self.browser.contexts:
                pages = [
                    p
                    for p in ctx.pages
                    if not p.is_closed()
                    and not (p.url or "").startswith(("devtools://", "chrome-extension://"))
                ]
                if not pages:
                    continue
                for candidate in reversed(pages):
                    try:
                        vis = candidate.evaluate("() => document.visibilityState")
                        if vis == "visible":
                            self.context = ctx
                            self.page = candidate
                            return
                    except Exception:
                        continue
                self.context = ctx
                self.page = pages[-1]
                return
        except Exception as err:
            log_debug(f"_refresh_active_cdp_page skipped: {err}")

    def try_connect_cdp(self, endpoint_url: str | None = None) -> bool:
        """
        Attempt to attach Playwright over CDP to the user's running Brave/Chrome window.
        Returns True if connected and an active page is available, False otherwise.
        """
        import socket
        from config import CDP_DEBUG_PORT, CDP_ENDPOINT_URL

        if self.is_active():
            return True

        url = endpoint_url or CDP_ENDPOINT_URL
        try:
            with socket.create_connection(("127.0.0.1", CDP_DEBUG_PORT), timeout=0.12):
                pass
        except OSError:
            return False

        try:
            if self.playwright is None:
                self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(url)
            self._attached_over_cdp = True
            self._refresh_active_cdp_page()
            if self.page is None and self.browser.contexts:
                self.context = self.browser.contexts[0]
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            if self.page is not None:
                self.active_browser_label = "Brave (CDP)"
                log_browser("Connected to your running Brave window over CDP (DOM automation active).")
                return True
        except Exception as err:
            log_debug(f"CDP connection to {url} unavailable: {err}")
            self._attached_over_cdp = False
            self.browser = None
            self.context = None
            self.page = None
        return False

    def _launch_with_candidate(self, exe_path: str | None, launch_args: list[str]):
        """Attempt to launch browser/context with anti-bot stealth flags."""
        if self.user_data_dir and not getattr(self, "_skip_persistent_context", False):
            try:
                try:
                    self.context = self.playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.user_data_dir),
                        headless=self.headless,
                        executable_path=exe_path,
                        args=launch_args,
                        ignore_default_args=["--enable-automation"],
                        no_viewport=not self.headless,
                    )
                except TypeError:
                    self.context = self.playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.user_data_dir),
                        headless=self.headless,
                        executable_path=exe_path,
                        args=launch_args,
                        no_viewport=not self.headless,
                    )
                self.page = (
                    self.context.pages[0]
                    if self.context.pages
                    else self.context.new_page()
                )
                self._apply_stealth()
                return
            except Exception as persistent_err:
                log_debug(
                    f"Persistent context launch failed for {exe_path or 'Playwright Chromium'} ({persistent_err}); retrying ephemeral launch..."
                )
                self.context = None

        try:
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                executable_path=exe_path,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
            )
        except TypeError:
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                executable_path=exe_path,
                args=launch_args,
            )
        self.page = self.browser.new_page(no_viewport=not self.headless)
        self._apply_stealth()

    @staticmethod
    def _is_target_closed_error(err: Exception) -> bool:
        """Return True if a Playwright exception indicates a closed page, context, or browser."""
        msg = str(err or "").lower()
        return any(
            phrase in msg
            for phrase in (
                "target page, context or browser has been closed",
                "target closed",
                "browser has been closed",
                "context has been closed",
                "page has been closed",
                "frame was detached",
                "session closed",
            )
        )

    def _recover_closed_browser(self):
        """
        Recover from a closed/dead Playwright page or persistent profile lock by closing
        stale handles, disabling persistent profile reuse for the retry, and starting a clean session.
        """
        log_warning("Browser context/page was closed unexpectedly. Recovering clean browser session...")
        old_page = self.page
        old_browser = self.browser
        old_context = self.context
        self._skip_persistent_context = True
        self.close()
        self.start()
        if self.page is None and old_page is not None:
            self.page = old_page
            self.browser = old_browser
            self.context = old_context

    def _safe_goto(self, url: str, wait_until: str = "domcontentloaded", timeout: float | None = None):
        """Navigate to `url`, automatically recovering once if the page/context was closed."""
        self.start()
        kwargs = {"wait_until": wait_until}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            self.page.goto(url, **kwargs)
        except Exception as err:
            err_msg = str(err).lower()
            if "timeout" in err_msg and wait_until != "commit":
                try:
                    log_debug(f"Navigation timed out with wait_until='{wait_until}', falling back to 'commit'...")
                    self.page.goto(url, wait_until="commit", timeout=timeout or 5000)
                    return
                except Exception:
                    pass
            if self._is_target_closed_error(err) or not self.is_active():
                self._recover_closed_browser()
                self.page.goto(url, **kwargs)
            else:
                raise

    def _wait_for_search_results(self, engine: str):
        """Wait briefly for search result links to render in the DOM before completing SEARCH."""
        if self.page is None or not hasattr(self.page, "wait_for_selector"):
            return
        try:
            if engine == "youtube":
                self.page.wait_for_selector(
                    "ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title-link, yt-lockup-view-model a[href^='/watch'], a#video-title",
                    state="visible",
                    timeout=5000,
                )
            elif engine == "github":
                self.page.wait_for_selector(
                    'div[data-testid="results-list"], a[data-testid="search-result-title"], ul.repo-list',
                    state="visible",
                    timeout=5000,
                )
            else:
                self.page.wait_for_selector(
                    "div#search a h3, #rso a h3, a[data-testid='result-title-a'], .result__a",
                    state="visible",
                    timeout=5000,
                )
        except Exception as err:
            log_debug(f"Wait for {engine} search results skipped/timed out: {err}")

    def start(self):
        if self.is_active():
            return

        if self.browser is not None or self.context is not None or self.playwright is not None:
            self.close()

        self.playwright = sync_playwright().start()
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if not self.headless:
            launch_args.insert(0, "--start-maximized")
        candidates = self._get_launch_candidates()
        errors: list[str] = []

        for label, exe_path in candidates:
            try:
                log_browser(f"Starting {label}...")
                self._launch_with_candidate(exe_path, launch_args)
                self.active_browser_label = label
                self.active_executable_path = exe_path
                log_browser(f"{label} started.")
                return
            except Exception as err:
                errors.append(f"{label} ({exe_path or 'managed'}): {err}")
                log_warning(
                    f"Could not launch {label} ({exe_path or 'Playwright-managed Chromium'}): {err}. Trying next fallback..."
                )
                self.context = None
                self.browser = None
                self.page = None

        try:
            self.playwright.stop()
        except Exception:
            pass
        self.playwright = None

        raise RuntimeError(
            "Unable to start Brave or Playwright Chromium fallback. Attempted: "
            + " | ".join(errors)
        )

    # ==========================================
    # PREVENT HANDY AUTO-TYPING INTO SEARCH BARS
    # ==========================================

    def _unfocus_inputs(self, clear_text: str | None = None):
        """
        Blur any focused input/textarea on the page and remove any text
        that Handy STT may have automatically pasted into a focused search bar.
        """
        if not self.is_active():
            return

        try:
            self.page.evaluate(
                """(spokenText) => {
                    const inputs = document.querySelectorAll('input, textarea, [contenteditable="true"]');
                    for (const el of inputs) {
                        const val = (el.value || el.innerText || '');
                        if (
                            el === document.activeElement ||
                            (spokenText && val.toLowerCase().includes(spokenText.toLowerCase())) ||
                            val.toLowerCase().includes('click ') ||
                            val.toLowerCase().includes('move mouse') ||
                            val.toLowerCase().includes('open ') ||
                            val.toLowerCase().includes('scroll ')
                        ) {
                            if ('value' in el) {
                                el.value = '';
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                            }
                            el.blur();
                        }
                    }
                    if (document.activeElement && document.activeElement !== document.body) {
                        document.activeElement.blur();
                    }
                }""",
                clear_text or "",
            )
        except Exception as err:
            log_debug(f"_unfocus_inputs skipped: {err}")

    # ==========================================
    # OPEN URL & NAVIGATION
    # ==========================================

    def open_url(self, url: str):
        self.start()

        url = url.strip()
        if not url:
            raise ValueError("URL cannot be empty.")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        log_browser(f"Opening: {url}")

        self._safe_goto(
            url,
            wait_until="domcontentloaded",
        )

        self._unfocus_inputs()
        log_browser("Page opened.")

    def go_back(self):
        self.start()
        log_browser("Navigating back...")
        self.page.go_back(wait_until="domcontentloaded")
        self._unfocus_inputs()

    def go_forward(self):
        self.start()
        log_browser("Navigating forward...")
        self.page.go_forward(wait_until="domcontentloaded")
        self._unfocus_inputs()

    def refresh(self):
        self.start()
        log_browser("Refreshing page...")
        self.page.reload(wait_until="domcontentloaded")
        self._unfocus_inputs()

    # ==========================================
    # MEDIA CONTROL (HTML5 / YOUTUBE)
    # ==========================================

    def has_video_element(self) -> bool:
        """Return True if the current page contains an HTML5 video element."""
        if not self.is_active() or not self.page:
            return False
        try:
            return bool(self.page.evaluate("() => !!document.querySelector('video')"))
        except Exception:
            return False

    def media_play_pause(self) -> str:
        """Toggle play/pause on the page's video element without typing into search boxes."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """() => {
                const v = document.querySelector('video');
                if (!v) return 'no_video';
                if (v.paused) {
                    v.play();
                    return 'played';
                } else {
                    v.pause();
                    return 'paused';
                }
            }"""
        )
        log_browser(f"Media play/pause: {res}")
        return res

    def media_seek(self, seconds: float) -> float | None:
        """Seek forward (positive seconds) or backward (negative seconds)."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """(delta) => {
                const v = document.querySelector('video');
                if (!v) return null;
                const newTime = Math.max(0, Math.min(v.duration || Infinity, v.currentTime + delta));
                v.currentTime = newTime;
                return newTime;
            }""",
            float(seconds),
        )
        log_browser(f"Media seek delta={seconds}s -> new_time={res}")
        return res

    def media_fullscreen(self, enable: bool = True) -> bool:
        """Enter or exit fullscreen for video or page."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """(enable) => {
                const fsBtn = document.querySelector('button.ytp-fullscreen-button');
                const isFs = !!document.fullscreenElement;
                if (enable) {
                    if (!isFs) {
                        if (fsBtn) { fsBtn.click(); return true; }
                        const v = document.querySelector('video');
                        if (v && v.requestFullscreen) { v.requestFullscreen(); return true; }
                    }
                } else {
                    if (isFs) {
                        if (fsBtn) { fsBtn.click(); return true; }
                        if (document.exitFullscreen) { document.exitFullscreen(); return true; }
                    }
                }
                return false;
            }""",
            enable,
        )
        log_browser(f"Media fullscreen (enable={enable}) -> {res}")
        return bool(res)

    def media_mute(self) -> bool:
        """Toggle audio mute on the video element."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """() => {
                const v = document.querySelector('video');
                if (!v) return false;
                v.muted = !v.muted;
                return v.muted;
            }"""
        )
        log_browser(f"Media mute toggled -> muted={res}")
        return bool(res)

    def media_next(self) -> bool:
        """Skip to next video (e.g. YouTube next button)."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """() => {
                const nextBtn = document.querySelector('a.ytp-next-button');
                if (nextBtn) { nextBtn.click(); return true; }
                const v = document.querySelector('video');
                if (v && v.duration) { v.currentTime = v.duration; return true; }
                return false;
            }"""
        )
        log_browser(f"Media next -> {res}")
        return bool(res)

    def media_previous(self) -> bool:
        """Skip to previous video (e.g. YouTube prev button)."""
        self.start()
        self._unfocus_inputs()
        res = self.page.evaluate(
            """() => {
                const prevBtn = document.querySelector('a.ytp-prev-button');
                if (prevBtn) { prevBtn.click(); return true; }
                const v = document.querySelector('video');
                if (v) { v.currentTime = 0; return true; }
                return false;
            }"""
        )
        log_browser(f"Media previous -> {res}")
        return bool(res)

    # ==========================================
    # SEARCH (GOOGLE / YOUTUBE / GITHUB)
    # ==========================================

    def search(self, query: str, engine: str | None = None):
        """Search on YouTube, GitHub, or Google using Playwright."""
        self.start()

        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty.")
        self.last_search_query = query

        current_url = (self.page.url or "").lower()
        if engine is None:
            if "youtube.com" in current_url:
                engine = "youtube"
            elif "github.com" in current_url:
                engine = "github"
            else:
                engine = "google"

        engine = engine.lower().strip()

        if engine == "youtube":
            self.search_youtube(query)
        elif engine == "github":
            self.search_github(query)
        else:
            self.search_google(query)

    def search_github(self, query: str):
        self.start()
        log_browser(f"Searching GitHub for: {query}")

        current_url = (self.page.url or "").lower()
        if "github.com" in current_url:
            try:
                search_btn = self.page.locator("button.header-search-button, [data-target='qbsearch-input.inputButton']").first
                if search_btn.is_visible(timeout=1500):
                    search_btn.click()
                search_input = self.page.locator("input#query-builder-test, input[name='query-builder-test'], input[name='q'], [data-target='qbsearch-input.input']").first
                if search_input.is_visible(timeout=1500):
                    search_input.click()
                    search_input.fill(query)
                    search_input.press("Enter")
                    self.page.wait_for_load_state("domcontentloaded")
                    self._wait_for_search_results("github")
                    self._unfocus_inputs()
                    return
            except Exception as err:
                log_debug(f"GitHub DOM search box fallback: {err}")

        search_url = f"https://github.com/search?q={quote_plus(query)}&type=repositories"
        self._safe_goto(search_url, wait_until="domcontentloaded")
        self._wait_for_search_results("github")
        self._unfocus_inputs()

    def search_youtube(self, query: str):
        self.start()
        log_browser(f"Searching YouTube for: {query}")

        current_url = (self.page.url or "").lower()
        if "youtube" in current_url:
            try:
                search_box = self.page.locator("input[name='search_query'], input#search").first
                if search_box.is_visible(timeout=2000):
                    search_box.click()
                    search_box.fill(query)
                    search_box.press("Enter")
                    self.page.wait_for_load_state("domcontentloaded")
                    self._wait_for_search_results("youtube")
                    self._unfocus_inputs()
                    return
            except Exception as err:
                if self._is_target_closed_error(err):
                    self._recover_closed_browser()
                log_debug(f"YouTube DOM search box fallback: {err}")

        search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        self._safe_goto(search_url, wait_until="domcontentloaded")
        self._wait_for_search_results("youtube")
        self._unfocus_inputs()

    def _is_google_captcha_page(self) -> bool:
        try:
            current_url = (self.page.url or "").lower()
            if "/sorry/" in current_url or "google.com/sorry" in current_url:
                return True
            has_captcha = self.page.evaluate(
                """() => Boolean(
                    document.querySelector('#captcha-form, #recaptcha, .g-recaptcha, iframe[src*="recaptcha"]')
                )"""
            )
            return bool(has_captcha)
        except Exception:
            return False

    def search_google(self, query: str):
        self.start()
        log_browser(f"Searching Google for: {query}")

        current_url = (self.page.url or "").lower()
        used_search_box = False

        if "google." not in current_url or "/sorry/" in current_url:
            try:
                self._safe_goto("https://www.google.com", wait_until="domcontentloaded")
            except Exception as err:
                log_debug(f"Initial google.com navigation fallback: {err}")

        try:
            search_box = self.page.locator("textarea[name='q'], input[name='q']").first
            if search_box.is_visible(timeout=2500):
                search_box.click()
                search_box.fill(query)
                search_box.press("Enter")
                self.page.wait_for_load_state("domcontentloaded")
                used_search_box = True
        except Exception as err:
            if self._is_target_closed_error(err):
                self._recover_closed_browser()
            log_debug(f"Google DOM search box fallback: {err}")

        if not used_search_box:
            search_url = f"https://www.google.com/search?q={quote_plus(query)}"
            self._safe_goto(search_url, wait_until="domcontentloaded")

        if self._is_google_captcha_page():
            log_warning(
                "Google triggered an 'I'm not a robot' (/sorry/) challenge. "
                "Automatically switching this search to DuckDuckGo so your workflow is not blocked."
            )
            ddg_url = f"https://duckduckgo.com/?q={quote_plus(query)}&ia=web"
            self._safe_goto(ddg_url, wait_until="domcontentloaded")

        self._wait_for_search_results("google")
        self._unfocus_inputs()

    # ==========================================
    # TARGET PARSING & COORDINATE CONVERSION
    # ==========================================

    @staticmethod
    def parse_element_target(raw_target: str) -> dict:
        cleaned = (raw_target or "").strip()
        for prefix in ("onto the ", "onto ", "to the ", "to ", "over the ", "over ", "on the ", "on ", "at the ", "at "):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        if cleaned.lower().startswith("the "):
            cleaned = cleaned[4:].strip()

        lower = cleaned.lower()

        # 1. Search bar / input box
        if lower in {
            "search bar",
            "search box",
            "search input",
            "search field",
            "search",
            "input box",
            "input field",
            "text box",
        } or ("search" in lower and any(w in lower for w in ("bar", "box", "input", "field"))):
            return {"kind": "search_bar", "query": "search", "semantic": "input"}

        # 2. Nth result / video / link / short
        nth_short_match = re.match(
            r"^(?:the\s+)?(\w+)\s+(?:youtube\s+)?(?:shot|short|shorts)$",
            lower,
        )
        if nth_short_match and nth_short_match.group(1) in RESULT_ORDINAL_MAP:
            return {
                "kind": "nth_short",
                "index": RESULT_ORDINAL_MAP[nth_short_match.group(1)],
                "semantic": "link",
            }

        if lower in RESULT_ORDINAL_MAP:
            return {
                "kind": "nth_result",
                "index": RESULT_ORDINAL_MAP[lower],
                "semantic": "link",
            }

        nth_elem_match = re.match(
            r"^(?:the\s+)?(?:(\w+)\s+(?:clickable\s+)?element|element\s+(\w+))$",
            lower,
        )
        if nth_elem_match:
            tok = nth_elem_match.group(1) or nth_elem_match.group(2)
            if tok in RESULT_ORDINAL_MAP:
                return {
                    "kind": "nth_clickable",
                    "index": RESULT_ORDINAL_MAP[tok],
                    "semantic": "clickable",
                }

        if lower.startswith("official "):
            return {
                "kind": "named_result",
                "query": cleaned,
                "semantic": "link",
                "index": 1,
            }

        nth_match = re.match(
            r"^(?:the\s+)?(\w+)\s+(?:search\s+)?(?:result|video|link|item)$",
            lower,
        )
        if nth_match and nth_match.group(1) in RESULT_ORDINAL_MAP:
            return {
                "kind": "nth_result",
                "index": RESULT_ORDINAL_MAP[nth_match.group(1)],
                "semantic": "link",
            }

        nth_num_match = re.match(
            r"^(?:the\s+)?(?:search\s+)?(?:result|video|link|item|shot|short)\s+(?:number\s+)?(\w+)$",
            lower,
        )
        if nth_num_match and nth_num_match.group(1) in RESULT_ORDINAL_MAP:
            return {
                "kind": "nth_result",
                "index": RESULT_ORDINAL_MAP[nth_num_match.group(1)],
                "semantic": "link",
            }

        # 3. Explicit semantic wrapper like "text 'Coldplay'" or "Subscribe button"
        semantic = "any"
        text_prefix_match = re.match(
            r"^(?:the\s+)?(text|word|heading|title)\s+['\"]?(.+?)['\"]?$",
            cleaned,
            re.IGNORECASE,
        )
        if text_prefix_match:
            semantic = "text"
            cleaned = text_prefix_match.group(2).strip()
        else:
            suffix_match = re.match(
                r"^(.+?)\s+(button|link|tab|icon|input|field|option)$",
                cleaned,
                re.IGNORECASE,
            )
            if suffix_match:
                role_word = suffix_match.group(2).lower()
                if role_word in {"button", "icon", "option"}:
                    semantic = "button"
                elif role_word in {"link", "tab"}:
                    semantic = "link"
                elif role_word in {"input", "field"}:
                    semantic = "input"
                cleaned = suffix_match.group(1).strip()

            prefix_role_match = re.match(
                r"^(button|link|tab|icon)\s+['\"]?(.+?)['\"]?$",
                cleaned,
                re.IGNORECASE,
            )
            if prefix_role_match:
                role_word = prefix_role_match.group(1).lower()
                semantic = "button" if role_word in {"button", "icon"} else "link"
                cleaned = prefix_role_match.group(2).strip()

        cleaned = cleaned.strip("'\"")
        if cleaned.lower().startswith("the "):
            cleaned = cleaned[4:].strip()

        return {"kind": "element", "query": cleaned, "semantic": semantic}

    @staticmethod
    def convert_viewport_to_screen(
        viewport_x: float,
        viewport_y: float,
        window_metrics: dict,
        screen_size: tuple[int, int],
    ) -> tuple[int, int]:
        py_width, py_height = int(screen_size[0]), int(screen_size[1])

        win_screen_x = float(window_metrics.get("screenX", 0.0))
        win_screen_y = float(window_metrics.get("screenY", 0.0))
        outer_w = float(window_metrics.get("outerWidth", py_width))
        outer_h = float(window_metrics.get("outerHeight", py_height))
        inner_w = float(window_metrics.get("innerWidth", outer_w))
        inner_h = float(window_metrics.get("innerHeight", outer_h))
        js_screen_w = float(window_metrics.get("screenWidth", 0.0))
        js_screen_h = float(window_metrics.get("screenHeight", 0.0))
        dpr = float(window_metrics.get("devicePixelRatio", 1.0))

        border_x = max(0.0, (outer_w - inner_w) / 2.0)
        chrome_top = max(0.0, (outer_h - inner_h) - border_x)

        css_x = win_screen_x + border_x + float(viewport_x)
        css_y = win_screen_y + chrome_top + float(viewport_y)

        scale_x = (py_width / js_screen_w) if js_screen_w > 0 else dpr
        scale_y = (py_height / js_screen_h) if js_screen_h > 0 else dpr

        phys_x = round(css_x * scale_x)
        phys_y = round(css_y * scale_y)

        margin = 5
        clamped_x = max(margin, min(int(phys_x), py_width - margin - 1))
        clamped_y = max(margin, min(int(phys_y), py_height - margin - 1))

        return clamped_x, clamped_y

    def locate_element_in_viewport(
        self,
        target: str,
        perform_click: bool = False,
        search_context: str | None = None,
    ) -> dict:
        self.start()
        try:
            self.page.bring_to_front()
        except Exception as err:
            log_debug(f"bring_to_front skipped: {err}")

        parsed = self.parse_element_target(target)
        kind = parsed["kind"]
        query = parsed.get("query", "")
        semantic = parsed.get("semantic", "any")
        index = parsed.get("index", 1)

        if kind != "search_bar":
            self._unfocus_inputs(clear_text=query)

        query_lower = query.lower().strip()
        terms = [query_lower] if query_lower else []
        if query_lower in self.ELEMENT_ALIASES:
            terms = self.ELEMENT_ALIASES[query_lower] + terms

        payload = {
            "kind": kind,
            "terms": terms,
            "semantic": semantic,
            "index": index,
            "performClick": perform_click,
            "searchContext": (search_context or getattr(self, "last_search_query", "") or "").strip(),
            "targetQuery": query,
        }

        info = self.page.evaluate(
            r"""(params) => {
                function isVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (
                        style.display === 'none' ||
                        style.visibility === 'hidden' ||
                        parseFloat(style.opacity) === 0
                    ) {
                        return false;
                    }
                    const rect = el.getBoundingClientRect();
                    return rect.width > 4 && rect.height > 4;
                }

                function getWindowMetrics() {
                    return {
                        screenX: window.screenX || 0,
                        screenY: window.screenY || 0,
                        outerWidth: window.outerWidth || window.innerWidth,
                        outerHeight: window.outerHeight || window.innerHeight,
                        innerWidth: window.innerWidth,
                        innerHeight: window.innerHeight,
                        screenWidth: (window.screen && window.screen.width) || window.innerWidth,
                        screenHeight: (window.screen && window.screen.height) || window.innerHeight,
                        devicePixelRatio: window.devicePixelRatio || 1
                    };
                }

                function computeSafePoint(el, isInputTarget = false) {
                    const clickable = el.closest('button, a[href], [role="button"], [role="link"]') || el;
                    try {
                        document.querySelectorAll('[data-light-click-target="true"]').forEach(n => n.removeAttribute('data-light-click-target'));
                        clickable.setAttribute('data-light-click-target', 'true');
                    } catch (e) {}
                    clickable.scrollIntoView({ block: 'center', inline: 'center' });
                    let rect = clickable.getBoundingClientRect();

                    const clientRects = clickable.getClientRects();
                    if (!isInputTarget && clientRects && clientRects.length > 1) {
                        for (const r of clientRects) {
                            if (r.width > 10 && r.height > 8) {
                                rect = r;
                                break;
                            }
                        }
                    }

                    const offsetX = rect.width / 2;
                    const offsetY = rect.height / 2;
                    const x = Math.max(2, Math.min(window.innerWidth - 2, rect.left + offsetX));
                    const y = Math.max(2, Math.min(window.innerHeight - 2, rect.top + offsetY));
                    const tag = (clickable.tagName || '').toLowerCase();
                    const isInput = isInputTarget || tag === 'input' || tag === 'textarea';
                    const preText = (clickable.innerText || clickable.textContent || '').trim();
                    const preAdShowing = Boolean(document.querySelector('#movie_player.ad-showing, .ad-showing'));
                    if (isInput && typeof clickable.focus === 'function') {
                        clickable.focus();
                    }
                    if (params.performClick && typeof clickable.click === 'function') {
                        clickable.click();
                    }
                    return {
                        found: true,
                        is_input: isInput,
                        vp_x: x,
                        vp_y: y,
                        pre_text: preText,
                        pre_ad_showing: preAdShowing,
                        pre_url: window.location.href,
                        target_href: (clickable.getAttribute('href') || clickable.href || '').trim(),
                        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
                        matched: (preText || clickable.getAttribute('aria-label') || clickable.getAttribute('title') || clickable.getAttribute('placeholder') || clickable.tagName || '').trim().slice(0, 60),
                        window_metrics: getWindowMetrics()
                    };
                }

                // 1. SEARCH BAR
                if (params.kind === 'search_bar') {
                    const searchSelectors = [
                        'input#search',
                        'input[name="search_query"]',
                        'textarea[name="q"]',
                        'input[name="q"]',
                        'input[type="search"]',
                        '[role="searchbox"]',
                        'input[placeholder*="Search" i]',
                        'input[aria-label*="Search" i]',
                        'textarea[aria-label*="Search" i]',
                        'input[type="text"]'
                    ];
                    for (const sel of searchSelectors) {
                        const nodes = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                        if (nodes.length > 0) {
                            return computeSafePoint(nodes[0], true);
                        }
                    }
                    return { found: false };
                }

                // 2. Nth RESULT / VIDEO / SHORT
                if (params.kind === 'nth_short') {
                    const shortSelectors = 'a[href*="/shorts/"], ytd-reel-item-renderer a, ytm-shorts-lockup-view-model a, ytd-rich-item-renderer a#video-title-link';
                    const nodes = Array.from(document.querySelectorAll(shortSelectors)).filter(isVisible);
                    const chosen = nodes[Math.max(0, params.index - 1)];
                    if (!chosen) return { found: false };
                    return computeSafePoint(chosen);
                }

                if (params.kind === 'nth_result') {
                    const url = window.location.href.toLowerCase();
                    if (url.includes('youtube.com')) {
                        const videoSelectorList = [
                            'ytd-video-renderer a#video-title',
                            'ytd-video-renderer a[href^="/watch?v="]',
                            'yt-lockup-view-model a[href^="/watch?v="]',
                            'ytd-rich-item-renderer a#video-title-link',
                            '#contents a#video-title',
                            '#contents a#video-title-link'
                        ];
                        let videoNodes = [];
                        for (const sel of videoSelectorList) {
                            const matched = Array.from(document.querySelectorAll(sel)).filter(el => {
                                if (!isVisible(el)) return false;
                                if (el.closest('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer, #guide')) return false;
                                return true;
                            });
                            if (matched.length > 0) {
                                videoNodes = matched;
                                break;
                            }
                        }
                        const chosen = videoNodes[Math.max(0, params.index - 1)];
                        if (!chosen) return { found: false };
                        return computeSafePoint(chosen);
                    } else if (url.includes('github.com')) {
                        const ghSelectors = [
                            'div[data-testid="results-list"] h3 a',
                            'div[data-testid="results-list"] div[role="listitem"] a[href*="/"]',
                            'a[data-testid="search-result-title"]',
                            'div[data-testid="results-list"] a[href]',
                            'ul.repo-list li a[href]',
                            'div.search-title a'
                        ].join(', ');
                        const ghNodes = Array.from(document.querySelectorAll(ghSelectors)).filter(el => {
                            if (!isVisible(el)) return false;
                            const h = (el.getAttribute('href') || el.href || '').toLowerCase();
                            if (!h || h.startsWith('#') || h.startsWith('javascript:')) return false;
                            if (h.includes('/search') || h.includes('/settings') || h.includes('/notifications') || h.includes('/explore')) return false;
                            return true;
                        });
                        const chosen = ghNodes[Math.max(0, params.index - 1)];
                        if (!chosen) return { found: false };
                        return computeSafePoint(chosen);
                    }
                    let selectors = 'a:has(h3), div#search a h3, a[data-testid="result-title-a"], article h2 a, main a[href], article a[href], a[href]';
                    if (url.includes('google.com')) {
                        selectors = 'a:has(h3), div#search a h3';
                    } else if (url.includes('duckduckgo.com')) {
                        selectors = 'a[data-testid="result-title-a"], article h2 a, h2 a';
                    }
                    const nodes = Array.from(document.querySelectorAll(selectors)).filter(isVisible);
                    const chosen = nodes[Math.max(0, params.index - 1)];
                    if (!chosen) return { found: false };
                    return computeSafePoint(chosen);
                }

                // 2c. NTH CLICKABLE ELEMENT (e.g. "click the first element", "first element")
                if (params.kind === 'nth_clickable') {
                    const url = window.location.href.toLowerCase();
                    const isSearchOrVideoPage = (
                        url.includes('google.') ||
                        url.includes('youtube.com') ||
                        url.includes('github.com') ||
                        url.includes('duckduckgo.') ||
                        url.includes('bing.com')
                    );

                    if (url.includes('youtube.com')) {
                        const ytNodes = Array.from(document.querySelectorAll(
                            'ytd-video-renderer a#video-title, ytd-video-renderer a[href^="/watch?v="], yt-lockup-view-model a[href^="/watch?v="], ytd-rich-item-renderer a#video-title-link'
                        )).filter(el => isVisible(el) && !el.closest('ytd-mini-guide-entry-renderer, ytd-guide-entry-renderer, #guide'));
                        if (ytNodes.length > 0) {
                            const chosen = ytNodes[Math.max(0, params.index - 1)];
                            if (chosen) return computeSafePoint(chosen);
                        }
                    } else if (url.includes('github.com')) {
                        const ghNodes = Array.from(document.querySelectorAll(
                            'div[data-testid="results-list"] h3 a, div[data-testid="results-list"] div[role="listitem"] a[href*="/"], a[data-testid="search-result-title"], div[data-testid="results-list"] a[href], ul.repo-list li a[href]'
                        )).filter(el => {
                            if (!isVisible(el)) return false;
                            const h = (el.getAttribute('href') || el.href || '').toLowerCase();
                            if (!h || h.startsWith('#') || h.startsWith('javascript:')) return false;
                            if (h.includes('/search') || h.includes('/settings') || h.includes('/notifications') || h.includes('/explore')) return false;
                            return true;
                        });
                        if (ghNodes.length > 0) {
                            const chosen = ghNodes[Math.max(0, params.index - 1)];
                            if (chosen) return computeSafePoint(chosen);
                        }
                    } else if (isSearchOrVideoPage) {
                        const searchNodes = Array.from(document.querySelectorAll(
                            'a:has(h3), div#search a h3, a[data-testid="result-title-a"], article h2 a, h2 a'
                        )).filter(isVisible);
                        if (searchNodes.length > 0) {
                            const chosen = searchNodes[Math.max(0, params.index - 1)];
                            if (chosen) return computeSafePoint(chosen);
                        }
                    }

                    const interactiveSelectors = 'button, a[href], [role="button"], [role="link"], input[type="button"], input[type="submit"], input[type="reset"]';
                    const allInteractive = Array.from(document.querySelectorAll(interactiveSelectors)).filter(isVisible);

                    allInteractive.sort((a, b) => {
                        const ra = a.getBoundingClientRect();
                        const rb = b.getBoundingClientRect();
                        if (Math.abs(ra.top - rb.top) > 15) return ra.top - rb.top;
                        return ra.left - rb.left;
                    });

                    const chosen = allInteractive[Math.max(0, params.index - 1)];
                    if (!chosen) {
                        return { found: false, error: 'No visible interactive element found at index ' + params.index };
                    }
                    return computeSafePoint(chosen);
                }

                // 2d. NAMED SEARCH RESULT (e.g. "official repository", "official docs", "official website")
                if (params.kind === 'named_result') {
                    const url = window.location.href.toLowerCase();
                    const isGitHubPage = url.includes('github.com');
                    const targetLower = (params.targetQuery || '').toLowerCase();
                    const ctxLower = (params.searchContext || '').toLowerCase();

                    const isRepo = targetLower.includes('repo') || targetLower.includes('repository') || targetLower.includes('github') || targetLower.includes('code');
                    const isDocs = targetLower.includes('doc') || targetLower.includes('documentation') || targetLower.includes('guide') || targetLower.includes('manual') || targetLower.includes('api');
                    const isSite = targetLower.includes('site') || targetLower.includes('website') || targetLower.includes('page') || targetLower.includes('official');

                    const resultSelectors = [
                        'div[data-testid="results-list"] h3 a',
                        'div[data-testid="results-list"] div[role="listitem"] a[href*="/"]',
                        'div[data-testid="results-list"] a[href*="/"]',
                        'a[data-testid="search-result-title"]',
                        'ul.repo-list li a',
                        'div.search-title a',
                        'div#search a:has(h3)',
                        'div#rso a:has(h3)',
                        'a:has(h3)',
                        'a[data-testid="result-title-a"]',
                        'article h2 a',
                        'h2 a',
                        'div#search a[href]',
                        'div.g a[href]',
                        'main a[href]'
                    ].join(', ');

                    const candidateLinks = Array.from(document.querySelectorAll(resultSelectors)).filter(el => {
                        if (!isVisible(el)) return false;
                        const h = (el.getAttribute('href') || el.href || '').toLowerCase();
                        if (!h || h.startsWith('javascript:') || h.startsWith('#')) return false;
                        if (h.includes('google.com/search') || h.includes('google.com/preferences') || h.includes('accounts.google.com') || h.includes('support.google.com')) return false;
                        if (h.includes('github.com/search') || h.includes('github.com/settings') || h.includes('github.com/notifications') || h.includes('github.com/explore')) return false;
                        return true;
                    });

                    let bestEl = null;
                    let bestScore = -Infinity;

                    const ctxTokens = ctxLower.split(/[^a-z0-9]+/).filter(w => w.length > 2);

                    for (let i = 0; i < candidateLinks.length; i++) {
                        const el = candidateLinks[i];
                        const href = (el.getAttribute('href') || el.href || '').toLowerCase();
                        const inner = (el.innerText || el.textContent || '').toLowerCase();
                        const h3 = el.querySelector('h3');
                        const h3Text = h3 ? (h3.innerText || '').toLowerCase() : '';
                        const parent = el.closest('div.g, div[data-hveid], article, li, div[data-testid="result"], div[role="listitem"]');
                        const snippet = parent ? (parent.innerText || '').toLowerCase() : '';
                        const combined = `${href} ${inner} ${h3Text} ${snippet}`;

                        let score = 0;
                        score += Math.max(0, 30 - i * 4);

                        for (const tok of ctxTokens) {
                            if (combined.includes(tok)) score += 30;
                            if (href.includes(tok)) score += 35;
                            if (h3Text.includes(tok) || inner.includes(tok)) score += 35;
                        }

                        if (isRepo) {
                            if (href.includes('github.com') || href.includes('gitlab.com') || isGitHubPage) {
                                score += 120;
                            }
                            if (combined.includes('github') || combined.includes('repository') || combined.includes('repo')) {
                                score += 40;
                            }
                            // Exact repo slug match e.g. /langchain-ai/langgraph or /langgraph
                            for (const tok of ctxTokens) {
                                if (href.endsWith('/' + tok) || href.includes('/' + tok + '/') || href.includes('/' + tok)) {
                                    score += 80;
                                }
                            }
                            if (targetLower.includes('official')) {
                                for (const tok of ctxTokens) {
                                    if (href.includes(tok)) score += 50;
                                }
                            }
                            if (href.includes('twitter.com') || href.includes('x.com') || href.includes('linkedin.com') || href.includes('facebook.com') || href.includes('reddit.com') || href.includes('medium.com')) {
                                score -= 100;
                            }
                        }

                        if (isDocs) {
                            if (href.includes('docs.') || href.includes('/docs') || href.includes('readthedocs') || href.includes('documentation')) {
                                score += 100;
                            }
                            if (combined.includes('documentation') || combined.includes('docs') || combined.includes('api reference')) {
                                score += 40;
                            }
                        }

                        if (isSite && !isRepo) {
                            if (combined.includes('official') || combined.includes('home page') || combined.includes('overview')) {
                                score += 50;
                            }
                            if (ctxTokens.length > 0 && ctxTokens.some(tok => href.includes(tok + '.org') || href.includes(tok + '.com') || href.includes(tok + '.io') || href.includes(tok + '.dev'))) {
                                score += 80;
                            }
                        }

                        if (score > bestScore) {
                            bestScore = score;
                            bestEl = el;
                        }
                    }

                    if (!bestEl || bestScore < 20) {
                        return { found: false, error: 'Could not find a high-confidence search result matching ' + targetLower };
                    }
                    return computeSafePoint(bestEl);
                }

                // 2b. YOUTUBE AD SKIP BUTTON PRIORITY
                if (params.terms && params.terms.some(t => t === 'skip' || t === 'skip ad' || t === 'skip ads' || t === 'skip button')) {
                    const ytSkipSelectors = [
                        'button.ytp-skip-ad-button',
                        'button.ytp-ad-skip-button-modern',
                        'button.ytp-ad-skip-button',
                        '.ytp-skip-ad-button',
                        '.ytp-ad-skip-button-modern',
                        '.ytp-ad-skip-button',
                        '.ytp-ad-skip-button-slot button',
                        '.ytp-ad-overlay-close-button'
                    ];
                    for (const sel of ytSkipSelectors) {
                        const skipNodes = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                        if (skipNodes.length > 0) {
                            return computeSafePoint(skipNodes[0]);
                        }
                    }
                }

                // 3. NAMED UI ELEMENT / BUTTON / LINK / TEXT
                const allSelectors = [
                    'a#video-title',
                    'a#video-title-link',
                    'ytd-subscribe-button-renderer button',
                    'ytd-mini-guide-entry-renderer a',
                    'ytd-guide-entry-renderer a',
                    'button',
                    'a[href]',
                    '[role="button"]',
                    '[role="link"]',
                    '[role="tab"]',
                    '[role="menuitem"]',
                    '[aria-label]',
                    '[title]',
                    'span',
                    'h1, h2, h3, h4, p, div'
                ].join(', ');

                const candidates = Array.from(document.querySelectorAll(allSelectors)).filter(el => {
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'input' || tag === 'textarea') return false;
                    if (el.getAttribute('jsname') === 'vdLsw') return false;
                    return isVisible(el);
                });

                let bestEl = null;
                let bestScore = -Infinity;

                function stemWord(w) {
                    if (w.length > 4 && w.endsWith('ies')) return w.slice(0, -3) + 'y';
                    if (w.length > 3 && w.endsWith('es')) return w.slice(0, -2);
                    if (w.length > 3 && w.endsWith('s')) return w.slice(0, -1);
                    return w;
                }

                function tokenize(str) {
                    return (str || '')
                        .toLowerCase()
                        .replace(/[^a-z0-9\s]/g, ' ')
                        .split(/\s+/)
                        .filter(Boolean);
                }

                const stopWords = new Set(['for', 'the', 'a', 'an', 'in', 'on', 'to', 'of', 'and', 'with', 'by', 'at', 'from']);

                for (const term of params.terms) {
                    const termTokens = tokenize(term);
                    const termContentTokens = termTokens.filter(w => !stopWords.has(w)).map(stemWord);

                    for (const el of candidates) {
                        const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        const title = (el.getAttribute('title') || '').trim().toLowerCase();
                        const inner = (el.innerText || el.textContent || '').trim().toLowerCase();

                        const exactMatch = (inner === term || aria === term || title === term);
                        const containsMatch = (
                            inner.includes(term) ||
                            aria.includes(term) ||
                            title.includes(term)
                        );

                        let fuzzyRatio = 0;
                        let matchedContentCount = 0;

                        if (!exactMatch && !containsMatch && termContentTokens.length >= 2) {
                            const combinedText = `${inner} ${aria} ${title}`;
                            const elStemSet = new Set(tokenize(combinedText).map(stemWord));
                            for (const tok of termContentTokens) {
                                if (elStemSet.has(tok)) {
                                    matchedContentCount++;
                                }
                            }
                            fuzzyRatio = matchedContentCount / termContentTokens.length;
                        }

                        const isFuzzyMatch = (
                            termContentTokens.length >= 2 &&
                            matchedContentCount >= 2 &&
                            fuzzyRatio >= 0.6
                        );

                        if (!exactMatch && !containsMatch && !isFuzzyMatch) continue;

                        let score = exactMatch ? 200 : (containsMatch ? 110 : Math.round(fuzzyRatio * 95));

                        const tag = el.tagName.toLowerCase();
                        const role = (el.getAttribute('role') || '').toLowerCase();
                        const isButton = (tag === 'button' || role === 'button');
                        const isLink = (tag === 'a' || role === 'link' || role === 'tab');
                        const isVideoTitle = (el.id === 'video-title' || el.id === 'video-title-link');

                        if (isVideoTitle) score += 35;
                        if (params.semantic === 'button' && isButton) score += 60;
                        if (params.semantic === 'link' && isLink) score += 60;
                        if (params.semantic === 'any' && (isButton || isLink)) score += 45;

                        const rect = el.getBoundingClientRect();
                        const areaPenalty = Math.min(70, (rect.width * rect.height) / 4000);
                        const lengthPenalty = Math.min(50, Math.max(0, inner.length - term.length) * 0.5);
                        score -= (areaPenalty + lengthPenalty);

                        if (score > bestScore) {
                            bestScore = score;
                            bestEl = el;
                        }
                    }
                    if (bestEl && bestScore >= 180) break;
                }

                if (!bestEl) return { found: false };

                return computeSafePoint(bestEl);
            }""",
            payload,
        )

        if not info or not info.get("found"):
            err_msg = info.get("error") if (isinstance(info, dict) and info.get("error")) else f"Could not find a visible element matching '{target}'."
            raise RuntimeError(err_msg)

        return info

    def get_element_screen_point(
        self,
        target: str,
        screen_size: tuple[int, int],
    ) -> tuple[int, int]:
        info = self.locate_element_in_viewport(target)
        vp_x = float(info["vp_x"])
        vp_y = float(info["vp_y"])

        screen_x, screen_y = self.convert_viewport_to_screen(
            vp_x,
            vp_y,
            info.get("window_metrics", {}),
            screen_size,
        )

        cal_dx, cal_dy = self._calibration_offset
        screen_x, screen_y = screen_x + cal_dx, screen_y + cal_dy

        log_browser(
            f"Target '{info.get('matched', target)}' -> viewport ({int(vp_x)}, {int(vp_y)}) -> screen ({screen_x}, {screen_y})"
        )
        return screen_x, screen_y

    def move_mouse_to_element(
        self,
        target: str,
        mouse_controller,
        search_context: str | None = None,
    ) -> tuple[int, int]:
        screen_size = mouse_controller.get_screen_size()
        info = self.locate_element_in_viewport(target, search_context=search_context)
        vp_x = float(info["vp_x"])
        vp_y = float(info["vp_y"])
        metrics = info.get("window_metrics", {})

        base_x, base_y = self.convert_viewport_to_screen(vp_x, vp_y, metrics, screen_size)
        cal_dx, cal_dy = self._calibration_offset
        est_x, est_y = mouse_controller.clamp_to_screen(base_x + cal_dx, base_y + cal_dy)

        try:
            self.page.evaluate(
                """() => {
                    window.__lightOsMouse = null;
                    if (!window.__lightOsListenerAttached) {
                        window.__lightOsListenerAttached = true;
                        window.addEventListener('mousemove', (e) => {
                            window.__lightOsMouse = { clientX: e.clientX, clientY: e.clientY };
                        }, { passive: true, capture: true });
                    }
                }"""
            )
        except Exception as err:
            log_debug(f"OS mousemove tracker attach skipped: {err}")

        mouse_controller.move(est_x, est_y, duration=0.25)

        try:
            actual = self.page.evaluate("() => window.__lightOsMouse")
            if actual and "clientX" in actual and "clientY" in actual:
                err_vp_x = vp_x - float(actual["clientX"])
                err_vp_y = vp_y - float(actual["clientY"])

                if abs(err_vp_x) > 2 or abs(err_vp_y) > 2:
                    js_screen_w = float(metrics.get("screenWidth", screen_size[0])) or screen_size[0]
                    js_screen_h = float(metrics.get("screenHeight", screen_size[1])) or screen_size[1]
                    scale_x = screen_size[0] / js_screen_w
                    scale_y = screen_size[1] / js_screen_h

                    corr_dx = int(round(err_vp_x * scale_x))
                    corr_dy = int(round(err_vp_y * scale_y))

                    if abs(corr_dx) < 250 and abs(corr_dy) < 250:
                        self._calibration_offset = (cal_dx + corr_dx, cal_dy + corr_dy)
                        est_x, est_y = mouse_controller.move(est_x + corr_dx, est_y + corr_dy, duration=0.08)
                        log_browser(
                            f"Calibrated cursor by ({corr_dx}, {corr_dy}) px -> locked onto ({est_x}, {est_y})"
                        )
        except Exception as err:
            log_debug(f"OS mousemove calibration check skipped: {err}")

        try:
            self.page.mouse.move(vp_x, vp_y)
        except Exception as err:
            log_debug(f"Playwright virtual hover skipped: {err}")

        return est_x, est_y

    # ==========================================
    # DOM INTERACTION & VERIFIED PHYSICAL CLICK
    # ==========================================

    def _settle_after_click(self):
        try:
            self.page.wait_for_timeout(80)
            self.page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception as err:
            log_debug(f"Post-click load state wait skipped: {err}")

    def _attach_click_tracker(self):
        """Install a lightweight click-event listener on the page before clicking."""
        try:
            self.page.evaluate(
                """() => {
                    window.__lightClickStats = { count: 0, trusted: 0 };
                    if (!window.__lightClickListenerAttached) {
                        window.__lightClickListenerAttached = true;
                        window.addEventListener('click', (e) => {
                            if (window.__lightClickStats) {
                                window.__lightClickStats.count += 1;
                                if (e.isTrusted) window.__lightClickStats.trusted += 1;
                            }
                        }, { capture: true, passive: true });
                    }
                }"""
            )
        except Exception as err:
            log_debug(f"_attach_click_tracker skipped: {err}")

    def _perform_physical_click_and_verify(
        self,
        target: str,
        mouse_controller=None,
        require_skip_verification: bool = False,
        search_context: str | None = None,
    ) -> dict:
        """
        Execute the complete LOCATE -> MOVE -> VERIFY CURSOR -> PHYSICAL CLICK -> VERIFY pipeline:
        1. Bring browser page to front and attach DOM click tracker.
        2. Move physical mouse cursor onto target and verify/correct cursor coordinates.
        3. Perform actual physical mouse click (mouseDown + mouseUp).
        4. If running headless or if OS click was intercepted before reaching the webpage,
           send Playwright hardware-level trusted mouse click at (vp_x, vp_y).
        5. Verify post-click UI/DOM state change (especially for 'skip' / interactive buttons).
        """
        try:
            self.page.bring_to_front()
        except Exception:
            pass

        self._attach_click_tracker()

        cursor_before = (0, 0)
        if mouse_controller is not None and hasattr(mouse_controller, "get_position"):
            try:
                pos = mouse_controller.get_position()
                if isinstance(pos, tuple) and len(pos) == 2:
                    cursor_before = (int(pos[0]), int(pos[1]))
            except Exception:
                pass

        if mouse_controller is not None:
            est_x, est_y = self.move_mouse_to_element(target, mouse_controller, search_context=search_context)
            info = self.locate_element_in_viewport(target, perform_click=False, search_context=search_context)
            vp_x = float(info["vp_x"])
            vp_y = float(info["vp_y"])
            screen_size = mouse_controller.get_screen_size()
            recalc_x, recalc_y = self.convert_viewport_to_screen(
                vp_x, vp_y, info.get("window_metrics", {}), screen_size
            )
            cal_dx, cal_dy = self._calibration_offset
            latest_x, latest_y = mouse_controller.clamp_to_screen(
                recalc_x + cal_dx, recalc_y + cal_dy
            )
            if abs(latest_x - est_x) > 3 or abs(latest_y - est_y) > 3:
                est_x, est_y = mouse_controller.move(latest_x, latest_y, duration=0.05)

            cursor_after_move = (est_x, est_y)
            if hasattr(mouse_controller, "verify_and_correct_position"):
                try:
                    verified_pos = mouse_controller.verify_and_correct_position(
                        est_x, est_y, tolerance=5
                    )
                    if isinstance(verified_pos, tuple) and len(verified_pos) == 2:
                        cursor_after_move = (int(verified_pos[0]), int(verified_pos[1]))
                except Exception:
                    pass

            log_browser(
                f"target={target} viewport=({int(vp_x)},{int(vp_y)}) "
                f"screen=({est_x},{est_y}) cursor_before={cursor_before} "
                f"cursor_after_move={cursor_after_move} click_started"
            )

            if hasattr(mouse_controller, "click_at"):
                mouse_controller.click_at(est_x, est_y)
            else:
                mouse_controller.click()
        else:
            info = self.locate_element_in_viewport(target, perform_click=False, search_context=search_context)
            vp_x = float(info["vp_x"])
            vp_y = float(info["vp_y"])
            est_x, est_y = int(vp_x), int(vp_y)
            cursor_after_move = (est_x, est_y)
            log_browser(
                f"target={target} viewport=({int(vp_x)},{int(vp_y)}) "
                f"screen=({est_x},{est_y}) cursor_before={cursor_before} "
                f"cursor_after_move={cursor_after_move} click_started"
            )

        # Check whether the webpage received the physical OS click.
        # In headless mode or if an OS overlay intercepted the physical click,
        # dispatch Playwright's trusted CDP mouseDown + mouseUp at (vp_x, vp_y).
        click_received_by_page = False
        try:
            stats = self.page.evaluate("() => window.__lightClickStats")
            if isinstance(stats, dict) and int(stats.get("count", 0)) > 0:
                click_received_by_page = True
        except Exception:
            pass

        if not click_received_by_page:
            try:
                self.page.mouse.move(vp_x, vp_y)
                self.page.mouse.down(button="left")
                self.page.mouse.up(button="left")
            except Exception as err:
                log_debug(f"Playwright hardware mouse click fallback skipped: {err}")

        log_browser(
            f"target={target} viewport=({int(vp_x)},{int(vp_y)}) "
            f"screen=({est_x},{est_y}) cursor_before={cursor_before} "
            f"cursor_after_move={cursor_after_move} click_completed"
        )

        self._settle_after_click()
        self._verify_element_click(
            target=target,
            pre_info=info,
            vp_x=vp_x,
            vp_y=vp_y,
            require_skip_verification=require_skip_verification,
        )
        return info

    def _verify_element_click(
        self,
        target: str,
        pre_info: dict,
        vp_x: float,
        vp_y: float,
        require_skip_verification: bool = False,
    ):
        """
        Verify whether the physical click activated the target UI element.
        For 'skip' buttons (or elements with explicit activation verification),
        checks whether the button disappeared, changed text/state, or cleared the ad state.
        Performs a single controlled fallback if the initial click did not activate the element,
        and raises RuntimeError if activation still fails.
        """
        is_skip_target = require_skip_verification or (
            (target or "").strip().lower() in {"skip", "skip ad", "skip ads", "skip button"}
        )

        def check_post_state() -> dict | None:
            try:
                res = self.page.evaluate(
                    """(pre) => {
                        function isVisible(el) {
                            if (!el || !el.isConnected) return false;
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) {
                                return false;
                            }
                            const rect = el.getBoundingClientRect();
                            return rect.width > 4 && rect.height > 4;
                        }
                        const el = document.querySelector('[data-light-click-target="true"]');
                        const clickStats = window.__lightClickStats || { count: 0, trusted: 0 };
                        const nowUrl = window.location.href;
                        const nowAdShowing = Boolean(document.querySelector('#movie_player.ad-showing, .ad-showing'));
                        const ytSkipStillVisible = Array.from(
                            document.querySelectorAll('button.ytp-skip-ad-button, button.ytp-ad-skip-button-modern, button.ytp-ad-skip-button, .ytp-skip-ad-button')
                        ).some(isVisible);

                        if (!el || !isVisible(el)) {
                            return { activated: true, reason: 'target_disappeared', clickCount: clickStats.count };
                        }
                        const nowText = (el.innerText || el.textContent || '').trim();
                        const dataClicked = el.getAttribute('data-clicked') === 'true' || el.getAttribute('aria-pressed') === 'true';
                        const isDisabled = Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true');
                        const urlChanged = Boolean(pre.pre_url && nowUrl !== pre.pre_url);
                        const textChanged = Boolean(pre.pre_text !== undefined && nowText !== pre.pre_text);
                        const adCleared = Boolean(pre.pre_ad_showing && !nowAdShowing && !ytSkipStillVisible);

                        return {
                            activated: Boolean(urlChanged || textChanged || dataClicked || isDisabled || adCleared),
                            clickCount: clickStats.count,
                            nowText: nowText,
                            ytSkipStillVisible: ytSkipStillVisible,
                            nowAdShowing: nowAdShowing
                        };
                    }""",
                    {
                        "pre_text": pre_info.get("pre_text", ""),
                        "pre_url": pre_info.get("pre_url", ""),
                        "pre_ad_showing": pre_info.get("pre_ad_showing", False),
                    },
                )
                return res if isinstance(res, dict) else None
            except Exception:
                return None

        state_check = check_post_state()
        if state_check is None:
            return

        if state_check.get("activated"):
            return

        # Controlled fallback: if the physical click did not activate the element
        # (or if clickCount == 0), perform a single controlled fallback and re-verify.
        if is_skip_target or int(state_check.get("clickCount", 0)) == 0:
            try:
                self.page.mouse.click(vp_x, vp_y)
                self.page.evaluate(
                    """() => {
                        const el = document.querySelector('[data-light-click-target="true"], button.ytp-skip-ad-button, button.ytp-ad-skip-button-modern');
                        if (el && typeof el.click === 'function') el.click();
                    }"""
                )
                self._settle_after_click()
            except Exception as err:
                log_debug(f"Controlled click fallback skipped: {err}")

            state_check = check_post_state()
            if state_check is not None and is_skip_target and not state_check.get("activated"):
                raise RuntimeError(
                    f"Click verification failed for '{target}': Skip button remained visible and unchanged after physical click."
                )

    def click_result(
        self,
        index: int | str = 1,
        mouse_controller=None,
        search_context: str | None = None,
    ):
        if self.page is not None:
            current_url = str(getattr(self.page, "url", "") or "").strip().lower()
            if current_url == "about:blank":
                raise RuntimeError(
                    "Cannot click search result: browser page is on about:blank (search results are not loaded)."
                )
            if "youtube.com/results" in current_url:
                self._wait_for_search_results("youtube")
            elif "github.com/search" in current_url or ("github.com" in current_url and "q=" in current_url):
                self._wait_for_search_results("github")
            elif "google." in current_url and "/search" in current_url:
                self._wait_for_search_results("google")

        effective_context = search_context or getattr(self, "last_search_query", None)
        target_str = str(index).strip() if index is not None else "1"
        if target_str.isdigit() or target_str.lower() in RESULT_ORDINAL_MAP:
            parsed_idx = RESULT_ORDINAL_MAP.get(
                target_str.lower(),
                int(target_str) if target_str.isdigit() else 1,
            )
            if parsed_idx < 1:
                parsed_idx = 1
            log_browser(f"Clicking result #{parsed_idx}...")
            target_str = f"result {parsed_idx}"
        else:
            log_browser(f"Clicking result: '{target_str}' with search context '{effective_context}'...")

        pre_url = str(getattr(self.page, "url", "") or "").strip()
        info = self._perform_physical_click_and_verify(
            target_str,
            mouse_controller=mouse_controller,
            search_context=effective_context,
        )
        self._unfocus_inputs()

        # Semantic verification for named targets
        is_named = not (target_str.isdigit() or target_str.lower() in RESULT_ORDINAL_MAP or target_str.lower().startswith("result "))
        if is_named:
            self.verify_destination(expected_target=target_str, expected_query=effective_context, pre_url=pre_url)

        return info

    def verify_destination(
        self,
        expected_target: str,
        expected_query: str | None = None,
        pre_url: str | None = None,
    ):
        """
        Semantic verification: After clicking a named target, verify that the resulting
        page actually matches the requested target and query.
        Raises RuntimeError if verification fails.
        """
        if not self.is_active() or not self.page:
            return

        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 3.0:
            curr = (self.get_current_url() or "").strip()
            if pre_url and curr and curr != pre_url and curr.lower() != "about:blank":
                break
            time.sleep(0.1)

        curr_url = (self.get_current_url() or "").lower()
        curr_title = (self.get_title() or "").lower()
        target_lower = (expected_target or "").lower()
        query_lower = (expected_query or "").lower()

        query_tokens = [t for t in re.split(r"[^a-z0-9]+", query_lower) if len(t) >= 3]

        is_repo = any(w in target_lower for w in ("repo", "repository", "github", "code"))
        is_docs = any(w in target_lower for w in ("doc", "documentation", "guide", "manual", "api"))
        is_site = any(w in target_lower for w in ("website", "site", "official", "page"))

        log_browser(f"[VERIFY] Destination: url='{curr_url}' title='{curr_title}' for target='{expected_target}' query='{expected_query}'")

        if is_repo:
            valid_host = any(h in curr_url for h in ("github.com", "gitlab.com"))
            if not valid_host:
                raise RuntimeError(
                    f"Semantic verification failed: Target '{expected_target}' requires a code repository, "
                    f"but landed on '{curr_url}' ({curr_title})."
                )
            if query_tokens:
                matched_token = any(tok in curr_url or tok in curr_title for tok in query_tokens)
                if not matched_token:
                    page_text = (self.get_visible_text() or "").lower()[:2000]
                    matched_token = any(tok in page_text for tok in query_tokens)
                if not matched_token:
                    raise RuntimeError(
                        f"Semantic verification failed: Landed on '{curr_url}' ({curr_title}), "
                        f"which does not match repository query '{expected_query}'."
                    )

        elif is_docs:
            valid_docs = any(d in curr_url or d in curr_title for d in ("doc", "guide", "manual", "api", "reference", "tutorial"))
            if not valid_docs:
                raise RuntimeError(
                    f"Semantic verification failed: Target '{expected_target}' requires documentation, "
                    f"but landed on '{curr_url}' ({curr_title})."
                )
            if query_tokens:
                matched_token = any(tok in curr_url or tok in curr_title for tok in query_tokens)
                if not matched_token:
                    raise RuntimeError(
                        f"Semantic verification failed: Landed on '{curr_url}' ({curr_title}), "
                        f"which does not match docs query '{expected_query}'."
                    )

        elif is_site:
            if query_tokens:
                matched_token = any(tok in curr_url or tok in curr_title for tok in query_tokens)
                if not matched_token:
                    raise RuntimeError(
                        f"Semantic verification failed: Landed on '{curr_url}' ({curr_title}), "
                        f"which does not match query '{expected_query}'."
                    )

        log_browser(f"[VERIFY] Destination verified successfully: '{curr_url}'")

    def click_element(self, text: str, mouse_controller=None):
        log_browser(f"Clicking element: '{text}'")
        info = self._perform_physical_click_and_verify(text, mouse_controller=mouse_controller)

        if not info.get("is_input"):
            self._unfocus_inputs()

    def type_in_browser(self, text: str) -> bool:
        if not self.is_active():
            return False

        try:
            self.page.bring_to_front()
            typed = self.page.evaluate(
                """(params) => {
                    const typedText = params.text;
                    const guardMs = params.guardMs;
                    function isVisible(el) {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 4 && rect.height > 4;
                    }

                    let active = document.activeElement;
                    const isActiveInput = active && (
                        active.tagName.toLowerCase() === 'input' ||
                        active.tagName.toLowerCase() === 'textarea' ||
                        active.getAttribute('contenteditable') === 'true'
                    );

                    if (!isActiveInput) {
                        const searchSelectors = [
                            'input#search',
                            'input[name="search_query"]',
                            'textarea[name="q"]',
                            'input[name="q"]',
                            'input[type="search"]',
                            '[role="searchbox"]',
                            'input[type="text"]'
                        ];
                        for (const sel of searchSelectors) {
                            const found = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                            if (found.length > 0) {
                                active = found[0];
                                active.focus();
                                break;
                            }
                        }
                    }

                    if (active && 'value' in active) {
                        const setExactValue = () => {
                            active.value = typedText;
                            active.dispatchEvent(new Event('input', { bubbles: true }));
                            active.dispatchEvent(new Event('change', { bubbles: true }));
                        };

                        // Handy may emit its own delayed input event after the
                        // command reaches LIGHT. Keep this one focused field at
                        // the requested value briefly, then remove the guard so
                        // normal user typing immediately resumes afterward.
                        const previousGuard = active.__lightTypeGuard;
                        if (previousGuard) {
                            active.removeEventListener('input', previousGuard.listener);
                            clearTimeout(previousGuard.timer);
                            clearInterval(previousGuard.interval);
                        }
                        const expiresAt = Date.now() + guardMs;
                        const listener = () => {
                            if (Date.now() <= expiresAt && active.value !== typedText) {
                                setExactValue();
                            }
                        };
                        active.addEventListener('input', listener);
                        const interval = setInterval(() => {
                            if (Date.now() <= expiresAt && active.value !== typedText) {
                                setExactValue();
                            }
                        }, 50);
                        const timer = setTimeout(() => {
                            active.removeEventListener('input', listener);
                            clearInterval(interval);
                            delete active.__lightTypeGuard;
                        }, guardMs);
                        active.__lightTypeGuard = { listener, interval, timer };

                        setExactValue();
                        active.focus();
                        return true;
                    }
                    return false;
                }""",
                {"text": text, "guardMs": BROWSER_TYPE_GUARD_MS},
            )
            if typed:
                log_browser(f"Typed '{text}' into browser input.")
            return bool(typed)
        except Exception as err:
            log_debug(f"type_in_browser failed: {err}")
            return False

    def scroll(self, direction: str = "down"):
        self.start()
        self._unfocus_inputs()
        direction = direction.lower().strip()

        if direction == "down":
            self.page.mouse.wheel(0, 500)
            try:
                self.page.evaluate("() => window.scrollBy(0, 500)")
            except Exception as err:
                log_debug(f"window.scrollBy fallback skipped: {err}")
        elif direction == "up":
            self.page.mouse.wheel(0, -500)
            try:
                self.page.evaluate("() => window.scrollBy(0, -500)")
            except Exception as err:
                log_debug(f"window.scrollBy fallback skipped: {err}")
        else:
            raise ValueError(f"Invalid scroll direction: {direction}")

    def find_element(self, text: str) -> bool:
        try:
            self.locate_element_in_viewport(text)
            log_browser(f"Found element matching: '{text}'")
            return True
        except Exception as err:
            log_debug(f"find_element did not match '{text}': {err}")
            log_browser(f"Element not found: '{text}'")
            return False

    # ==========================================
    # OBSERVATION & COPY RANGE
    # ==========================================

    def get_current_url(self) -> str | None:
        if not self.is_active():
            return None
        return self.page.url

    def get_title(self) -> str:
        self.start()
        title = self.page.title()
        log_browser(f"Page title: {title}")
        return title

    def get_visible_text(self, max_chars: int = 500) -> str:
        self.start()
        text = self.page.locator("body").inner_text(timeout=BROWSER_TIMEOUT_MS)
        cleaned = " ".join(text.split())
        snippet = cleaned[:max_chars]
        log_browser(f"Visible text: {snippet}")
        return snippet

    def clear_highlights(self):
        """Deterministically restore original styles on any elements highlighted by copy_text_range."""
        if not self.is_active():
            return
        try:
            self.page.evaluate(
                """() => {
                    const highlighted = document.querySelectorAll('[data-light-highlighted="true"]');
                    for (const el of highlighted) {
                        el.style.backgroundColor = el.getAttribute('data-light-orig-bg') || '';
                        el.style.transition = el.getAttribute('data-light-orig-transition') || '';
                        el.removeAttribute('data-light-highlighted');
                        el.removeAttribute('data-light-orig-bg');
                        el.removeAttribute('data-light-orig-transition');
                    }
                }"""
            )
        except Exception as err:
            log_debug(f"clear_highlights skipped: {err}")

    def copy_text_range(self, target: str | None = None, highlight_ms: int = HIGHLIGHT_DURATION_MS) -> str:
        """
        Copy text from the webpage to the Windows clipboard.
        - Matches case-insensitively while preserving original document capitalization.
        - Slices inclusively from start_phrase through end_phrase.
        - Raises clear ValueErrors for missing or ambiguous start/end phrases.
        - Safely highlights the most specific matched element and restores original styles.
        """
        self.start()
        self._unfocus_inputs()

        if not target:
            selected = self.page.evaluate("() => window.getSelection().toString()")
            if not selected or not selected.strip():
                raise ValueError("No text is currently selected on the page.")
            self._write_and_verify_clipboard(selected)
            log_browser(f"Copied selected text ({len(selected)} chars) to clipboard.")
            return selected

        if "|||" in target:
            start_phrase, end_phrase = [p.strip() for p in target.split("|||", 1)]
        else:
            start_phrase, end_phrase = target.strip(), ""

        if not start_phrase:
            raise ValueError("Start phrase cannot be empty.")

        extracted = self.page.evaluate(
            r"""(params) => {
                const startLow = params.start.toLowerCase();
                const endLow = params.end.toLowerCase();
                const fullText = document.body.innerText || '';
                const fullLow = fullText.toLowerCase();

                const startPositions = [];
                const startLengths = [];
                let searchPos = 0;
                while (searchPos <= fullLow.length) {
                    const idx = fullLow.indexOf(startLow, searchPos);
                    if (idx === -1) break;
                    startPositions.push(idx);
                    startLengths.push(params.start.length);
                    searchPos = idx + Math.max(1, startLow.length);
                }

                if (startPositions.length === 0) {
                    const words = startLow.split(/[^a-z0-9]+/i).filter(Boolean);
                    if (words.length > 0) {
                        const escaped = words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
                        const rx = new RegExp(escaped.join('[\\s\\-.,;:\'"()\\[\\]]+'), 'gi');
                        let m;
                        while ((m = rx.exec(fullText)) !== null) {
                            startPositions.push(m.index);
                            startLengths.push(m[0].length);
                        }
                    }
                }

                if (startPositions.length === 0) {
                    return { found: false, reason: `Could not find start phrase: '${params.start}'` };
                }

                const validRanges = [];
                for (let i = 0; i < startPositions.length; i++) {
                    const sIdx = startPositions[i];
                    const sLen = startLengths[i] || params.start.length;
                    if (!endLow) {
                        validRanges.push([sIdx, sIdx + sLen]);
                    } else {
                        const eIdx = fullLow.indexOf(endLow, sIdx + sLen);
                        if (eIdx !== -1) {
                            const nextStart = (i + 1 < startPositions.length) ? startPositions[i + 1] : Infinity;
                            if (eIdx < nextStart) {
                                validRanges.push([sIdx, eIdx + params.end.length]);
                            }
                        }
                    }
                }

                if (validRanges.length === 0) {
                    return {
                        found: false,
                        reason: `Could not find end phrase: '${params.end}' after '${params.start}'`
                    };
                }

                if (validRanges.length > 1 && endLow) {
                    return {
                        found: false,
                        reason: `Ambiguous text range: matched ${validRanges.length} passages from '${params.start}' to '${params.end}'. Please specify more words.`
                    };
                }

                const [startIdx, endIdx] = validRanges[0];
                const slice = fullText.slice(startIdx, endIdx).trim();

                // Highlight the most specific (smallest text length) matching DOM element
                const matchingBlocks = Array.from(document.querySelectorAll('p, li, blockquote, article, div, span'))
                    .filter(el => {
                        const txt = (el.innerText || '').toLowerCase();
                        return txt.includes(startLow) && (!endLow || txt.includes(endLow));
                    })
                    .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);

                if (matchingBlocks.length > 0) {
                    const el = matchingBlocks[0];
                    el.scrollIntoView({ block: 'center' });
                    if (!el.hasAttribute('data-light-highlighted')) {
                        el.setAttribute('data-light-orig-bg', el.style.backgroundColor || '');
                        el.setAttribute('data-light-orig-transition', el.style.transition || '');
                        el.setAttribute('data-light-highlighted', 'true');
                    }
                    el.style.transition = 'background-color 0.4s ease';
                    el.style.backgroundColor = 'rgba(255, 235, 59, 0.45)';
                    setTimeout(() => {
                        if (el.getAttribute('data-light-highlighted') === 'true') {
                            el.style.backgroundColor = el.getAttribute('data-light-orig-bg') || '';
                            el.style.transition = el.getAttribute('data-light-orig-transition') || '';
                            el.removeAttribute('data-light-highlighted');
                            el.removeAttribute('data-light-orig-bg');
                            el.removeAttribute('data-light-orig-transition');
                        }
                    }, params.highlightMs || 3000);
                }

                return { found: true, text: slice };
            }""",
            {"start": start_phrase, "end": end_phrase, "highlightMs": highlight_ms},
        )

        if not extracted or not extracted.get("found"):
            reason = extracted.get("reason") if extracted else f"Could not find text matching '{target}'."
            raise ValueError(reason)

        copied_text = extracted["text"]
        self._write_and_verify_clipboard(copied_text)
        preview = copied_text[:120] + ("..." if len(copied_text) > 120 else "")
        log_browser(f"Copied to clipboard ({len(copied_text)} chars): \"{preview}\"")
        return copied_text

    def _write_and_verify_clipboard(self, text: str) -> bool:
        """Write `text` to system clipboard and verify read-back where available."""
        try:
            pyperclip.copy(text)
            pasted = pyperclip.paste()
            if pasted != text:
                log_warning("Clipboard verification mismatch after copy.")
                return False
            return True
        except Exception as err:
            log_warning(f"System clipboard unavailable: {err}")
            return False

    # ==========================================
    # CLOSE BROWSER
    # ==========================================

    def close(self):
        attached_cdp = getattr(self, "_attached_over_cdp", False)

        if self.context is not None:
            if not attached_cdp:
                try:
                    self.context.close()
                except Exception as err:
                    log_debug(f"Browser context close ignored error: {err}")
            self.context = None
            self.page = None

        if self.browser is not None:
            if not attached_cdp:
                try:
                    self.browser.close()
                except Exception as err:
                    log_debug(f"Browser close ignored error: {err}")
            self.browser = None
            self.page = None

        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception as err:
                log_debug(f"Playwright stop ignored error: {err}")
            self.playwright = None

        self._attached_over_cdp = False
