import type { ReactNode } from 'react'

interface AsyncProps<T> {
  data: T | null
  error: string | null
  loading: boolean
  empty?: (data: T) => boolean
  emptyMessage?: string
  children: (data: T) => ReactNode
}

export function Async<T>({
  data,
  error,
  loading,
  empty,
  emptyMessage = 'Nothing here yet.',
  children,
}: AsyncProps<T>) {
  if (loading && data === null) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
  }
  if (error) {
    return (
      <p className="text-sm text-red-700 dark:text-red-400">
        Failed to load: {error}
      </p>
    )
  }
  if (data === null) {
    return null
  }
  if (empty?.(data)) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">{emptyMessage}</p>
  }
  return <>{children(data)}</>
}
