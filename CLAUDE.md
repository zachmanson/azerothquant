# azerothquant

Read `docs/agents/whats-next.md` at the start of every session: it has the work queue and the gotchas. Handoffs update that file.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues on zachmanson/azerothquant (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Ending a session

Always end with a handoff: a single command the user can paste to continue in the next session (e.g. `/tdd Build #50 per the spec comment on the issue, then /code-review and commit`). Make it self-contained: name the issue and the skill to run.
