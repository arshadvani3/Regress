"""Optional `regress.yaml` config: declare which checks run against which spans.

Per CLAUDE.md's zero-config-default-path principle, this file is entirely
optional. With no config, `regress score` always runs `not_refusal` (free,
no LLM involved). When an API key is available in the environment, it also
runs a built-in `response_quality` judge check — otherwise a first-time user
whose app doesn't literally refuse sees "everything passed" and never finds
the tool's actual value. No key, no config file needed for that -- and no
judge check runs, since that would mean a paid call the user never asked for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from regress.scoring.rubrics import RESPONSE_QUALITY

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
    # True only for the zero-config (no regress.yaml) default when an API key
    # was found and the built-in response_quality judge check was included --
    # lets callers (the CLI) decide whether to print a cost notice, without
    # re-implementing the "is a key available" check themselves.
    used_zero_config_judge: bool = False


def _has_judge_api_key() -> bool:
    return bool(os.environ.get("REGRESS_JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def load_config(path: Path | None = None) -> RegressConfig:
    """Load `regress.yaml`, or return the zero-config default if absent."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        checks = [CheckConfig(check="not_refusal", name="not_refusal")]
        has_key = _has_judge_api_key()
        if has_key:
            checks.append(
                CheckConfig(
                    check="judge_rubric",
                    name="response_quality",
                    params={"rubric": RESPONSE_QUALITY},
                    tier="judge",
                )
            )
        return RegressConfig(checks=checks, used_zero_config_judge=has_key)

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
