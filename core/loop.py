import time

from config import DUPLICATE_COOLDOWN_SECONDS, POLL_INTERVAL
from core.state import LightState
from utils.logger import (
    log_command,
    log_debug,
    log_error,
    log_executor,
    log_info,
    log_voice,
)


class LightLoop:

    def __init__(
        self,
        handy,
        laya,
        executor,
        state: LightState | None = None,
        duplicate_cooldown: float = DUPLICATE_COOLDOWN_SECONDS,
    ):
        self.handy = handy
        self.laya = laya
        self.executor = executor
        self.state = state if state is not None else getattr(executor, "state", LightState())
        self.executor.state = self.state
        self.duplicate_cooldown = duplicate_cooldown

    def process_text(self, text: str) -> str:
        """
        Process a single voice transcription string through Laya and Executor.
        Returns "OK", "IGNORED", "ERROR", or "STOP".
        """
        log_voice(text)

        # 1. Understand & Validate Command
        try:
            command = self.laya.understand(text, state=self.state)
            log_command(f"Action: {command.action.value} | Target: {command.target}")
        except Exception as error:
            self.state.record_failure(text, status="IGNORED", error_message=str(error))
            log_error(f"Command ignored: {error}")
            log_info("Continuing to listen...")
            return "IGNORED"

        # 2. Execute Command
        try:
            execution_result = self.executor.execute(command, raw_text=text)
            log_executor(str(execution_result))
            return execution_result
        except Exception as error:
            self.state.record_failure(text, status="ERROR", error_message=str(error))
            log_error(f"Could not execute command: {error}")
            log_info("Continuing to listen...")
            return "ERROR"

    def run(self, max_iterations: int | None = None):
        log_info("Listening for commands...")
        log_info("Say 'stop' to exit.\n")

        # Remember current transcription at startup so we only run new commands
        try:
            latest = self.handy.get_latest_transcription()
        except Exception as error:
            log_error(f"Failed to read initial transcription: {error}")
            latest = None

        if latest is not None:
            last_id = latest["id"]
            last_text = (latest["text"] or "").strip()
        else:
            last_id = None
            last_text = ""

        last_time = 0.0
        iterations = 0

        try:
            while True:
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                try:
                    result = self.handy.get_latest_transcription()
                except Exception as error:
                    log_error(f"Database read error: {error}")
                    time.sleep(POLL_INTERVAL)
                    continue

                if result is None or result["id"] == last_id:
                    time.sleep(POLL_INTERVAL)
                    continue

                last_id = result["id"]
                text = (result["text"] or "").strip()

                if not text:
                    time.sleep(POLL_INTERVAL)
                    continue

                now = time.monotonic()
                if text.lower() == last_text.lower() and (now - last_time) < self.duplicate_cooldown:
                    log_debug(f"Ignored immediate duplicate transcription: '{text}'")
                    time.sleep(POLL_INTERVAL)
                    continue

                last_text = text
                last_time = now

                status = self.process_text(text)

                if status == "STOP":
                    log_info("Stopped.")
                    break

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log_info("Interrupted by user. Shutting down...")
        finally:
            try:
                self.executor.browser.close()
            except Exception as err:
                log_debug(f"Browser close cleanup ignored error: {err}")