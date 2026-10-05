import atexit
import os
import re
import subprocess
from pathlib import Path

from computer.platform_factory import get_platform_controller
from voice.factory import get_voice_provider
from brain.laya import Laya
from brain.llm import QwenPlanner
from core.executor import Executor
from core.loop import LightLoop
from core.state import LightState
from utils.logger import log_info, log_debug
from providers.configuration import load_provider_settings
from providers.ai import build_ai_provider

PID_FILE = Path(__file__).resolve().parent / ".light.pid"


def _get_protected_pids() -> set[int]:
    """
    Return the set of PIDs belonging to the current process and its parent launcher shim.
    On Windows, `lightenv\\Scripts\\python.exe` (os.getppid()) spawns the base
    `Python312\\python.exe` (os.getpid()) as a child process with the same `main.py`
    command line, so both must be protected.
    """
    protected = {os.getpid()}
    ppid = os.getppid()
    if ppid and ppid > 0:
        protected.add(ppid)
    return protected


def _kill_pid_tree(pid: int, protected_pids: set[int] | None = None) -> bool:
    """Terminate a stale process and its child tree if it is not our own process/shim."""
    protected = protected_pids or _get_protected_pids()
    if pid <= 0 or pid in protected:
        return False
    try:
        platform = get_platform_controller()
        cmd = platform.get_kill_pid_tree_command(pid)
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            log_info(f"Terminated previous LIGHT instance (PID {pid}).")
            return True
    except Exception as err:
        log_debug(f"Could not terminate PID {pid}: {err}")
    return False


def ensure_single_instance(pid_file: Path = PID_FILE) -> list[int]:
    """
    Ensure only the newly started main.py process is running.
    1. Kills any previous PID recorded in `.light.pid` (excluding current PID & venv parent shim PID).
    2. Scans Windows `Win32_Process` for any other `python.exe` running `main.py`
       and terminates it before starting the new loop.
    3. Writes the current PID to `.light.pid` and cleans it up on exit.
    """
    protected_pids = _get_protected_pids()
    current_pid = os.getpid()
    killed_pids: list[int] = []

    # 1. Check previous lockfile PID
    if pid_file.exists():
        try:
            old_pid_str = pid_file.read_text(encoding="utf-8").strip()
            if old_pid_str.isdigit():
                old_pid = int(old_pid_str)
                if old_pid not in protected_pids and _kill_pid_tree(old_pid, protected_pids):
                    killed_pids.append(old_pid)
        except Exception as err:
            log_debug(f"PID file check skipped: {err}")

    # 2. Scan process table for any other `python* main.py` instance
    try:
        platform = get_platform_controller()
        scan_cmd = platform.get_process_scan_command("main.py")
        proc = subprocess.run(
            scan_cmd,
            capture_output=True,
            text=True,
            timeout=4,
        )
        rows: list[tuple[int, int]] = platform.parse_process_scan_output(proc.stdout or "")
        for p_id, pp_id in rows:
            if p_id in protected_pids and pp_id > 0:
                protected_pids.add(pp_id)

        for candidate_pid, candidate_ppid in rows:
            if (
                candidate_pid not in protected_pids
                and candidate_ppid not in protected_pids
                and candidate_pid not in killed_pids
            ):
                if _kill_pid_tree(candidate_pid, protected_pids):
                    killed_pids.append(candidate_pid)
    except Exception as err:
        log_debug(f"Process scan for stale main.py skipped: {err}")

    # 3. Record current PID and register cleanup on exit
    try:
        pid_file.write_text(str(current_pid), encoding="utf-8")
    except Exception as err:
        log_debug(f"Could not write PID file: {err}")

    def _cleanup_pid_file():
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(current_pid):
                pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup_pid_file)
    return killed_pids


def main():
    print("================================")
    print("        LIGHT STARTING")
    print("================================\n")

    # Automatically kill any stale old main.py processes before starting
    ensure_single_instance()

    # Load components
    provider_settings = load_provider_settings()
    state = LightState()
    voice_provider = get_voice_provider(provider_config=provider_settings.stt)
    log_info(
        "STT selection: "
        f"provider={provider_settings.stt.provider} runtime={provider_settings.stt.runtime} "
        f"model={provider_settings.stt.model or 'service-managed'}"
    )
    log_info(
        "AI selection: "
        f"provider={provider_settings.ai.provider} runtime={provider_settings.ai.runtime or 'api'} "
        f"model={provider_settings.ai.model} enabled={provider_settings.ai.enabled}"
    )
    ai_provider = build_ai_provider(provider_settings.ai)
    laya = Laya(llm_planner=QwenPlanner(ai_provider=ai_provider))
    executor = Executor(state=state, ai_provider=ai_provider)

    # Create LIGHT loop
    light = LightLoop(
        handy=voice_provider,
        laya=laya,
        executor=executor,
        state=state,
    )

    # Start continuous listening
    light.run()


if __name__ == "__main__":
    main()
