"""Read-only JSON API backing the dashboard (Phase 7).

Everything the CLI can already do (ingest, score, cluster, evalgen,
calibrate) is unchanged by this package — these routes only read the same
tables to render the trace explorer, issue kanban, and calibration view.
No route here writes, except `POST /api/labels`, which is the dashboard's
equivalent of `regress calibrate --label`.
"""
