"""Optional `regress.yaml` config: declare which checks run against which spans.

Per CLAUDE.md's zero-config-default-path principle, this file is entirely
optional — `regress score` with no config runs only `not_refusal` (the one
check with no required parameters) against every span. Everything else
needs a rubric/schema/threshold the tool can't guess, so it's opt-in here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("regress.yaml")

_DETERMINISTIC_CHECKS = {
    "json_schema_valid",
    "regex_match",
    "exact_match",
    "tool_call_args_valid",
    "latency_under",
    "cost_under",
    "not_refusal",
}


class ConfigError(ValueError):
    """Raised when `regress.yaml` is malformed."""


@dataclass
class CheckConfig:
    """One configured check: which function to run, with what arguments."""

    check: str
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    tier: str = "deterministic"  # "deterministic" | "judge"


@dataclass
class RegressConfig:
    checks: list[CheckConfig] = field(default_factory=list)
    judge_model: str = "gpt-4o-mini"
    judge_base_url: str = "https://api.openai.com/v1"


def load_config(path: Path | None = None) -> RegressConfig:
    """Load `regress.yaml`, or return the zero-config default if absent."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return RegressConfig(checks=[CheckConfig(check="not_refusal", name="not_refusal")])

    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping at the top level")

    judge_section = raw.get("judge", {}) or {}
    if not isinstance(judge_section, dict):
        raise ConfigError("'judge' must be a mapping")

    checks = []
    for entry in raw.get("checks", []) or []:
        if not isinstance(entry, dict) or "check" not in entry:
            raise ConfigError(
                f"each entry under 'checks' must be a mapping with a 'check' key: {entry!r}"
            )
        check_name = str(entry["check"])
        tier = "judge" if check_name == "judge_rubric" else "deterministic"
        if tier == "deterministic" and check_name not in _DETERMINISTIC_CHECKS:
            raise ConfigError(f"unknown deterministic check: {check_name!r}")
        params = {k: v for k, v in entry.items() if k not in ("check", "name")}
        check_label = str(entry["name"]) if "name" in entry else check_name
        checks.append(
            CheckConfig(check=check_name, name=check_label, params=params, tier=tier)
        )

    return RegressConfig(
        checks=checks,
        judge_model=judge_section.get("model", "gpt-4o-mini"),
        judge_base_url=judge_section.get("base_url", "https://api.openai.com/v1"),
    )
