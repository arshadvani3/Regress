"""Regress CLI entrypoint.

`regress up` starts the collector + API + dashboard as a single process,
per the instant-developer-pickup design north star in CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

import click
from sqlalchemy import select

from regress import __version__


@click.group()
@click.version_option(version=__version__, prog_name="regress")
def main() -> None:
    """Regress: your agent's production failures become its regression suite."""


@main.command()
@click.option(
    "--path",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Where to write the scaffold. Defaults to ./regress.yaml.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing regress.yaml.",
)
def init(config_path: Path | None, force: bool) -> None:
    """Scaffold a starter regress.yaml with a menu of ready-to-use rubrics."""
    from regress.config import DEFAULT_CONFIG_PATH
    from regress.templates import render_scaffold

    target = config_path or DEFAULT_CONFIG_PATH
    if target.exists() and not force:
        raise click.ClickException(f"{target} already exists. Use --force to overwrite.")

    target.write_text(render_scaffold())
    click.echo(f"Wrote {target}")
    click.echo(
        "Deterministic checks (not_refusal, latency_under) are enabled. "
        "Uncomment a judge rubric to add semantic checks, then run: regress score"
    )


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8990, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable autoreload (development only).")
def up(host: str, port: int, reload: bool) -> None:
    """Start the Regress collector, API, and dashboard as one process."""
    import uvicorn

    click.echo(f"Starting Regress on http://{host}:{port}")
    uvicorn.run("regress.app:app", host=host, port=port, reload=reload)


@main.command()
@click.option("--limit", default=20, show_default=True, help="Maximum number of traces to list.")
def traces(limit: int) -> None:
    """List ingested traces, most recent first."""
    from regress.db import get_session, init_db
    from regress.models import Trace

    init_db()
    with get_session() as session:
        rows = session.execute(
            select(Trace).order_by(Trace.ingested_at.desc()).limit(limit)
        ).scalars().all()

        if not rows:
            click.echo("No traces ingested yet.")
            return

        header = f"{'TRACE ID':<34} {'APP':<16} {'STATUS':<8} {'LATENCY (ms)':<14} {'STARTED AT'}"
        click.echo(header)
        for row in rows:
            latency = f"{row.latency_ms:.1f}" if row.latency_ms is not None else "-"
            started = row.started_at.isoformat() if row.started_at else "-"
            click.echo(
                f"{row.id:<34} {(row.app or '-'):<16} {row.status:<8} {latency:<14} {started}"
            )


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to regress.yaml. Defaults to ./regress.yaml if present, otherwise runs "
    "only the zero-config not_refusal check.",
)
@click.option(
    "--rescore",
    is_flag=True,
    default=False,
    help="Re-run checks even on spans that already have scores.",
)
def score(config_path: Path | None, rescore: bool) -> None:
    """Run deterministic + judge checks against ingested spans."""
    from regress.config import ConfigError, load_config
    from regress.db import get_session, init_db
    from regress.models import Score, Span
    from regress.scoring.run import score_spans

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if not config.checks:
        click.echo("No checks configured. Add a regress.yaml or use the default not_refusal check.")
        return

    if config.used_zero_config_judge:
        click.echo(
            f"No regress.yaml found — running the built-in quality check "
            f"(LLM judge, {config.judge_model}, ~1 API call/span). "
            f"Add a regress.yaml to customize or silence."
        )

    init_db()
    with get_session() as session:
        query = select(Span)
        if not rescore:
            already_scored = select(Score.span_id).where(Score.span_id.is_not(None))
            query = query.where(~Span.id.in_(already_scored))
        spans = session.execute(query).scalars().all()

        if not spans:
            click.echo("No spans to score.")
            return

        errors: list[str] = []
        rows = score_spans(
            session,
            list(spans),
            config,
            on_error=lambda span, check, exc: errors.append(f"{span.id}/{check.name}: {exc}"),
        )
        session.commit()

        click.echo(
            f"Scored {len(spans)} span(s) against {len(config.checks)} check(s): "
            f"{len(rows)} score(s)."
        )
        for error in errors:
            click.echo(f"  skipped: {error}")


