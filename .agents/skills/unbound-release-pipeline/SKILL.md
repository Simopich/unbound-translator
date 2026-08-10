---
name: unbound-release-pipeline
description: Maintain or diagnose the Pokemon Unbound GitHub Actions BPS release pipeline. Use for ready-translations builds, ROM secret/MD5 checks, BPS assets, prerelease tags and descriptions, commit links, concurrency, or Discord announcements; do not use for ordinary local ROM injection or translation wording.
---

# Unbound Release Pipeline

Treat `.github/workflows/release-ready-translations.yml` as the implementation and `README.md` as public setup
documentation. Keep release changes narrow and never expose ROM data.

## Contract

- Input: each complete controlfixed `ready-translations/<language>.json` and secret `UNBOUND_ENGLISH_ROM_URL`.
- Verify source ROM MD5 `9cad8e771940e7f7094d13911552cef0` before injection.
- Output only `dist/unbound-translated-<language>.bps`; delete temporary translated ROMs.
- Inject with safe script-slot reclamation plus `--fail-on-no-space`; never publish a partial translation.
- Pushes to `main` publish stable releases; pushes to `qa` publish prereleases. Releases contain BPS assets only.
- Successful releases may announce through optional `DISCORD_WEBHOOK_URL`.
- Failed/cancelled builds stay silent. Discord delivery failure is non-blocking.

## Workflow

1. Read the full workflow, `scripts/create_bps.py`, relevant tests, and the Ready Translations README section.
2. Preserve push-on-`main` and `qa`, branch-specific release status, manual dispatch, full Git history, `main`
   concurrency cancellation, uncancelled `qa` commit builds, and least required permissions.
3. Keep shell interpolation runtime-safe: GitHub expressions use `${{ ... }}`; shell variables use `${...}`. Build commit
   URLs from `GITHUB_SERVER_URL`/`GITHUB_REPOSITORY` or correctly expanded equivalents.
4. Derive one language per JSON basename and one BPS asset per language. Never run controlfix in CI; ready JSON is
   already controlfixed.
5. Keep release notes deterministic: asset list, language/flag label, version, and linked commit hashes/messages.
6. Escape Discord payloads with `jq`; disable mentions and keep webhook failures isolated from release success.
7. Update README and root release contract only when user-facing/cross-cutting behavior changes.

## Stop Conditions

Abort design or implementation if it could upload a ROM, bypass MD5 verification, publish partial/lossy injection,
announce failed builds, or expose secrets in logs/releases.

## Verification

- Run `git diff --check` and `python -m pytest tests/test_create_bps.py tests/test_ready_translation_safety.py`.
- Parse/inspect the workflow with an available YAML or Actions validator; do not install a new dependency solely for it.
- Confirm asset glob is BPS-only, prerelease status follows branch, failure notifications are absent, and generated URLs
  contain no literal `${...}` placeholders.
- For behavior requiring GitHub itself, report the unverified hosted portion explicitly.
