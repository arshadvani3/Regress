import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { Async } from '../components/Async'
import type { IssueState, IssueSummary } from '../api/types'

const COLUMNS: { state: IssueState; label: string; accent: string }[] = [
  { state: 'active', label: 'Active', accent: 'border-t-amber-400' },
  { state: 'regressed', label: 'Regressed', accent: 'border-t-red-500' },
  { state: 'resolved', label: 'Resolved', accent: 'border-t-green-500' },
]

function IssueCard({ issue }: { issue: IssueSummary }) {
  return (
    <Link
      to={`/issues/${issue.id}`}
      className="block rounded-lg border border-gray-200 p-3 hover:border-gray-300 hover:shadow-sm dark:border-gray-800 dark:hover:border-gray-700"
    >
      <p className="text-sm font-medium">{issue.title}</p>
      <p className="mt-1 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
        {issue.description}
      </p>
      <p className="mt-2 text-xs text-gray-400">
        {issue.trace_count} trace{issue.trace_count === 1 ? '' : 's'}
      </p>
    </Link>
  )
}

export function IssueBoard() {
  const { data, error, loading } = useApi(() => api.listIssues(), [])

  return (
    <div>
      <h1 className="text-lg font-semibold mb-4">Issues</h1>
      <Async
        data={data}
        error={error}
        loading={loading}
        empty={(d) => d.length === 0}
        emptyMessage="No issues yet. Run `regress cluster` after scoring some traces to discover failure clusters."
      >
        {(issues) => (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {COLUMNS.map((col) => {
              const columnIssues = issues.filter((i) => i.state === col.state)
              return (
                <div key={col.state} className={`border-t-4 ${col.accent} pt-3`}>
                  <h2 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
                    {col.label} ({columnIssues.length})
                  </h2>
                  <div className="space-y-2">
                    {columnIssues.map((issue) => (
                      <IssueCard key={issue.id} issue={issue} />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Async>
    </div>
  )
}
