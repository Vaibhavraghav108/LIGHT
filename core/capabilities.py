"""Pure capability definitions and single-step plans; no backend imports or I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from core.tasks import TaskRecord, TaskStatus


class CapabilityError(ValueError):
    """A plan cannot be admitted or dispatched safely."""


class Backend(str, Enum):
    PLAYWRIGHT = "playwright"
    PLATFORM = "platform"
    # Existing TYPE chooses DOM typing or OS typing based on foreground state.
    FOREGROUND_KEYBOARD = "foreground_keyboard"


class ExecutionMode(str, Enum):
    ORDERED = "ordered"


class PlanSource(str, Enum):
    INTERNAL = "internal"  # No semantic compiler / untrusted producer yet.


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verification(str, Enum):
    BROWSER_READINESS = "existing_browser_readiness_checks"
    ELEMENT_AND_READINESS = "existing_element_and_browser_readiness_checks"
    FOREGROUND = "existing_foreground_checks"
    NONE = "no_independent_postcondition"


@dataclass(frozen=True)
class Argument:
    name: str
    value_type: type = str
    required: bool = True
    default: str | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Capability:
    name: str
    purpose: str
    arguments: tuple[Argument, ...]
    backends: tuple[Backend, ...]
    risk: Risk
    verification: Verification
    state_effects: str
    confirmation_required: bool = False
    requires_active_browser: bool = False
    execution_mode: ExecutionMode = ExecutionMode.ORDERED
    cancellation: str = "Generation gate before dispatch; existing cooperative backend checks"
    timeout: str = "Existing backend timeouts only; no universal deadline or instant interruption"


@dataclass(frozen=True)
class CapabilityPlan:
    capability: str
    arguments: Mapping[str, object]
    task_id: int
    generation: int
    backend: Backend
    execution_mode: ExecutionMode = ExecutionMode.ORDERED
    source: PlanSource = PlanSource.INTERNAL
    confirmed: bool = False
    # Reserved for later multi-step planning, not a second scheduler in Phase 2.
    dependencies: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.arguments, Mapping):
            raise CapabilityError("Arguments must be a mapping")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


def _http_url(value: str) -> bool:
    """No guessing schemes, credentials, shell targets, or browser script URLs."""
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


class CapabilityRegistry:
    """Definitions only. Availability means a registered backend, not host readiness."""

    def __init__(self):
        self._definitions: dict[str, Capability] = {}

    def register(self, capability: Capability):
        if not isinstance(capability, Capability) or not capability.name:
            raise CapabilityError("Invalid capability definition")
        if capability.name in self._definitions:
            raise CapabilityError("Duplicate capability registration")
        self._definitions[capability.name] = capability

    def lookup(self, name: str) -> Capability:
        if type(name) is not str or name not in self._definitions:
            raise CapabilityError("Unknown capability")
        return self._definitions[name]

    def available(self, name: str, backend: Backend | None = None) -> bool:
        if type(name) is not str or name not in self._definitions:
            return False
        return backend is None or (type(backend) is Backend
                                   and backend in self._definitions[name].backends)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def validate(self, plan: CapabilityPlan, *, task: TaskRecord,
                 generation: int, cancelled: bool = False) -> Capability:
        if type(plan) is not CapabilityPlan:
            raise CapabilityError("Expected a typed capability plan")
        definition = self.lookup(plan.capability)
        if (type(plan.task_id) is not int or plan.task_id <= 0
                or type(plan.generation) is not int or plan.generation < 0
                or type(generation) is not int or generation < 0
                or not isinstance(task, TaskRecord)):
            raise CapabilityError("Invalid task identity or generation")
        status = task.snapshot()
        if (type(status["id"]) is not int or status["id"] <= 0
                or type(status["generation"]) is not int or status["generation"] < 0):
            raise CapabilityError("Invalid issued task identity/generation")
        if (plan.task_id != status["id"] or plan.generation != status["generation"]
                or plan.generation != generation):
            raise CapabilityError("Mismatched or stale task identity/generation")
        if cancelled or status["status"] not in {TaskStatus.ACCEPTED.value, TaskStatus.RUNNING.value}:
            raise CapabilityError("Task is cancelled or already terminal")
        if type(plan.backend) is not Backend or plan.backend not in definition.backends:
            raise CapabilityError("Unsupported backend")
        if type(plan.execution_mode) is not ExecutionMode or plan.execution_mode != definition.execution_mode:
            raise CapabilityError("Unsupported execution mode")
        if type(plan.source) is not PlanSource:
            raise CapabilityError("Unsupported plan source")
        if type(plan.confirmed) is not bool:
            raise CapabilityError("Confirmation must be boolean")
        if definition.confirmation_required and not plan.confirmed:
            raise CapabilityError("Explicit caller confirmation required")
        if type(plan.dependencies) is not tuple or plan.dependencies:
            raise CapabilityError("Phase 2 supports single-step plans without dependencies")
        schema = {arg.name: arg for arg in definition.arguments}
        if any(type(key) is not str or key not in schema for key in plan.arguments):
            raise CapabilityError("Unknown argument")
        for name, spec in schema.items():
            if name not in plan.arguments and spec.required:
                raise CapabilityError("Missing required argument")
            value = plan.arguments.get(name, spec.default)
            if type(value) is not spec.value_type:
                raise CapabilityError("Invalid argument type")
            if isinstance(value, str) and not value.strip():
                raise CapabilityError("Empty argument")
            if spec.choices and value not in spec.choices:
                raise CapabilityError("Unsupported argument value")
        if plan.capability == "browser.open_site" and not _http_url(plan.arguments["url"]):
            raise CapabilityError("Expected an explicit HTTP(S) URL without credentials")
        if plan.capability == "browser.activate" and re.fullmatch(
                r"(?:(?:onto|to|over|on|at)\s+(?:the\s+)?)*(?:the\s+)?"
                r"(?:(?:(?:clickable|search|youtube)\s+)?(?:element|item|result|video|link|shot|short|shorts)\s+(?:number\s+)?)?"
                r"(?:\d+|first|second|third|fourth|fifth|one|two|three|four|five|1st|2nd|3rd|4th|5th)"
                r"(?:\s+(?:(?:clickable|search|youtube)\s+)?(?:element|item|result|video|link|shot|short|shorts))?",
                plan.arguments["target"].strip().lower()):
            raise CapabilityError("Activation requires a named element, not an ordinal")
        return definition


def default_registry() -> CapabilityRegistry:
    """Fresh deterministic catalog. No agent backend, registration plugins, or probes."""
    registry = CapabilityRegistry()
    for definition in (
        Capability("browser.open_site", "Open an explicit HTTP(S) URL", (Argument("url"),),
                   (Backend.PLAYWRIGHT,), Risk.MEDIUM, Verification.BROWSER_READINESS,
                   "Existing observed browser URL/title/site state"),
        Capability("browser.search", "Search a supported engine with an explicit query",
                   (Argument("query"), Argument("engine", required=False, default="google",
                                                choices=("google", "youtube", "github"))),
                   (Backend.PLAYWRIGHT,), Risk.MEDIUM, Verification.BROWSER_READINESS,
                   "Existing browser/search state; Google challenge fallback remains unchanged"),
        Capability("browser.scroll", "Scroll the active controlled browser, never the desktop",
                   (Argument("direction", choices=("up", "down")),), (Backend.PLAYWRIGHT,),
                   Risk.LOW, Verification.NONE, "Existing observation refresh",
                   requires_active_browser=True),
        Capability("browser.activate", "Click a named visible page element (not tab/window activation)",
                   (Argument("target"),), (Backend.PLAYWRIGHT,), Risk.HIGH,
                   Verification.ELEMENT_AND_READINESS, "Existing click observation and browser state",
                   confirmation_required=True, requires_active_browser=True),
        Capability("desktop.open_app", "Launch a supported tracked native application",
                   (Argument("app", choices=("notepad", "calculator")),), (Backend.PLATFORM,),
                   Risk.MEDIUM, Verification.FOREGROUND, "Existing foreground app/window state"),
        Capability("desktop.switch_window", "Focus an existing window matching the given name",
                   (Argument("target"),), (Backend.PLATFORM,), Risk.MEDIUM,
                   Verification.FOREGROUND, "Existing foreground app/window state"),
        Capability("keyboard.type", "Type using existing foreground-aware DOM/OS routing",
                   (Argument("text"),), (Backend.FOREGROUND_KEYBOARD,), Risk.HIGH,
                   Verification.NONE, "Existing command/foreground observations",
                   confirmation_required=True),
        Capability("keyboard.press", "Press a supported single key in the foreground application",
                   (Argument("key", choices=("enter", "space", "backspace", "esc", "tab",
                                             "delete", "up", "down", "left", "right")),),
                   (Backend.FOREGROUND_KEYBOARD,), Risk.HIGH, Verification.NONE,
                   "Existing command/foreground observations", confirmation_required=True),
    ):
        registry.register(definition)
    return registry
