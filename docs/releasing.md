# Releasing Regress

Publishing to PyPI is automated via `.github/workflows/release.yml`, which
builds the dashboard, packages the wheel, and publishes on any pushed tag
matching `v*` — using PyPI **Trusted Publishing** (OIDC), so no PyPI API token
is stored as a repo secret.

## One-time setup (before the first release)

1. **Create the project on PyPI** — either publish once manually
   (`python -m build && twine upload dist/*`) to reserve the `regress-ai` name,
   or use PyPI's "pending publisher" flow to register a trusted publisher for a
   project that doesn't exist yet.
2. **Register a trusted publisher** on PyPI for `regress-ai`:
   PyPI project → *Publishing* → *Add a new publisher* → GitHub, with:
   - Repository owner: `arshadvani3`
   - Repository name: `Regress`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. **Create a `pypi` GitHub Environment** on this repo (Settings → Environments)
   so `release.yml`'s `environment: pypi` gate has somewhere to point. Optional:
   require a reviewer on that environment for an extra manual confirmation
   before every publish.

No secrets need to be added anywhere — Trusted Publishing exchanges a
short-lived OIDC token for the release, scoped to this exact workflow.

## Cutting a release

1. Bump `version` in `pyproject.toml` and `__version__` in
   `src/regress/__init__.py` (keep them in sync).
2. Commit the version bump.
3. Tag and push:
   ```bash
   git tag v0.1.0
   git push --tags
   ```
4. The `Release` workflow builds the dashboard, builds the sdist + wheel, and
   publishes to PyPI. Watch the run under the *Actions* tab.

## Verifying a release

```bash
pip index versions regress-ai   # confirm the new version is live
pip install regress-ai==0.1.0
regress --version
```
