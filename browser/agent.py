import asyncio
import os
import threading
from config import BROWSER_USE_CONFIG_DIR, LLM_TIMEOUT
from providers.ai import AIProvider, build_ai_provider
from providers.configuration import load_provider_settings
from utils.logger import log_browser, log_debug, log_info, log_warning


class AutonomousBrowserAgent:
    """
    Subordinate autonomous browser agent powered by browser-use.
    Used ONLY for open-ended, complex, goal-oriented research and comparison tasks.
    Reuses LIGHT's explicitly selected AI provider and model.
    Remains strictly under LIGHT's priority STOP and cancellation control.
    """

    def __init__(self, ai_provider: AIProvider | None = None):
        # browser-use defaults optional telemetry/cloud sync to enabled and
        # otherwise writes under the user's global config directory. Reassert
        # LIGHT's private, workspace-local defaults before its lazy import.
        os.environ.setdefault("BROWSER_USE_CONFIG_DIR", str(BROWSER_USE_CONFIG_DIR))
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
        os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
        self._running = False
        self._lock = threading.Lock()
        self._current_agent = None
        self.ai_provider = ai_provider or build_ai_provider(load_provider_settings().ai)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def cancel(self):
        """Cancel the running browser agent immediately."""
        with self._lock:
            if self._current_agent and hasattr(self._current_agent, "stop"):
                try:
                    self._current_agent.stop()
                except Exception:
                    pass
            self._running = False

    def run_task(self, task_instruction: str, max_steps: int = 5, cancel_event=None) -> dict:
        """
        Run autonomous task synchronously and return result dict.
        Safe to call from both within and outside an active asyncio event loop.
        """
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "final_result": "CANCELLED"}

        def _run_in_new_loop():
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(
                    self.execute_task(task_prompt=task_instruction, max_steps=max_steps, cancel_event=cancel_event)
                )
            finally:
                try:
                    new_loop.close()
                except Exception:
                    pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_in_new_loop)
                res = future.result()
        else:
            res = _run_in_new_loop()

        cancelled = (cancel_event is not None and cancel_event.is_set()) or res == "CANCELLED"
        success = (not cancelled) and res.startswith("AGENT_COMPLETED")
        return {"success": success, "cancelled": cancelled, "final_result": res}

    async def run_task_async(self, task_instruction: str, max_steps: int = 5, cancel_event=None) -> dict:
        """Run autonomous task asynchronously when called from within an active event loop."""
        if cancel_event is not None and cancel_event.is_set():
            return {"success": False, "cancelled": True, "final_result": "CANCELLED"}

        res = await self.execute_task(task_instruction, max_steps=max_steps, cancel_event=cancel_event)
        cancelled = (cancel_event is not None and cancel_event.is_set()) or res == "CANCELLED"
        success = (not cancelled) and res.startswith("AGENT_COMPLETED")
        return {"success": success, "cancelled": cancelled, "final_result": res}

    def _get_llm(self):
        """
        Initialize Browser Use's native wrapper for the explicitly selected AI
        provider and model. Provider selection never falls back implicitly.
        """
        provider = (
            self.ai_provider.runtime_name
            if self.ai_provider.provider_name == "local"
            else self.ai_provider.provider_name
        ).replace("_", " ").title()
        model = self.ai_provider.model
        endpoint = self.ai_provider.config.base_url or "provider default"
        # On local CPU, complex schema generation requires adequate timeout (>=180s)
        timeout = max(float(self.ai_provider.config.timeout or LLM_TIMEOUT), 180.0)

        log_info(f"[AGENT] LLM provider: {provider}")
        log_info(f"[AGENT] LLM model: {model}")
        log_info(f"[AGENT] LLM endpoint: {endpoint}")

        try:
            llm = self.ai_provider.create_browser_use_llm(timeout=timeout)
            log_info("[AGENT] Browser Use initialized")
            return llm
        except Exception:
            # Third-party SDK exceptions can echo request headers or URLs.
            # Keep the user-facing failure useful without exposing credentials.
            msg = f"Failed to initialize {provider} model '{model}'. Check provider status and credentials."
            log_warning(f"[AGENT] {msg}")
            raise RuntimeError(msg)

    async def execute_task(
        self,
        task_prompt: str = "",
        max_steps: int = 5,
        cancel_event=None,
        task_instruction: str = "",
    ) -> str:
        """
        Execute an autonomous browser agent task with Browser Use asynchronously.
        Compatible with LIGHT's active event loop.
        Monitors cancel_event (<5ms STOP responsiveness) and aborts immediately when set.
        """
        effective_prompt = (task_prompt or task_instruction or "").strip()
        if cancel_event is not None and cancel_event.is_set():
            return "CANCELLED"

        if not effective_prompt:
            raise ValueError("No task prompt provided for autonomous browser agent.")

        log_browser(f"[AGENT_TASK] Starting autonomous browser goal: '{effective_prompt}'")

        try:
            from browser_use import Agent, Browser
        except ImportError:
            msg = "browser-use is not installed in the environment."
            log_warning(f"[AGENT_TASK] {msg}")
            return f"AGENT_UNAVAILABLE: {msg}"

        try:
            llm = self._get_llm()
        except Exception as err:
            log_warning(f"[AGENT_TASK] Initialization failed: {err}")
            return f"AGENT_INIT_FAILED: {err}"

        with self._lock:
            self._running = True

        browser = Browser(headless=True)
        agent = Agent(
            task=task_prompt,
            llm=llm,
            use_vision=False,
            flash_mode=True,
            browser=browser,
            llm_timeout=180,
        )
        with self._lock:
            self._current_agent = agent

        agent_task = asyncio.create_task(agent.run(max_steps=max_steps))

        async def _poll_cancel():
            while not agent_task.done():
                if cancel_event is not None and cancel_event.is_set():
                    log_browser("[AGENT_TASK] STOP detected during agent execution! Aborting agent...")
                    try:
                        if hasattr(agent, "stop"):
                            agent.stop()
                    except Exception:
                        pass
                    agent_task.cancel()
                    break
                await asyncio.sleep(0.01)

        cancel_poller = asyncio.create_task(_poll_cancel())
        try:
            history = await agent_task
            cancel_poller.cancel()

            final = history.final_result()
            if not final:
                extracted = history.extracted_content()
                if extracted:
                    final = "\n".join(str(e) for e in extracted if e)
                elif history.is_successful():
                    final = "Goal completed successfully."
                else:
                    errs = history.errors()
                    final = f"Incomplete: {errs[-1]}" if errs else "Agent completed navigation steps."

            is_success = (history.is_successful() is True)
            if is_success:
                return f"AGENT_COMPLETED: {final}"
            return f"AGENT_FAILED: {final}"
        except asyncio.CancelledError:
            log_browser("[AGENT_TASK] Agent task was cancelled by STOP/Cancel.")
            return "CANCELLED"
        except Exception as err:
            if cancel_event is not None and cancel_event.is_set():
                return "CANCELLED"
            log_warning(f"[AGENT_TASK] Error during agent execution: {err}")
            return f"ERROR: {err}"
        finally:
            cancel_poller.cancel()
            with self._lock:
                self._current_agent = None
                self._running = False
            try:
                await browser.close()
            except Exception:
                pass