@main.command()
@click.option(
    "--min-cluster-size",
    default=3,
    show_default=True,
    help="Minimum number of similar failing traces to form a cluster.",
)
def cluster(min_cluster_size: int) -> None:
    """Embed scored-bad traces, cluster them, and update Issues.

    Requires the 'cluster' extra: pip install 'regress-ai[cluster]'
    """
    from regress.clustering.run import run_clustering
    from regress.db import get_session, init_db

    init_db()
    with get_session() as session:
        try:
            result = run_clustering(session, min_cluster_size=min_cluster_size)
        except ImportError as exc:
            raise click.ClickException(str(exc)) from exc
        session.commit()

        if result.traces_considered < min_cluster_size:
            click.echo(
                f"Only {result.traces_considered} scored-bad trace(s) found "
                f"(need at least {min_cluster_size}). Nothing to cluster yet."
            )
            return

        click.echo(
            f"Considered {result.traces_considered} scored-bad trace(s), "
            f"found {result.clusters_found} cluster(s)."
        )
        click.echo(f"  new issues: {len(result.lifecycle.new_issues)}")
        click.echo(f"  updated issues: {len(result.lifecycle.updated_issues)}")
        if result.lifecycle.regressed_issues:
            click.echo(f"  REGRESSED issues: {len(result.lifecycle.regressed_issues)}")
            for issue in result.lifecycle.regressed_issues:
                click.echo(f"    - {issue.title!r} ({issue.id}) is failing again")
        for error in result.titling_errors:
            click.echo(f"  titling failed: {error}")


