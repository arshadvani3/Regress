# Regress dashboard

Vite + React + TypeScript + Tailwind. Talks to the read-only JSON API at
`/api/*` served by `regress up` (see `src/regress/api/`). Three views:
trace explorer, issue kanban, calibration.

```bash
npm install
npm run dev      # :5173, proxies /api and /health to :8990 (run `regress up` separately)
npm run build    # writes ../src/regress/dashboard_dist/ for `regress up` to serve directly
```

No routing/build config beyond what `vite.config.ts` sets: `outDir` points
at `dashboard_dist` so a plain `regress up` picks up whatever was last
built, no copy step needed.
