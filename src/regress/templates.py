"""The `regress init` scaffold: a commented, ready-to-run `regress.yaml`.

Deterministic checks that need no thought are uncommented; judge rubrics
are a menu of named, uncomment-ready options -- "delete what you don't
want" beats authoring a rubric from scratch. Rubric text is pulled from
`regress.scoring.rubrics` so this can never drift from the zero-config
default (`response_quality`) or from each other.
"""

from __future__ import annotations

from regress.scoring.judge import DEFAULT_BASE_URL, DEFAULT_MODEL
from regress.scoring.rubrics import NAMED_RUBRICS

_RUBRIC_ORDER = [
    "response_quality",
    "answers_the_question",
    "no_hallucination",
    "stays_on_topic",
    "not_toxic",
    "follows_format",
]


def render_scaffold() -> str:
    """Render the `regress init` scaffold as a `regress.yaml` string."""
    rubric_lines = []
    for name in _RUBRIC_ORDER:
        rubric_lines.append("  # - check: judge_rubric")
        rubric_lines.append(f"  #   name: {name}")
        rubric_lines.append(f'  #   rubric: "{NAMED_RUBRICS[name]}"')
        rubric_lines.append("")
    rubric_menu = "\n".join(rubric_lines).rstrip() + "\n"

    return f"""\
# Regress scoring config. Optional -- with no file, `regress score` runs
# `not_refusal` for free, plus a built-in quality check if an API key is
# set. This file lets you customize and add more.
#
# Docs: docs/usage.md#2-score

judge:
  model: {DEFAULT_MODEL}          # any OpenAI-compatible endpoint, incl. Ollama
  base_url: {DEFAULT_BASE_URL}

checks:
  # Deterministic checks -- free, exact, no LLM call, no domain knowledge
  # needed. Uncommented to run out of the box.
  - check: not_refusal
  - check: latency_under
    name: fast_response
    max_ms: 2000

  # Needs a per-1k-token price for your model to be meaningful -- uncomment
  # and fill in cost_per_1k_tokens once you know it.
  # - check: cost_under
  #   name: cheap_response
  #   max_cost: 0.01
  #   cost_per_1k_tokens: 0.15

  # Judge rubrics -- pick the ones that fit your app, or write your own.
  # Uncomment to enable (each is one `judge_rubric` check).
{rubric_menu}\
"""