@main.command()
@click.option(
    "--dir",
    "evals_dir",
    type=click.Path(path_type=Path),
    default=Path("evals"),
    show_default=True,
    help="Directory to write generated eval YAML + pytest files into.",
)
@click.option(
    "--state",
    "issue_state",
    default="active",
    show_default=True,
    help="Only generate evals for issues in this lifecycle state ('all' for every state).",
)
def evalgen(evals_dir: Path, issue_state: str) -> None:
    """Generate eval files for issues: representative sanitized inputs plus
    an assertion type chosen from what actually caught the failure.
    """
    from regress.db import get_session, init_db
    from regress.evalgen.orchestrate import generate_evals_for_issues
    from regress.models import Issue

    init_db()
    with get_session() as session:
        query = select(Issue)
        if issue_state != "all":
            query = query.where(Issue.state == issue_state)
        issues = list(session.execute(query).scalars().all())

        if not issues:
            click.echo(f"No issues in state {issue_state!r}. Run `regress cluster` first.")
            return

        outcomes = generate_evals_for_issues(session, issues, directory=evals_dir)
        session.commit()

        if not outcomes:
            click.echo("No evals generated — issues had no usable trace content.")
            return

        click.echo(f"Generated {len(outcomes)} eval(s) in {evals_dir}/:")
        for outcome in outcomes:
            click.echo(
                f"  {outcome.yaml_path.name} — {outcome.issue_title!r} "
                f"({outcome.case_count} case(s))"
            )


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to regress.yaml for the scoring step. Defaults to ./regress.yaml if "
    "present, otherwise the zero-config default (see `regress score --help`).",
)
@click.option(
    "--min-cluster-size",
    default=3,
    show_default=True,
    help="Minimum number of similar failing traces to form a cluster.",
)
@click.option(
    "--dir",
    "evals_dir",
    type=click.Path(path_type=Path),
    default=Path("evals"),
    show_default=True,
    help="Directory to write generated eval YAML + pytest files into.",
)
def analyze(config_path: Path | None, min_cluster_size: int, evals_dir: Path) -> None:
    """Run score, cluster, and evalgen in one step: traces in, evals out.

    Equivalent to running `regress score`, `regress cluster`, and
    `regress evalgen` in sequence -- each step still works standalone;
    this just collapses the common path into one command.
    """
    from regress.clustering.run import run_clustering
    from regress.config import ConfigError, load_config
    from regress.db import get_session, init_db
    from regress.evalgen.orchestrate import generate_evals_for_issues
    from regress.models import Issue, Score, Span
    from regress.scoring.run import score_spans

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if not config.checks:
        click.echo("No checks configured. Add a regress.yaml or use the default not_refusal check.")
        return

    if config.used_zero_config_judge:
        click.echo(
            f"No regress.yaml found — running the built-in quality check "
            f"(LLM judge, {config.judge_model}, ~1 API call/span). "
            f"Add a regress.yaml to customize or silence."
        )

    init_db()
    with get_session() as session:
        already_scored = select(Score.span_id).where(Score.span_id.is_not(None))
        spans = session.execute(select(Span).where(~Span.id.in_(already_scored))).scalars().all()

        scored_count = 0
        failed_count = 0
        if spans:
            errors: list[str] = []
            rows = score_spans(
                session,
                list(spans),
                config,
                on_error=lambda span, check, exc: errors.append(f"{span.id}/{check.name}: {exc}"),
            )
            session.commit()
            scored_count = len(spans)
            failed_count = sum(1 for row in rows if row.passed is False)
            click.echo(
                f"Scored {scored_count} span(s) against {len(config.checks)} check(s): "
                f"{len(rows)} score(s), {failed_count} failing."
            )
            for error in errors:
                click.echo(f"  skipped: {error}")
        else:
            click.echo("Scored 0 span(s) (nothing new to score).")

        try:
            cluster_result = run_clustering(session, min_cluster_size=min_cluster_size)
        except ImportError as exc:
            raise click.ClickException(str(exc)) from exc
        session.commit()

        if cluster_result.traces_considered < min_cluster_size:
            click.echo(
                f"Clustered: only {cluster_result.traces_considered} scored-bad trace(s) "
                f"found (need at least {min_cluster_size}). Nothing to cluster yet."
            )
        else:
            click.echo(
                f"Clustered {cluster_result.traces_considered} scored-bad trace(s) into "
                f"{cluster_result.clusters_found} cluster(s): "
                f"{len(cluster_result.lifecycle.new_issues)} new, "
                f"{len(cluster_result.lifecycle.updated_issues)} updated, "
                f"{len(cluster_result.lifecycle.regressed_issues)} regressed."
            )
            for issue in cluster_result.lifecycle.regressed_issues:
                click.echo(f"  REGRESSED: {issue.title!r} ({issue.id}) is failing again")
            for error in cluster_result.titling_errors:
                click.echo(f"  titling failed: {error}")

        issues = list(
            session.execute(select(Issue).where(Issue.state == "active")).scalars().all()
        )
        if not issues:
            click.echo("Evals: no active issues to generate from.")
            return

        outcomes = generate_evals_for_issues(session, issues, directory=evals_dir)
        session.commit()

        if not outcomes:
            click.echo("Evals: no evals generated — issues had no usable trace content.")
            return

        click.echo(f"Generated {len(outcomes)} eval(s) in {evals_dir}/:")
        for outcome in outcomes:
            click.echo(
                f"  {outcome.yaml_path.name} — {outcome.issue_title!r} "
                f"({outcome.case_count} case(s))"
            )


@main.command(name="run")
@click.argument("evals_dir", type=click.Path(path_type=Path), default=Path("evals"))
@click.option(
    "--against",
    default="traces",
    show_default=True,
    help="'traces' to replay recorded case data, or a URL to POST each case's "
    "input to and score the live response.",
)
@click.option(
    "--gate",
    is_flag=True,
    default=False,
    help="Exit nonzero if the pass rate dropped significantly vs. the last run "
    "(two-proportion z-test, not a raw diff). Updates the baseline on success.",
)
@click.option("--alpha", default=0.05, show_default=True, help="Significance threshold for --gate.")
def run(evals_dir: Path, against: str, gate: bool, alpha: float) -> None:
    """Run every eval in EVALS_DIR and report pass/fail."""
    from regress.evalgen.gate import two_proportion_z_test
    from regress.evalgen.suite import load_baseline, run_suite, save_baseline

    if not evals_dir.exists():
        raise click.ClickException(f"{evals_dir} does not exist.")

    result = run_suite(evals_dir, against=against)

    for error in result.load_errors:
        click.echo(f"  skipped (invalid eval file): {error}")

    if result.total_count == 0:
        click.echo("No eval cases to run.")
        raise SystemExit(1 if gate else 0)

    click.echo(f"{result.passed_count}/{result.total_count} case(s) passed against {against!r}.")
    for outcome in result.outcomes:
        if not outcome.passed:
            click.echo(f"  FAIL {outcome.trace_id}: {outcome.reasoning}")

    if not gate:
        return

    baseline = load_baseline(evals_dir)
    if baseline is None:
        click.echo("No baseline yet — recording this run as the baseline.")
        save_baseline(evals_dir, result)
        return

    baseline_passed, baseline_total = baseline
    significance = two_proportion_z_test(
        baseline_passed, baseline_total, result.passed_count, result.total_count, alpha=alpha
    )
    click.echo(
        f"Baseline: {significance.baseline_pass_rate:.1%} pass rate "
        f"({baseline_passed}/{baseline_total}). "
        f"Current: {significance.current_pass_rate:.1%} "
        f"({result.passed_count}/{result.total_count})."
    )
    if significance.is_regression:
        click.echo(f"REGRESSION: p={significance.p_value:.4f} < alpha={alpha}")
        raise SystemExit(1)

    click.echo(f"No significant regression (p={significance.p_value:.4f}).")
    save_baseline(evals_dir, result)


