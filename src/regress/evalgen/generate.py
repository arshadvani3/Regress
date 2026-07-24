"""Generate an eval file for an Issue: representative sanitized inputs plus
an assertion type chosen automatically from what actually caught the
failure — deterministic if a deterministic check failed, judge+rubric if a
judge check failed, per CLAUDE.md.

`Score` rows only persist the *result* of a check, not the config it ran
with, so a deterministic check that needs parameters we don't have on hand
(latency_under's threshold, json_schema_valid's schema, ...) can't be
regenerated exactly. For those, EvalGen falls back to pinning each case's
own observed failing output as a per-case exact_match regression pin —
"this exact bad output must never reproduce" is itself a normal
regression-test pattern, not a degraded one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from regress.clustering import final_output, last_user_message
from regress.evalgen.sanitize import sanitize
from regress.models import Issue, Score, Trace

_MAX_CASES = 5

# Checks whose Score alone is enough to regenerate the exact same assertion
# (no extra parameters needed at call time), applied uniformly to every case.
_PARAMLESS_DETERMINISTIC_CHECKS = {"not_refusal"}


def _slugify(text: str, *, disambiguator: str) -> str:
    """Slug from `text`, with a short suffix from `disambiguator` so two
    issues with the same (or similarly-titled) title never collide on the
    same eval filename and silently overwrite each other.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "issue"
    return f"{slug}-{disambiguator[:8]}"


@dataclass
class EvalCase:
    trace_id: str
    input: str
    bad_output: str


@dataclass
class EvalAssertion:
    """type == "deterministic": either `check` (a paramless check name,
    applied to every case) or, if `check` is None, each case's own
    `bad_output` is used as an exact_match pin. type == "judge": `rubric`
    is applied to every case.
    """

    type: str  # "deterministic" | "judge"
    check: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    rubric: str | None = None


@dataclass
class GeneratedEval:
    issue_id: str
    issue_title: str
    name: str
    assertion: EvalAssertion
    cases: list[EvalCase]


def _failing_scores(trace: Trace) -> list[Score]:
    scores = [s for s in trace.scores if s.passed is False]
    for span in trace.spans:
        scores.extend(s for s in span.scores if s.passed is False)
    return scores


def _choose_assertion(traces: list[Trace]) -> EvalAssertion:
    """Pick the assertion type from the failing scores across an issue's traces.

    Judge failures take priority when both tiers are present — a semantic
    rubric a human already wrote captures intent better than a structural
    fallback. Among deterministic checks, only a paramless check name
    (currently just not_refusal) can be regenerated exactly; anything else
    falls back to per-case output pinning.
    """
    judge_scores = []
    deterministic_counts: dict[str, int] = {}

    for trace in traces:
        for score in _failing_scores(trace):
            if score.source == "judge" and score.rubric:
                judge_scores.append(score)
            elif score.source == "deterministic":
                deterministic_counts[score.name] = deterministic_counts.get(score.name, 0) + 1

    if judge_scores:
        return EvalAssertion(type="judge", rubric=judge_scores[0].rubric)

    if deterministic_counts:
        most_common = max(deterministic_counts, key=lambda name: deterministic_counts[name])
        if most_common in _PARAMLESS_DETERMINISTIC_CHECKS:
            return EvalAssertion(type="deterministic", check=most_common)

    return EvalAssertion(type="deterministic", check=None)


def generate_eval(issue: Issue, traces: list[Trace]) -> GeneratedEval:
    """Build a GeneratedEval for `issue` from its member `traces`.

    `traces` is passed in rather than derived from `issue.trace_links`
    directly so callers control ordering/filtering (e.g. most-recent-first,
    capped to `_MAX_CASES`) without this function needing session access.
    """
    assertion = _choose_assertion(traces)

    cases = []
    for trace in traces[:_MAX_CASES]:
        input_text = sanitize(last_user_message(trace))
        output_text = sanitize(final_output(trace))
        if not input_text and not output_text:
            continue
        cases.append(EvalCase(trace_id=trace.id, input=input_text, bad_output=output_text))

    return GeneratedEval(
        issue_id=issue.id,
        issue_title=issue.title,
        name=_slugify(issue.title, disambiguator=issue.id),
        assertion=assertion,
        cases=cases,
    )
