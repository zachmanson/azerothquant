# Global Rules (cloud copy)

Copy of the global `C:/vibing/CLAUDE.md` for cloud sessions, which only see the repo. Loaded by the SessionStart hook in `.claude/settings.json`, only when running in the cloud. Keep in sync with the local file.

Plugins don't load in the cloud, so skills are the ones in `.claude/skills/`, invoked without a plugin prefix (`/tdd`, not `/mattpocock-skills:tdd`). `ui-ux-pro-max` is in `.claude/skills/` too.

## Workflow
- For new feature work, reach for the Matt Pocock skills (`/tdd`, `/research`, `/prototype`) as needed rather than a formal GSD-style process — no forced planning ceremony for every phase.
- When debugging, invoke `/diagnosing-bugs` before proposing fixes.
- Before claiming anything is complete or fixed, invoke `/verification-before-completion`.
- When doing UI work, invoke `ui-ux-pro-max` before planning or implementing.

### Triviality gate
The rules above are for real feature/debugging work. Skip the formal skill and just do the thing when a task is small: a change under ~20 lines, a single obvious root cause (typo, off-by-one, wrong import, missing null check), a one-off script, or a cosmetic tweak (spacing, color, copy). Use judgment — if you're not sure whether something counts as trivial, do the lightweight version rather than the full skill. Verification for trivial changes can be "I read the diff and it does what was asked" — it doesn't need a full test-suite run unless the change touches shared/critical logic.

## Skill Suggestions
- If you notice the same multi-step pattern recurring across sessions, flag it: "We've done this a few times — want me to write a skill for it?" Do not create skills without explicit approval.

## Code Quality
- Write code to company standards: clean, readable, testable.
- Include unit tests for non-trivial logic. Don't ship features without test coverage.
- CI/CD should be considered a first-class concern, not an afterthought.
- Prefer simple, explicit code over clever abstractions.

## Debugging
- Before applying a fix, state the root cause hypothesis and verify it with a minimal test. Do not chain multiple speculative fixes.
- When fixing serialization/data issues, always check for double-encoding or shape mismatches first.
- If an approach is architecturally infeasible, flag it early rather than debugging indefinitely — surface blockers before writing code.
- If a fix attempt fails, diagnose why before switching tactics. Don't retry the identical approach blindly.

## Project Context
- When referencing phases, milestones, or project state, ALWAYS check STATE.md and ROADMAP.md before assuming what exists. Never reference a phase that hasn't been created yet.

## Sessions
- One session = one *thing*: an issue, a slice, a bug, a discussion. Anything new that comes up gets filed as an issue or noted for the handoff, and the session stays on its thing.
- Budget ~150k tokens per session. If the thing is running long, stop at a clean point and hand off the rest.
- When the thing is done (verified and committed), end with a **handoff**:
  1. Add a dated entry at the top of `docs/agents/whats-next.md`, then commit and push it: what just finished, the next thing in order, and any gotchas the next session needs.
  2. Tell me to start a new session.
  3. Give the exact opening message for the next session in a code block I can paste, including the skill command if one fits (e.g. `/tdd` for #32).

## Communication
- Be concise. No trailing summaries, no restating what was just done.
- Lead with the answer or action, then reasoning if needed.

## Cloud notes
- Tests: `cd brain && pytest -q` and `busted --directory=addon`. The SessionStart hook installs both; if either is missing, read `/tmp/cloud-session-start.log`.
- The Brain's live data (`brain/history.sqlite`, `brain/archive/`, `brain/config.toml`, `brain/predictions.toml`) is gitignored and not here. Anything that needs it, or the game, is for a local session: note it in the handoff.
- `gh issue view/comment/edit` go through GraphQL, which the cloud GitHub proxy may reject with a 403. Fall back to REST: `gh api repos/zachmanson/azerothquant/issues/<n>`, `.../issues/<n>/comments` (GET, or POST `-f body=...`), `.../issues/<n>/labels` (POST `-f "labels[]=..."`).
- Push straight to `main` (fine in this repo). If the session was started on a `claude/...` branch, merge or push it to `main` before the handoff.