@main.command()
@click.option(
    "--label",
    "label_n",
    type=int,
    default=None,
    help="Sample and interactively hand-label N judge verdicts.",
)
@click.option(
    "--labeler",
    default=None,
    help="Name/email to record with each label (defaults to $USER).",
)
@click.option(
    "--include-labeled",
    is_flag=True,
    default=False,
    help="When sampling, include scores that already have a label from you "
    "(useful for measuring inter-labeler agreement).",
)
@click.option(
    "--report",
    "report_target",
    is_flag=False,
    flag_value="-",
    default=None,
    help="Compute Cohen's kappa + a threshold suggestion. Bare --report prints "
    "the markdown report to stdout; --report PATH writes it to a file.",
)
def calibrate(
    label_n: int | None, labeler: str | None, include_labeled: bool, report_target: str | None
) -> None:
    """Hand-label judge verdicts and report judge-vs-human agreement.

    With --label N: sample N judge-sourced scores (stratified by rubric)
    and prompt for a pass/fail call on each. With --report: compute Cohen's
    kappa (overall and by rubric) and a threshold suggestion from whatever
    has been labeled so far. Both can be combined in one run.
    """
    import os

    from regress.calibrate.collect import labeled_judge_scores, to_labeled_pairs, to_valued_pairs
    from regress.calibrate.kappa import kappa_by_rubric
    from regress.calibrate.report import render_report
    from regress.calibrate.sample import sample_judge_scores
    from regress.calibrate.threshold import suggest_threshold
    from regress.db import get_session, init_db
    from regress.models import Label, Score
    from regress.scoring import output_text

    if label_n is None and report_target is None:
        raise click.ClickException("Pass --label N and/or --report.")

    init_db()
    with get_session() as session:
        if label_n is not None:
            who = labeler or os.environ.get("USER", "unknown")
            all_scores = list(session.execute(select(Score)).scalars().all())
            sample = sample_judge_scores(all_scores, label_n, include_labeled=include_labeled)

            if not sample:
                click.echo("No unlabeled judge-sourced scores to sample from.")
            for i, score in enumerate(sample, start=1):
                click.echo(f"\n[{i}/{len(sample)}] rubric: {score.rubric}")
                if score.span is not None:
                    click.echo(f"  output: {output_text(score.span)}")
                click.echo(f"  judge verdict: {'PASS' if score.passed else 'FAIL'} "
                           f"(score={score.value:.2f}) — {score.reasoning}")
                human_value = click.confirm("  Does this response actually pass?")
                session.add(Label(score_id=score.id, human_value=human_value, labeler=who))
            session.commit()
            if sample:
                click.echo(f"\nRecorded {len(sample)} label(s).")

        if report_target is not None:
            scores = labeled_judge_scores(session)
            kappa_result = kappa_by_rubric(to_labeled_pairs(scores))
            threshold = suggest_threshold(to_valued_pairs(scores))
            report_text = render_report(kappa_result, threshold)

            if report_target == "-":
                click.echo("\n" + report_text)
            else:
                Path(report_target).write_text(report_text)
                click.echo(f"\nWrote report to {report_target}")


if __name__ == "__main__":
    main()
