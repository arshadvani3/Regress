// Mirrors src/regress/api/schemas.py — keep these in sync by hand; there's
// no codegen step (small surface, not worth the build complexity yet).

export interface TraceSummary {
  id: string
  app: string | null
  status: string
  started_at: string | null
  latency_ms: number | null
  cost: number | null
  preview: string
}

export interface MessagePart {
  role: string | null
  direction: string
  text: string
}

export interface ScoreSummary {
  id: string
  name: string
  source: string
  value: number
  passed: boolean | null
  rubric: string | null
  reasoning: string | null
}

export interface SpanDetail {
  id: string
  name: string
  gen_ai_operation_name: string | null
  gen_ai_provider_name: string | null
  request_model: string | null
  response_model: string | null
  status: string
  started_at: string | null
  ended_at: string | null
  messages: MessagePart[]
  scores: ScoreSummary[]
}

export interface TraceDetail {
  id: string
  app: string | null
  status: string
  started_at: string | null
  ended_at: string | null
  latency_ms: number | null
  cost: number | null
  spans: SpanDetail[]
  scores: ScoreSummary[]
}

export type IssueState = 'active' | 'resolved' | 'regressed'

export interface IssueSummary {
  id: string
  title: string
  description: string
  state: IssueState
  trace_count: number
  created_at: string
  resolved_at: string | null
}

export interface IssueDetail {
  id: string
  title: string
  description: string
  state: IssueState
  created_at: string
  resolved_at: string | null
  traces: TraceSummary[]
  eval_paths: string[]
}

export interface KappaResult {
  kappa: number | null
  agreement: number
  n: number
  judge_pass_rate: number
  human_pass_rate: number
}

export interface ThresholdSuggestion {
  suggested_threshold: number | null
  suggested_agreement: number
  judge_own_agreement: number
  n: number
  improves_on_judge: boolean
}

export interface CalibrationPair {
  score_id: string
  rubric: string | null
  value: number
  judge_passed: boolean | null
  human_value: boolean
  labeler: string
}

export interface CalibrationReport {
  overall: KappaResult
  by_rubric: Record<string, KappaResult>
  threshold: ThresholdSuggestion
  labeled_pairs: CalibrationPair[]
}

export interface UnlabeledScore {
  score_id: string
  rubric: string | null
  value: number
  passed: boolean | null
  reasoning: string | null
  output_preview: string
}
