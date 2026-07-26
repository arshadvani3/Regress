"""Pydantic response shapes for the dashboard API.

Hand-written rather than `from_attributes`-derived from the ORM models
one-for-one, because the dashboard's needs diverge from storage shape in a
few places (e.g. `TraceSummary.preview` collapses messages into one line;
`IssueDetail` embeds trace summaries instead of raw `IssueTrace` rows).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TraceSummary(BaseModel):
    id: str
    app: str | None
    status: str
    started_at: datetime | None
    latency_ms: float | None
    cost: float | None
    preview: str


class MessagePart(BaseModel):
    role: str | None
    direction: str
    text: str


class ScoreSummary(BaseModel):
    id: str
    name: str
    source: str
    value: float
    passed: bool | None
    rubric: str | None
    reasoning: str | None


class SpanDetail(BaseModel):
    id: str
    name: str
    gen_ai_operation_name: str | None
    gen_ai_provider_name: str | None
    request_model: str | None
    response_model: str | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    messages: list[MessagePart]
    scores: list[ScoreSummary]


class TraceDetail(BaseModel):
    id: str
    app: str | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    latency_ms: float | None
    cost: float | None
    spans: list[SpanDetail]
    scores: list[ScoreSummary]


class IssueSummary(BaseModel):
    id: str
    title: str
    description: str
    state: str
    trace_count: int
    created_at: datetime
    resolved_at: datetime | None


class IssueDetail(BaseModel):
    id: str
    title: str
    description: str
    state: str
    created_at: datetime
    resolved_at: datetime | None
    traces: list[TraceSummary]
    eval_paths: list[str]


class CalibrationPair(BaseModel):
    score_id: str
    rubric: str | None
    value: float
    judge_passed: bool | None
    human_value: bool
    labeler: str


class KappaResultOut(BaseModel):
    kappa: float | None
    agreement: float
    n: int
    judge_pass_rate: float
    human_pass_rate: float


class ThresholdSuggestionOut(BaseModel):
    suggested_threshold: float | None
    suggested_agreement: float
    judge_own_agreement: float
    n: int
    improves_on_judge: bool


class CalibrationReport(BaseModel):
    overall: KappaResultOut
    by_rubric: dict[str, KappaResultOut]
    threshold: ThresholdSuggestionOut
    labeled_pairs: list[CalibrationPair]


class UnlabeledScore(BaseModel):
    score_id: str
    rubric: str | None
    value: float
    passed: bool | None
    reasoning: str | None
    output_preview: str


class LabelCreate(BaseModel):
    score_id: str
    human_value: bool
    labeler: str
