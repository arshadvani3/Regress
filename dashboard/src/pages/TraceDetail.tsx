import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { Async } from '../components/Async'
import type { ScoreSummary } from '../api/types'

function ScorePill({ score }: { score: ScoreSummary }) {
  const passed = score.passed
  const color =
    passed === true
      ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300'
      : passed === false
        ? 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300'
        : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
  return (
    <div className={`rounded px-2 py-1 text-xs ${color}`} title={score.reasoning ?? undefined}>
      <span className="font-medium">{score.rubric ?? score.name}</span>
      {' — '}
      {passed === true ? 'pass' : passed === false ? 'fail' : score.value.toFixed(2)}
      <span className="opacity-60"> ({score.source})</span>
    </div>
  )
}

export function TraceDetail() {
  const { traceId } = useParams<{ traceId: string }>()
  const { data, error, loading } = useApi(() => api.getTrace(traceId!), [traceId])

  return (
    <div>
      <Link to="/" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
        ← Traces
      </Link>
      <Async data={data} error={error} loading={loading}>
        {(trace) => (
          <div className="mt-3">
            <div className="mb-4 flex items-center gap-3">
              <StatusBadge status={trace.status} />
              <h1 className="text-lg font-semibold">{trace.app ?? trace.id}</h1>
              {trace.latency_ms !== null && (
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  {trace.latency_ms.toFixed(0)}ms
                </span>
              )}
            </div>

            {trace.scores.length > 0 && (
              <div className="mb-6 flex flex-wrap gap-2">
                {trace.scores.map((score) => (
                  <ScorePill key={score.id} score={score} />
                ))}
              </div>
            )}

            <div className="space-y-4">
              {trace.spans.map((span) => (
                <div
                  key={span.id}
                  className="rounded-lg border border-gray-200 p-4 dark:border-gray-800"
                >
                  <div className="mb-3 flex items-center gap-2">
                    <StatusBadge status={span.status} />
                    <span className="font-medium">{span.name}</span>
                    {span.request_model && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {span.request_model}
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    {span.messages.map((message, i) => (
                      <div
                        key={i}
                        className="rounded-md bg-gray-50 p-3 text-sm dark:bg-gray-900"
                      >
                        <div className="mb-1 text-xs font-medium uppercase text-gray-400">
                          {message.role ?? message.direction}
                        </div>
                        <div className="whitespace-pre-wrap">{message.text}</div>
                      </div>
                    ))}
                  </div>
                  {span.scores.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {span.scores.map((score) => (
                        <ScorePill key={score.id} score={score} />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </Async>
    </div>
  )
}
