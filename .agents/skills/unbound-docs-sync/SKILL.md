---
name: unbound-docs-sync
description: Keep Unbound translator documentation and Codex metadata accurate without bloating always-loaded context. Use when workflows, JSON contracts, ROM assumptions, supported languages, README.md, AGENTS.md, .codex configuration, agents, or repository skills change; do not use for implementation-only edits with no durable contract change.
---

# Unbound Docs Sync

Update documentation only where information belongs. Cross-cutting repository contracts go in `AGENTS.md`; human
setup, roadmap, usage, and release documentation go in `README.md`; repeatable task procedures go in the matching skill.

## Placement Rules

- Keep root `AGENTS.md` short and practical: repository purpose, important paths, canonical commands, non-negotiable
  invariants, verification, and done criteria.
- Do not place roadmap ideas, possible future features, one-off debugging history, option catalogs, or detailed task
  procedures in `AGENTS.md`.
- Avoid duplicating instructions across `AGENTS.md`, `README.md`, and skills. Keep one authoritative owner and add a
  short pointer elsewhere only when discovery requires it.
- Keep skill `description` fields trigger-first and specific. Each skill owns one job with explicit input, output,
  procedure, stop conditions, and verification.
- Use `references/` only when progressive disclosure saves meaningful context. Link references directly from
  `SKILL.md`; avoid nested reference chains.
- Update both `AGENTS.md` and `README.md` only when a cross-cutting workflow or public contract truly affects both.

## Checks

- Keep shared command examples aligned and remove stale facts instead of preserving historical notes.
- Run `git diff --check` after documentation edits.
- Validate every changed skill with the project/system skill validator.
- Run Python compile checks only when Python files changed.
