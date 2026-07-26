import type {
  CalibrationReport,
  IssueDetail,
  IssueSummary,
  TraceDetail,
  TraceSummary,
  UnlabeledScore,
} from './types'

class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new ApiError(response.status, detail || response.statusText)
  }
  return response.json() as Promise<T>
}

export const api = {
  listTraces: (limit = 50) => request<TraceSummary[]>(`/api/traces?limit=${limit}`),
  getTrace: (id: string) => request<TraceDetail>(`/api/traces/${id}`),

  listIssues: (state?: string) =>
    request<IssueSummary[]>(`/api/issues${state ? `?state=${state}` : ''}`),
  getIssue: (id: string) => request<IssueDetail>(`/api/issues/${id}`),

  unlabeledScores: (n = 10) =>
    request<UnlabeledScore[]>(`/api/calibration/unlabeled?n=${n}`),
  calibrationReport: () => request<CalibrationReport>('/api/calibration/report'),
  createLabel: (scoreId: string, humanValue: boolean, labeler: string) =>
    request<{ id: string }>('/api/labels', {
      method: 'POST',
      body: JSON.stringify({ score_id: scoreId, human_value: humanValue, labeler }),
    }),
}

export { ApiError }
