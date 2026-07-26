const COLORS: Record<string, string> = {
  ok: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  error: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  unset: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
}

export function StatusBadge({ status }: { status: string }) {
  const classes = COLORS[status] ?? COLORS.unset
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${classes}`}>
      {status}
    </span>
  )
}
