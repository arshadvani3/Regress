import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { Async } from '../components/Async'

export function TraceList() {
  const { data, error, loading } = useApi(() => api.listTraces(100), [])
  const navigate = useNavigate()

  return (
    <div>
      <h1 className="text-lg font-semibold mb-4">Traces</h1>
      <Async
        data={data}
        error={error}
        loading={loading}
        empty={(d) => d.length === 0}
        emptyMessage="No traces ingested yet. Point instrument() or an OTLP exporter at this server to see them here."
      >
        {(traces) => (
          <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900 text-left text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">App</th>
                  <th className="px-3 py-2 font-medium">Preview</th>
                  <th className="px-3 py-2 font-medium">Latency</th>
                  <th className="px-3 py-2 font-medium">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {traces.map((trace) => (
                  <tr
                    key={trace.id}
                    onClick={() => navigate(`/traces/${trace.id}`)}
                    className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900"
                  >
                    <td className="px-3 py-2">
                      <StatusBadge status={trace.status} />
                    </td>
                    <td className="px-3 py-2">{trace.app ?? '—'}</td>
                    <td className="px-3 py-2 max-w-md truncate" title={trace.preview}>
                      {trace.preview || '—'}
                    </td>
                    <td className="px-3 py-2 text-gray-500 dark:text-gray-400">
                      {trace.latency_ms !== null ? `${trace.latency_ms.toFixed(0)}ms` : '—'}
                    </td>
                    <td className="px-3 py-2 text-gray-500 dark:text-gray-400">
                      {trace.started_at ? new Date(trace.started_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </div>
  )
}
