"""Calibrator: hand-label a sample of judge verdicts, compute Cohen's kappa
judge-vs-human, and suggest a better score threshold — per CLAUDE.md.

Only judge-sourced Score rows are calibration candidates; deterministic
checks have no ambiguity to calibrate against a human. This module is
small on purpose, per CLAUDE.md's note that it's the resume differentiator
precisely because it's a complete, tight loop rather than a big surface.
"""

from __future__ import annotations
