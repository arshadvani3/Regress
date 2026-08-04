# Releasing Regress

Publishing to PyPI is automated via `.github/workflows/release.yml`, which
builds the dashboard, packages the wheel, and publishes on any pushed tag
matching `v*` — using PyPI **Trusted Publishing** (OIDC), so no PyPI API token
is stored as a repo secret.

## One-time setup

> Already done for `regress-ai` (completed for the v0.1.0 release). Kept here as
> a reference for the mechanism and for anyone forking this project.

1. **Register a pending publisher** on PyPI — this reserves the `regress-ai`
   name *and* authorizes the workflow in one step, with no local `twine upload`
   and no API token. On pypi.org → account → *Publishing* → *Add a pending
   publisher* (GitHub), with:
   - PyPI Project Name: `regress-ai`
   - Repository owner: `arshadvani3`
   - Repository name: `Regress` (case-sensitive)
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. **Create a `pypi` GitHub Environment** on this repo (Settings → Environments)
   so `release.yml`'s `environment: pypi` gate has somewhere to point. Add
   yourself as a **required reviewer** (Deployment protection rules) so every
   publish pauses for a one-click approval — the safety net against an
   accidental tag push going live, since PyPI versions can't be re-uploaded.

No secrets need to be added anywhere — Trusted Publishing exchanges a
short-lived OIDC token for the release, scoped to this exact workflow.

## Cutting a release

1. Bump `version` in `pyproject.toml` and `__version__` in
   `src/regress/__init__.py` (keep them in sync).
2. Commit the version bump.
3. Tag the new version (annotated) and push just that tag — matching `vX.Y.Z`
   triggers the workflow:
   ```bash
   git tag -a vX.Y.Z -m "regress-ai X.Y.Z"
   git push origin vX.Y.Z
   ```
4. The `Release` workflow builds the dashboard, builds the sdist + wheel, then
   **pauses on the `pypi` environment gate**. Approve the deployment under the
   *Actions* tab (Review deployments → `pypi` → Approve and deploy) to publish.

> A version can only be published to PyPI once — if the `publish` job fails
> *after* a version is live, you must bump to a new version; you can't re-upload.
> If it fails *before* publishing (e.g. a config mismatch), fix and re-run the
> job from the Actions UI — no new tag needed.

## Verifying a release

```bash
pip index versions regress-ai   # confirm the new version is live
pip install regress-ai==0.1.0
regress --version
```
