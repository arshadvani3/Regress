import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { Async } from '../components/Async'
import { StatusBadge } from '../components/StatusBadge'

const STATE_LABEL: Record<string, string> = {
  active: 'Active',
  regressed: 'Regressed',
  resolved: 'Resolved',
}

export function IssueDetail() {
  const { issueId } = useParams<{ issueId: string }>()
  const { data, error, loading } = useApi(() => api.getIssue(issueId!), [issueId])

  return (
    <div>
      <Link to="/issues" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
        ← Issues
      </Link>
      <Async data={data} error={error} loading={loading}>
        {(issue) => (
          <div className="mt-3">
            <div className="mb-1 flex items-center gap-3">
              <h1 className="text-lg font-semibold">{issue.title}</h1>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                {STATE_LABEL[issue.state] ?? issue.state}
              </span>
            </div>
            <p className="mb-6 text-sm text-gray-600 dark:text-gray-400">{issue.description}</p>

            {issue.eval_paths.length > 0 && (
              <div className="mb-6">
                <h2 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
                  Generated evals
                </h2>
                <ul className="space-y-1">
                  {issue.eval_paths.map((path) => (
                    <li
                      key={path}
                      className="rounded bg-gray-50 px-2 py-1 font-mono text-xs dark:bg-gray-900"
                    >
                      {path}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <h2 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
              Traces in this cluster ({issue.traces.length})
            </h2>
            <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-900 text-left text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">App</th>
                    <th className="px-3 py-2 font-medium">Preview</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {issue.traces.map((trace) => (
                    <tr key={trace.id}>
                      <td className="px-3 py-2">
                        <StatusBadge status={trace.status} />
                      </td>
                      <td className="px-3 py-2">{trace.app ?? '—'}</td>
                      <td className="px-3 py-2 max-w-md truncate" title={trace.preview}>
                        <Link to={`/traces/${trace.id}`} className="hover:underline">
                          {trace.preview || trace.id}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Async>
    </div>
  )
}
