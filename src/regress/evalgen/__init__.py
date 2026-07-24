"""EvalGen: per-issue eval generation, replay/live execution, and the CI gate.

Per CLAUDE.md: each issue becomes an eval file — representative inputs
(sanitized from real traces), an assertion type chosen automatically
(deterministic if the failure is structural, judge+rubric if semantic), and
metadata linking back to the issue. Output is human-editable YAML plus a
generated pytest module; `regress run` executes evals against recorded
traces (replay) or a live endpoint.
"""

from __future__ import annotations
