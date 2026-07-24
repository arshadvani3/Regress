from pathlib import Path

import pytest

from regress.evalgen.generate import EvalAssertion, EvalCase, GeneratedEval
from regress.evalgen.load import EvalFileError, load_eval_file
from regress.evalgen.write import write_eval


def _sample_eval(**overrides: object) -> GeneratedEval:
    defaults: dict[str, object] = {
        "issue_id": "i1",
        "issue_title": "Refuses refund requests",
        "name": "refuses-refund-requests",
        "assertion": EvalAssertion(type="judge", rubric="Should address the refund."),
        "cases": [EvalCase(trace_id="t1", input="q", bad_output="a")],
    }
    defaults.update(overrides)
    return GeneratedEval(**defaults)


def test_write_eval_creates_yaml_and_pytest_files(tmp_path: Path) -> None:
    yaml_path, pytest_path = write_eval(_sample_eval(), tmp_path)

    assert yaml_path.exists()
    assert pytest_path.exists()
    assert yaml_path.name == "refuses-refund-requests.yaml"
    assert pytest_path.name == "test_refuses_refund_requests.py"


def test_write_eval_creates_directory_if_missing(tmp_path: Path) -> None:
    directory = tmp_path / "nested" / "evals"

    yaml_path, _ = write_eval(_sample_eval(), directory)

    assert yaml_path.exists()


def test_write_eval_overwrites_existing_files(tmp_path: Path) -> None:
    write_eval(_sample_eval(), tmp_path)
    updated = _sample_eval(
        cases=[EvalCase(trace_id="t2", input="new input", bad_output="new output")]
    )

    yaml_path, _ = write_eval(updated, tmp_path)
    loaded = load_eval_file(yaml_path)

    assert len(loaded.cases) == 1
    assert loaded.cases[0].trace_id == "t2"


def test_pytest_module_references_the_yaml_file(tmp_path: Path) -> None:
    yaml_path, pytest_path = write_eval(_sample_eval(), tmp_path)

    content = pytest_path.read_text()

    assert yaml_path.name in content
    assert "run_eval_case" in content


def test_write_then_load_round_trips_judge_assertion(tmp_path: Path) -> None:
    eval_ = _sample_eval(
        assertion=EvalAssertion(type="judge", rubric="Answers the question directly.")
    )

    yaml_path, _ = write_eval(eval_, tmp_path)
    loaded = load_eval_file(yaml_path)

    assert loaded.issue_id == "i1"
    assert loaded.assertion.type == "judge"
    assert loaded.assertion.rubric == "Answers the question directly."
    assert loaded.assertion.check is None


def test_write_then_load_round_trips_deterministic_assertion(tmp_path: Path) -> None:
    eval_ = _sample_eval(assertion=EvalAssertion(type="deterministic", check="not_refusal"))

    yaml_path, _ = write_eval(eval_, tmp_path)
    loaded = load_eval_file(yaml_path)

    assert loaded.assertion.type == "deterministic"
    assert loaded.assertion.check == "not_refusal"


def test_write_then_load_round_trips_multiple_cases(tmp_path: Path) -> None:
    eval_ = _sample_eval(
        cases=[
            EvalCase(trace_id="t1", input="q1", bad_output="a1"),
            EvalCase(trace_id="t2", input="q2", bad_output="a2"),
        ]
    )

    yaml_path, _ = write_eval(eval_, tmp_path)
    loaded = load_eval_file(yaml_path)

    assert len(loaded.cases) == 2
    assert [c.trace_id for c in loaded.cases] == ["t1", "t2"]


def test_load_eval_file_raises_on_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("issue_id: i1\nname: x\n")

    with pytest.raises(EvalFileError):
        load_eval_file(path)


def test_load_eval_file_raises_on_non_mapping_top_level(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("- just\n- a\n- list\n")

    with pytest.raises(EvalFileError):
        load_eval_file(path)


def test_load_eval_file_raises_on_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("cases: [\n  unclosed")

    with pytest.raises(EvalFileError):
        load_eval_file(path)


def test_eval_yaml_omits_empty_optional_assertion_fields(tmp_path: Path) -> None:
    eval_ = _sample_eval(assertion=EvalAssertion(type="deterministic", check=None))

    yaml_path, _ = write_eval(eval_, tmp_path)
    raw_text = yaml_path.read_text()

    assert "check:" not in raw_text
    assert "rubric:" not in raw_text
