import { useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { Async } from '../components/Async'
import type { KappaResult } from '../api/types'

const KAPPA_BANDS: [number, string][] = [
  [0.81, 'almost perfect'],
  [0.61, 'substantial'],
  [0.41, 'moderate'],
  [0.21, 'fair'],
  [0.0, 'slight'],
  [-Infinity, 'poor'],
]

function interpretKappa(kappa: number | null): string {
  if (kappa === null) return 'n/a'
  const band = KAPPA_BANDS.find(([lower]) => kappa >= lower)
  return band ? band[1] : 'n/a'
}

function KappaCard({ label, result }: { label: string; result: KappaResult }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <p className="text-xs font-medium uppercase text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold">
        {result.kappa === null ? 'n/a' : result.kappa.toFixed(2)}
      </p>
      <p className="text-xs text-gray-500 dark:text-gray-400">{interpretKappa(result.kappa)}</p>
      <p className="mt-2 text-xs text-gray-400">
        {result.n} pair{result.n === 1 ? '' : 's'} · {(result.agreement * 100).toFixed(0)}% raw
        agreement
      </p>
    </div>
  )
}

function LabelingFlow({ onLabeled }: { onLabeled: () => void }) {
  const { data, error, loading, reload } = useApi(() => api.unlabeledScores(10), [])
  const [index, setIndex] = useState(0)
  const [labeler, setLabeler] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (value: boolean) => {
    if (!data || !data[index] || !labeler.trim()) return
    setSubmitting(true)
    try {
      await api.createLabel(data[index].score_id, value, labeler.trim())
      if (index + 1 < data.length) {
        setIndex(index + 1)
      } else {
        setIndex(0)
        reload()
      }
      onLabeled()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
      <h2 className="mb-3 text-sm font-medium text-gray-500 dark:text-gray-400">
        Label a judge verdict
      </h2>
      <label className="mb-3 block text-xs text-gray-500 dark:text-gray-400">
        Your name/email
        <input
          value={labeler}
          onChange={(e) => setLabeler(e.target.value)}
          placeholder="you@example.com"
          className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
        />
      </label>
      <Async
        data={data}
        error={error}
        loading={loading}
        empty={(d) => d.length === 0}
        emptyMessage="No unlabeled judge verdicts to label right now."
      >
        {(scores) => {
          const current = scores[index]
          if (!current) return null
          return (
            <div>
              <p className="text-xs text-gray-400">
                {index + 1} of {scores.length} — rubric: {current.rubric ?? '(none)'}
              </p>
              <div className="my-3 rounded-md bg-gray-50 p-3 text-sm dark:bg-gray-900">
                {current.output_preview || '(empty output)'}
              </div>
              <p className="mb-3 text-sm">
                Judge said:{' '}
                <span className="font-medium">
                  {current.passed === true ? 'PASS' : current.passed === false ? 'FAIL' : '—'}
                </span>{' '}
                <span className="text-gray-400">({current.value.toFixed(2)})</span>
                {current.reasoning && (
                  <span className="text-gray-500 dark:text-gray-400"> — {current.reasoning}</span>
                )}
              </p>
              <div className="flex gap-2">
                <button
                  disabled={submitting || !labeler.trim()}
                  onClick={() => submit(true)}
                  className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  Actually passes
                </button>
                <button
                  disabled={submitting || !labeler.trim()}
                  onClick={() => submit(false)}
                  className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  Actually fails
                </button>
              </div>
            </div>
          )
        }}
      </Async>
    </div>
  )
}

export function Calibration() {
  const { data, error, loading, reload } = useApi(() => api.calibrationReport(), [])

  return (
    <div>
      <h1 className="text-lg font-semibold mb-4">Calibration</h1>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LabelingFlow onLabeled={reload} />

        <Async data={data} error={error} loading={loading}>
          {(report) => (
            <div className="space-y-4">
              <KappaCard label="Overall judge-vs-human kappa" result={report.overall} />

              {Object.keys(report.by_rubric).length > 1 && (
                <div className="space-y-2">
                  {Object.entries(report.by_rubric).map(([rubric, result]) => (
                    <KappaCard key={rubric} label={rubric} result={result} />
                  ))}
                </div>
              )}

              <div className="rounded-lg border border-gray-200 p-4 text-sm dark:border-gray-800">
                <p className="text-xs font-medium uppercase text-gray-400">
                  Threshold suggestion
                </p>
                {report.threshold.suggested_threshold === null ? (
                  <p className="mt-1 text-gray-500 dark:text-gray-400">
                    Not enough labeled data to suggest a threshold.
                  </p>
                ) : report.threshold.improves_on_judge ? (
                  <p className="mt-1">
                    A cutoff of{' '}
                    <span className="font-medium">
                      {report.threshold.suggested_threshold.toFixed(2)}
                    </span>{' '}
                    improves on the judge's own pass/fail call:{' '}
                    {(report.threshold.suggested_agreement * 100).toFixed(0)}% vs.{' '}
                    {(report.threshold.judge_own_agreement * 100).toFixed(0)}% agreement with
                    humans.
                  </p>
                ) : (
                  <p className="mt-1 text-gray-500 dark:text-gray-400">
                    The judge's own pass/fail call already agrees with humans as well as any
                    threshold cutoff — no threshold change suggested.
                  </p>
                )}
              </div>
            </div>
          )}
        </Async>
      </div>
    </div>
  )
}
