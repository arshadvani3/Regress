from pathlib import Path

import pytest

from regress.config import ConfigError, load_config


def test_load_config_returns_default_when_file_missing_and_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REGRESS_JUDGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = load_config(tmp_path / "does_not_exist.yaml")

    assert len(config.checks) == 1
    assert config.checks[0].check == "not_refusal"
    assert config.checks[0].tier == "deterministic"
    assert config.used_zero_config_judge is False


def test_load_config_adds_response_quality_judge_when_key_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REGRESS_JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = load_config(tmp_path / "does_not_exist.yaml")

    assert len(config.checks) == 2
    assert config.checks[0].check == "not_refusal"
    judge_check = config.checks[1]
    assert judge_check.check == "judge_rubric"
    assert judge_check.name == "response_quality"
    assert judge_check.tier == "judge"
    assert "rubric" in judge_check.params
    assert config.used_zero_config_judge is True


def test_load_config_adds_response_quality_judge_with_regress_judge_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REGRESS_JUDGE_API_KEY", "sk-judge-only")

    config = load_config(tmp_path / "does_not_exist.yaml")

    assert len(config.checks) == 2
    assert config.used_zero_config_judge is True


def test_load_config_with_real_regress_yaml_never_sets_zero_config_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    path = tmp_path / "regress.yaml"
    path.write_text("checks:\n  - check: not_refusal\n")

    config = load_config(path)

    assert config.used_zero_config_judge is False


def test_load_config_parses_deterministic_checks(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text(
        """
checks:
  - check: not_refusal
  - check: latency_under
    name: fast_response
    max_ms: 2000
"""
    )

    config = load_config(path)

    assert len(config.checks) == 2
    assert config.checks[0].name == "not_refusal"
    fast = config.checks[1]
    assert fast.check == "latency_under"
    assert fast.name == "fast_response"
    assert fast.params == {"max_ms": 2000}
    assert fast.tier == "deterministic"


def test_load_config_parses_judge_check(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text(
        """
judge:
  model: gpt-4o-mini
  base_url: http://localhost:11434/v1

checks:
  - check: judge_rubric
    name: helpfulness
    rubric: "Does the response answer the question?"
"""
    )

    config = load_config(path)

    assert config.judge_model == "gpt-4o-mini"
    assert config.judge_base_url == "http://localhost:11434/v1"
    assert len(config.checks) == 1
    assert config.checks[0].tier == "judge"
    assert config.checks[0].params["rubric"] == "Does the response answer the question?"


def test_load_config_rejects_unknown_deterministic_check(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text("checks:\n  - check: not_a_real_check\n")

    with pytest.raises(ConfigError, match="unknown deterministic check"):
        load_config(path)


def test_load_config_rejects_non_mapping_top_level(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text("- just\n- a\n- list\n")

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_rejects_check_entry_without_check_key(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text("checks:\n  - name: missing_check_key\n")

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text("checks: [\n  unclosed")

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_empty_file_returns_no_checks(tmp_path: Path) -> None:
    path = tmp_path / "regress.yaml"
    path.write_text("")

    config = load_config(path)

    assert config.checks == []
