from pathlib import Path

from click.testing import CliRunner

from regress.cli import main
from regress.config import load_config


def test_init_writes_valid_regress_yaml(tmp_path: Path) -> None:
    target = tmp_path / "regress.yaml"
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--path", str(target)])

    assert result.exit_code == 0
    assert target.exists()
    assert f"Wrote {target}" in result.output


def test_init_scaffold_parses_with_load_config(tmp_path: Path) -> None:
    target = tmp_path / "regress.yaml"
    runner = CliRunner()

    runner.invoke(main, ["init", "--path", str(target)])
    config = load_config(target)

    check_names = [c.check for c in config.checks]
    assert "not_refusal" in check_names
    assert "latency_under" in check_names
    # Judge rubrics ship commented out -- none should be active by default.
    assert all(c.tier == "deterministic" for c in config.checks)


def test_init_scaffold_contains_commented_rubric_menu(tmp_path: Path) -> None:
    target = tmp_path / "regress.yaml"
    runner = CliRunner()

    runner.invoke(main, ["init", "--path", str(target)])
    content = target.read_text()

    for rubric_name in [
        "response_quality",
        "answers_the_question",
        "no_hallucination",
        "stays_on_topic",
        "not_toxic",
        "follows_format",
    ]:
        assert f"#   name: {rubric_name}" in content


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "regress.yaml"
    target.write_text("checks: []\n")
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--path", str(target)])

    assert result.exit_code != 0
    assert "already exists" in str(result.output)
    assert target.read_text() == "checks: []\n"


def test_init_force_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "regress.yaml"
    target.write_text("checks: []\n")
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--path", str(target), "--force"])

    assert result.exit_code == 0
    assert "judge:" in target.read_text()


def test_init_defaults_to_regress_yaml_in_cwd(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["init"])

        assert result.exit_code == 0
        assert Path("regress.yaml").exists()
