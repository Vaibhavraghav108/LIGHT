import laya

from brain.commands import Command, Action
from brain.decision import (
    preprocess_text,
    parse_deterministic_command,
    extract_target,
    validate_command,
)
from config import LAYA_MODEL
from utils.logger import log_laya


class Laya:

    def __init__(self, agent=None):
        if agent is not None:
            self.agent = agent
        else:
            log_laya("Loading model...")
            self.agent = laya.load(LAYA_MODEL)
            log_laya("Model loaded.")

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

    def understand(self, text: str, state=None) -> Command:
        cleaned = preprocess_text(text)

        if not cleaned:
            raise ValueError("Empty command")

        # 1. Check deterministic commands first (fast & safe)
        deterministic_cmd = parse_deterministic_command(cleaned, state=state)
        if deterministic_cmd is not None:
            return deterministic_cmd

        # 2. Fall back to Laya model prediction
        result = self.agent.predict(cleaned, self.questions)
        action_name = result["answers"]["action"]["choice"]
        action = Action(action_name.lower())

        log_laya(f"Predicted: {action.value}")

        # 3. Extract target and validate prediction
        target = self._extract_target(cleaned, action)
        command = Command(action, target)

        return validate_command(cleaned, command)

    def _extract_target(self, text: str, action: Action) -> str | None:
        return extract_target(text, action)