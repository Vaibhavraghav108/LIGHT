import os
import re
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
        1. Explicit executable_path (if provided)
        2. Playwright-managed Chromium (executable_path=None)
        3. Workspace-local Playwright Chromium binaries (.playwright-browsers)
        4. Installed Google Chrome candidate paths that exist on disk
        5. Configured Brave candidate paths as final fallback
        """
        from config import get_chrome_candidate_paths, get_workspace_chromium_candidate_paths

        candidates: list[tuple[str, str | None]] = []
        seen: set[str | None] = set()

        if self.executable_path:
            candidates.append(("Custom Browser", str(self.executable_path)))
            seen.add(str(self.executable_path))

        # 1. Playwright-managed Chromium (primary default)
        candidates.append(("Playwright Chromium", None))
        seen.add(None)

        # 2. Workspace-local Playwright Chromium binaries
        for path in get_workspace_chromium_candidate_paths():
            try:
                if path.exists():
                    resolved = str(path)
                    if resolved not in seen:
                        candidates.append(("Workspace Chromium", resolved))
                        seen.add(resolved)
            except OSError:
                continue

        # 3. Installed Google Chrome
        for path in get_chrome_candidate_paths():
            try:
                if path.exists():
                    resolved = str(path)
                    if resolved not in seen:
                        candidates.append(("Chrome", resolved))
                        seen.add(resolved)
            except OSError:
                continue

        # 4. Brave as final fallback
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
        """Attempt to launch browser/context with a specific executable_path (or None for Playwright Chromium)."""
        if self.user_data_dir:
            try:
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
                return
            except Exception as persistent_err:
                log_debug(
                    f"Persistent context launch failed for {exe_path or 'Playwright Chromium'} ({persistent_err}); retrying ephemeral launch..."
                )
                self.context = None

        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            executable_path=exe_path,
            args=launch_args,
        )
        self.page = self.browser.new_page(no_viewport=not self.headless)

    def start(self):
        if self.is_active():
            return

        if self.browser is not None or self.context is not None or self.playwright is not None:
            self.close()

        self.playwright = sync_playwright().start()
        launch_args = ["--start-maximized"] if not self.headless else []
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

        self.page.goto(
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
    # SEARCH (GOOGLE / YOUTUBE)
    # ==========================================

    def search(self, query: str, engine: str | None = None):
        """Search on YouTube or Google using Playwright."""
        self.start()

        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty.")

        current_url = (self.page.url or "").lower()
        if engine is None:
            if "youtube.com" in current_url:
                engine = "youtube"
            else:
                engine = "google"

        engine = engine.lower().strip()

        if engine == "youtube":
            self.search_youtube(query)
        else:
            self.search_google(query)

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
                    self._unfocus_inputs()
                    return
            except Exception as err:
                log_debug(f"YouTube DOM search box fallback: {err}")

        search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        self.page.goto(search_url, wait_until="domcontentloaded")
        self._unfocus_inputs()

    def search_google(self, query: str):
        self.start()
        log_browser(f"Searching Google for: {query}")

        current_url = (self.page.url or "").lower()
        if "google" in current_url:
            try:
                search_box = self.page.locator("textarea[name='q'], input[name='q']").first
                if search_box.is_visible(timeout=2000):
                    search_box.click()
                    search_box.fill(query)
                    search_box.press("Enter")
                    self.page.wait_for_load_state("domcontentloaded")
                    self._unfocus_inputs()
                    return
            except Exception as err:
                log_debug(f"Google DOM search box fallback: {err}")

        search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        self.page.goto(search_url, wait_until="domcontentloaded")
        self._unfocus_inputs()

    # ==========================================
    # TARGET PARSING & COORDINATE CONVERSION
    # ==========================================

    def parse_element_target(self, raw_target: str) -> dict:
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

    def locate_element_in_viewport(self, target: str, perform_click: bool = False) -> dict:
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
        }

        info = self.page.evaluate(
            """(params) => {
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
                    const clickable = el.closest('a[href], button, [role="button"], [role="link"]') || el;
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
                        rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
                        matched: (clickable.innerText || clickable.getAttribute('aria-label') || clickable.getAttribute('title') || clickable.getAttribute('placeholder') || clickable.tagName || '').trim().slice(0, 60),
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
                    let selectors = 'ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title-link, a#video-title, a#video-title-link, a[href*="/shorts/"], a:has(h3), div#search a h3, main a[href], article a[href], a[href]';
                    if (url.includes('youtube.com')) {
                        selectors = 'ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title-link, a#video-title, a#video-title-link, a[href*="/shorts/"]';
                    } else if (url.includes('google.com')) {
                        selectors = 'a:has(h3), div#search a h3';
                    }
                    const nodes = Array.from(document.querySelectorAll(selectors)).filter(isVisible);
                    const chosen = nodes[Math.max(0, params.index - 1)];
                    if (!chosen) return { found: false };
                    return computeSafePoint(chosen);
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

                for (const term of params.terms) {
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
                        if (!exactMatch && !containsMatch) continue;

                        let score = exactMatch ? 200 : 80;

                        const tag = el.tagName.toLowerCase();
                        const role = (el.getAttribute('role') || '').toLowerCase();
                        const isButton = (tag === 'button' || role === 'button');
                        const isLink = (tag === 'a' || role === 'link' || role === 'tab');

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
            raise ValueError(f"Could not find a visible element matching '{target}'.")

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

    def move_mouse_to_element(self, target: str, mouse_controller) -> tuple[int, int]:
        screen_size = mouse_controller.get_screen_size()
        info = self.locate_element_in_viewport(target)
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
    # DOM INTERACTION
    # ==========================================

    def _settle_after_click(self):
        try:
            self.page.wait_for_timeout(80)
            self.page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception as err:
            log_debug(f"Post-click load state wait skipped: {err}")

    def click_result(self, index: int = 1, mouse_controller=None):
        if index < 1:
            index = 1
        log_browser(f"Clicking result #{index}...")
        target_str = f"result {index}"
        if mouse_controller is not None:
            self.move_mouse_to_element(target_str, mouse_controller)
        self.locate_element_in_viewport(target_str, perform_click=True)
        self._settle_after_click()
        self._unfocus_inputs()

    def click_element(self, text: str, mouse_controller=None):
        log_browser(f"Clicking element: '{text}'")
        if mouse_controller is not None:
            self.move_mouse_to_element(text, mouse_controller)
        info = self.locate_element_in_viewport(text, perform_click=True)
        self._settle_after_click()

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
            """(params) => {
                const startLow = params.start.toLowerCase();
                const endLow = params.end.toLowerCase();
                const fullText = document.body.innerText || '';
                const fullLow = fullText.toLowerCase();

                const startPositions = [];
                let searchPos = 0;
                while (searchPos <= fullLow.length) {
                    const idx = fullLow.indexOf(startLow, searchPos);
                    if (idx === -1) break;
                    startPositions.push(idx);
                    searchPos = idx + Math.max(1, startLow.length);
                }

                if (startPositions.length === 0) {
                    return { found: false, reason: `Could not find start phrase: '${params.start}'` };
                }

                const validRanges = [];
                for (let i = 0; i < startPositions.length; i++) {
                    const sIdx = startPositions[i];
                    if (!endLow) {
                        validRanges.push([sIdx, sIdx + params.start.length]);
                    } else {
                        const eIdx = fullLow.indexOf(endLow, sIdx + params.start.length);
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

                if (validRanges.length > 1) {
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
