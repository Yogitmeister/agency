"""Launch-time JSON command policy for supervised terminals."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

MAX_COMMAND = 2_000
DEFAULT_POLICY_RESOURCE = "command-policy.json"
_SLASH_HEAD = re.compile(r"^/[A-Za-z0-9:_-]+$")
_POLICY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_RULE = re.compile(r"^/(?:\*|[A-Za-z0-9:_-]+\*?)$")


class PolicyError(ValueError):
    """The command or policy cannot cross the terminal boundary."""


def normalize_command(command: str) -> str:
    if any(unicodedata.category(character).startswith("C") for character in command):
        raise PolicyError("commands must be one line and contain no control characters")
    command = command.strip()
    if not command:
        raise PolicyError("command is empty")
    if len(command) > MAX_COMMAND:
        raise PolicyError(f"command exceeds {MAX_COMMAND} characters")
    head = command.split(maxsplit=1)[0]
    if not _SLASH_HEAD.fullmatch(head):
        raise PolicyError("only slash commands are accepted; arbitrary prompt text is refused")
    return command


def _read_policy_document(policy_file: str | Path | None) -> tuple[dict[str, Any], str]:
    if policy_file:
        path = Path(policy_file).expanduser().resolve()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyError(f"cannot read policy file {path}: {exc}") from exc
        source = str(path)
    else:
        try:
            raw = (
                resources.files("agency_pty")
                .joinpath(DEFAULT_POLICY_RESOURCE)
                .read_text(encoding="utf-8")
            )
        except OSError as exc:
            raise PolicyError(f"cannot read bundled {DEFAULT_POLICY_RESOURCE}: {exc}") from exc
        source = f"bundled:{DEFAULT_POLICY_RESOURCE}"
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid JSON in policy source {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise PolicyError(f"policy source {source} must contain a JSON object")
    if document.get("schema") != 1:
        raise PolicyError(f"policy source {source} must declare schema 1")
    if not isinstance(document.get("policies"), dict):
        raise PolicyError(f"policy source {source} must contain a policies object")
    return document, source


def _validate_rules(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyError(f"{label} must be a JSON array of command patterns")
    if len(value) != len(set(value)):
        raise PolicyError(f"{label} contains duplicate command patterns")
    for rule in value:
        if not _RULE.fullmatch(rule):
            raise PolicyError(
                f"invalid command pattern {rule!r} in {label}; use /command, /command*, or /*"
            )
    return tuple(value)


def _matches(rule: str, command: str) -> bool:
    if rule == "/*":
        return True
    if rule.endswith("*"):
        head = rule[:-1]
        return command == head or command.startswith(head + " ")
    return command == rule


@dataclass(frozen=True)
class CommandPolicy:
    name: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]
    source: str

    def accepts(self, command: str) -> tuple[bool, str]:
        try:
            normalized = normalize_command(command)
        except PolicyError as exc:
            return False, str(exc)
        for rule in self.deny:
            if _matches(rule, normalized):
                return False, f"refused by deny rule {rule} in {self.name} policy"
        for rule in self.allow:
            if _matches(rule, normalized):
                return True, f"accepted by allow rule {rule} in {self.name} policy"
        allowed = ", ".join(self.allow) if self.allow else "nothing"
        return False, f"{self.name} policy allows only: {allowed}"


def parse_policy(value: str, policy_file: str | Path | None = None) -> CommandPolicy:
    if not _POLICY_NAME.fullmatch(value):
        raise PolicyError("policy name must contain only letters, digits, dots, hyphens, or underscores")
    document, source = _read_policy_document(policy_file)
    profiles = document["policies"]
    profile = profiles.get(value)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(str(name) for name in profiles)) or "none"
        raise PolicyError(f"unknown policy {value!r} in {source}; available: {available}")
    allow = _validate_rules(profile.get("allow"), label=f"{value}.allow")
    deny = _validate_rules(profile.get("deny"), label=f"{value}.deny")
    return CommandPolicy(name=value, allow=allow, deny=deny, source=source)
