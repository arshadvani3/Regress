"""Read-only routes for the dashboard: traces, issues, calibration.

Reuses the same logic the CLI uses (`regress.calibrate.*`,
`regress.scoring.output_text`) so the dashboard's numbers can never drift
from `regress calibrate --report`'s.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from regress.api.schemas import (
    CalibrationPair,
    CalibrationReport,
    IssueDetail,
    IssueSummary,
    KappaResultOut,
    LabelCreate,
    MessagePart,
    ScoreSummary,
    SpanDetail,
    ThresholdSuggestionOut,
    TraceDetail,
    TraceSummary,
    UnlabeledScore,
)
from regress.calibrate.collect import labeled_judge_scores, to_labeled_pairs, to_valued_pairs
from regress.calibrate.kappa import KappaResult, kappa_by_rubric
from regress.calibrate.sample import sample_judge_scores
from regress.calibrate.threshold import suggest_threshold
from regress.models import Issue, Label, Score, Trace
from regress.scoring import message_parts, output_text


def make_router(session_factory: sessionmaker[Session]) -> APIRouter:
    """Build the API router bound to a specific session factory.

    A factory function rather than a module-level router because
    `create_app()` supports swapping the SQLAlchemy engine (tests use an
    isolated in-memory DB), so the router's DB access must go through
    whatever engine that call was given, not `regress.db`'s default.
    """
    router = APIRouter(prefix="/api")

    @contextmanager
    def get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def session_dep() -> Iterator[Session]:
        with get_session() as session:
            yield session

    def _trace_preview(trace: Trace) -> str:
        for span in sorted(trace.spans, key=lambda s: s.started_at or trace.started_at or ""):
            for message in sorted(span.messages, key=lambda m: m.position):
                if message.direction != "input":
                    continue
                for part in message_parts(message.content):
                    content = part.get("content")
                    if isinstance(content, str) and content.strip():
                        return content[:200]
        return ""

    def _trace_summary(trace: Trace) -> TraceSummary:
        return TraceSummary(
            id=trace.id,
            app=trace.app,
            status=trace.status,
            started_at=trace.started_at,
            latency_ms=trace.latency_ms,
            cost=trace.cost,
            preview=_trace_preview(trace),
        )

    def _score_summary(score: Score) -> ScoreSummary:
        return ScoreSummary(
            id=score.id,
            name=score.name,
            source=score.source,
            value=score.value,
            passed=score.passed,
            rubric=score.rubric,
            reasoning=score.reasoning,
        )

    def _kappa_out(result: KappaResult) -> KappaResultOut:
        return KappaResultOut(
            kappa=result.kappa,
            agreement=result.agreement,
            n=result.n,
            judge_pass_rate=result.judge_pass_rate,
            human_pass_rate=result.human_pass_rate,
        )

    @router.get("/traces", response_model=list[TraceSummary])
    def list_traces(
        limit: int = 50, session: Session = Depends(session_dep)
    ) -> list[TraceSummary]:
        traces = (
            session.execute(select(Trace).order_by(Trace.ingested_at.desc()).limit(limit))
            .scalars()
            .all()
        )
        return [_trace_summary(t) for t in traces]

    @router.get("/traces/{trace_id}", response_model=TraceDetail)
    def get_trace(trace_id: str, session: Session = Depends(session_dep)) -> TraceDetail:
        trace = session.get(Trace, trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")

        spans = sorted(trace.spans, key=lambda s: s.started_at or trace.started_at or "")
        return TraceDetail(
            id=trace.id,
            app=trace.app,
            status=trace.status,
            started_at=trace.started_at,
            ended_at=trace.ended_at,
            latency_ms=trace.latency_ms,
            cost=trace.cost,
            scores=[_score_summary(s) for s in trace.scores],
            spans=[
                SpanDetail(
                    id=span.id,
                    name=span.name,
                    gen_ai_operation_name=span.gen_ai_operation_name,
                    gen_ai_provider_name=span.gen_ai_provider_name,
                    request_model=span.request_model,
                    response_model=span.response_model,
                    status=span.status,
                    started_at=span.started_at,
                    ended_at=span.ended_at,
                    messages=[
                        MessagePart(
                            role=message.role,
                            direction=message.direction,
                            text="\n".join(
                                str(part.get("content", ""))
                                for part in message_parts(message.content)
                                if isinstance(part.get("content"), str)
                            ),
                        )
                        for message in sorted(span.messages, key=lambda m: m.position)
                    ],
                    scores=[_score_summary(s) for s in span.scores],
                )
                for span in spans
            ],
        )

    @router.get("/issues", response_model=list[IssueSummary])
    def list_issues(
        state: str | None = None, session: Session = Depends(session_dep)
    ) -> list[IssueSummary]:
        query = select(Issue).order_by(Issue.created_at.desc())
        if state:
            query = query.where(Issue.state == state)
        issues = session.execute(query).scalars().all()
        return [
            IssueSummary(
                id=issue.id,
                title=issue.title,
                description=issue.description,
                state=issue.state,
                trace_count=len(issue.trace_links),
                created_at=issue.created_at,
                resolved_at=issue.resolved_at,
            )
            for issue in issues
        ]

    @router.get("/issues/{issue_id}", response_model=IssueDetail)
    def get_issue(issue_id: str, session: Session = Depends(session_dep)) -> IssueDetail:
        issue = session.get(Issue, issue_id)
        if issue is None:
            raise HTTPException(status_code=404, detail="Issue not found")

        return IssueDetail(
            id=issue.id,
            title=issue.title,
            description=issue.description,
            state=issue.state,
            created_at=issue.created_at,
            resolved_at=issue.resolved_at,
            traces=[_trace_summary(link.trace) for link in issue.trace_links],
            eval_paths=[e.path for e in issue.evals],
        )

    @router.get("/calibration/unlabeled", response_model=list[UnlabeledScore])
    def unlabeled_scores(
        n: int = 10,
        include_labeled: bool = False,
        session: Session = Depends(session_dep),
    ) -> list[UnlabeledScore]:
        all_scores = list(session.execute(select(Score)).scalars().all())
        sample = sample_judge_scores(all_scores, n, include_labeled=include_labeled)
        return [
            UnlabeledScore(
                score_id=score.id,
                rubric=score.rubric,
                value=score.value,
                passed=score.passed,
                reasoning=score.reasoning,
                output_preview=output_text(score.span)[:500] if score.span else "",
            )
            for score in sample
        ]

    @router.post("/labels", status_code=201)
    def create_label(body: LabelCreate, session: Session = Depends(session_dep)) -> dict[str, str]:
        score = session.get(Score, body.score_id)
        if score is None:
            raise HTTPException(status_code=404, detail="Score not found")

        label = Label(score_id=body.score_id, human_value=body.human_value, labeler=body.labeler)
        session.add(label)
        session.commit()
        return {"id": label.id}

    @router.get("/calibration/report", response_model=CalibrationReport)
    def calibration_report(session: Session = Depends(session_dep)) -> CalibrationReport:
        scores = labeled_judge_scores(session)
        kappa_result = kappa_by_rubric(to_labeled_pairs(scores))
        threshold = suggest_threshold(to_valued_pairs(scores))

        pairs = [
            CalibrationPair(
                score_id=score.id,
                rubric=score.rubric,
                value=score.value,
                judge_passed=score.passed,
                human_value=label.human_value,
                labeler=label.labeler,
            )
            for score in scores
            for label in score.labels
        ]

        return CalibrationReport(
            overall=_kappa_out(kappa_result.overall),
            by_rubric={k: _kappa_out(v) for k, v in kappa_result.by_rubric.items()},
            threshold=ThresholdSuggestionOut(
                suggested_threshold=threshold.suggested_threshold,
                suggested_agreement=threshold.suggested_agreement,
                judge_own_agreement=threshold.judge_own_agreement,
                n=threshold.n,
                improves_on_judge=threshold.improves_on_judge,
            ),
            labeled_pairs=pairs,
        )

    return router
