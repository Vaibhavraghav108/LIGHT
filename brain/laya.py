import laya

from brain.commands import Command, Action
from brain.decision import (
    preprocess_text,
    parse_deterministic_command,
    parse_multi_command,
    parse_complex_fallback,
    normalize_command_plan,
    extract_target,
    validate_command,
)
from brain.llm import QwenPlanner
from config import LAYA_MODEL
from utils.logger import log_laya


class Laya:

    def __init__(self, agent=None, llm_planner: QwenPlanner | None = None):
        if agent is not None:
            self.agent = agent
        else:
            log_laya("Loading model...")
            self.agent = laya.load(LAYA_MODEL)
            log_laya("Model loaded.")

        # If a unit test passes a mock `agent` without an explicit `llm_planner`,
        # disable live network Ollama calls by default so unit tests stay fast and isolated.
        if llm_planner is not None:
            self.llm = llm_planner
        elif agent is not None:
            self.llm = QwenPlanner(enabled=False)
        else:
            self.llm = QwenPlanner()

        self.questions = {
            "action": {
                "instructions": "What action should the computer perform?",
                "type": "choice",
                "criteria": [
                    "OPEN_APP",
                    "CLOSE_APP",
                    "OPEN_URL",
                    "TYPE",
                    "CLICK",
                    "SCROLL",
                    "PRESS_KEY",
                    "MOVE_MOUSE",
                    "WAIT",
                    "STOP",
                ],
            }
        }

    def understand_many(self, text: str, state=None) -> list[Command]:
        """
        Parse spoken text into one or more ordered LIGHT Commands.
        Order of precedence:
        1. Fast Path: Multi-step deterministic parser (<1ms)
        2. Fast Path: Single-step deterministic parser (<1ms)
        3. Complex Path: Qwen3 1.7B local LLM via Ollama + Plan Normalization
        4. Complex Fallback: Deterministic complex search-and-open fallback + Plan Normalization
        5. Fallback: Laya classifier + strict safety validation
        """
        cleaned = preprocess_text(text)
        if not cleaned:
            raise ValueError("Empty command")

        # 1. Fast Path: Multi-step deterministic clauses
        multi_cmds = parse_multi_command(text, state=state)
        if multi_cmds:
            return multi_cmds

        # 2. Fast Path: Single-step deterministic command
        deterministic_cmd = parse_deterministic_command(cleaned, state=state)
        if deterministic_cmd is not None:
            return [deterministic_cmd]

        # 3. Complex Path: Optional Qwen3 1.7B LLM planner
        if self.llm is not None and self.llm.enabled:
            llm_cmds = self.llm.plan_actions(text, state=state)
            if llm_cmds:
                return llm_cmds

        # 4. Deterministic fallback for complex natural search phrases if LLM is offline/disabled
        complex_fallback = parse_complex_fallback(text, state=state)
        if complex_fallback:
            return complex_fallback

        # 5. Reject single unrelated words (e.g., "Cricket") before invoking Laya classifier
        if len(cleaned.split()) == 1:
            raise ValueError(f"Ignored unrelated single-word speech: '{cleaned}'")

        # 6. Fallback to Laya model prediction + safety validation
        result = self.agent.predict(cleaned, self.questions)
        action_name = result["answers"]["action"]["choice"]
        action = Action(action_name.lower())

        log_laya(f"Predicted: {action.value}")

        target = self._extract_target(cleaned, action)
        command = Command(action, target)

        return [validate_command(cleaned, command)]

    def understand(self, text: str, state=None) -> Command:
        commands = self.understand_many(text, state=state)
        return commands[0]

    def _extract_target(self, text: str, action: Action) -> str | None:
        return extract_target(text, action)