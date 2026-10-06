"""Lower plans to existing Commands. Never executes or implements a backend."""

from brain.commands import Action, Command
from core.capabilities import CapabilityError, CapabilityPlan, CapabilityRegistry
from core.tasks import TaskRecord


class CapabilityAdapter:
    _TARGETS = {
        "browser.open_site": (Action.OPEN_URL, "url"),
        "browser.scroll": (Action.SCROLL, "direction"),
        "browser.activate": (Action.CLICK_ELEMENT, "target"),
        "desktop.open_app": (Action.OPEN_APP, "app"),
        "desktop.switch_window": (Action.SWITCH_WINDOW, "target"),
        "keyboard.type": (Action.TYPE, "text"),
        "keyboard.press": (Action.PRESS_KEY, "key"),
    }

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def lower(self, plan: CapabilityPlan, *, task: TaskRecord,
              generation: int, cancelled: bool = False) -> Command:
        self.registry.validate(plan, task=task, generation=generation, cancelled=cancelled)
        if plan.capability == "browser.search":
            return Command(Action.SEARCH,
                           f"{plan.arguments.get('engine', 'google')}:{plan.arguments['query']}")
        if plan.capability not in self._TARGETS:
            raise CapabilityError("No existing action adapter for capability")
        action, argument = self._TARGETS[plan.capability]
        return Command(action, plan.arguments[argument])
