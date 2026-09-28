# Global Rules (cloud copy)

Copy of the global `Z:/vibing/CLAUDE.md` for cloud sessions, which only see the repo. Loaded by the SessionStart hook in `.claude/settings.json`, only when running in the cloud. Keep in sync with the local file.

Plugins don't load in the cloud, so skills are the ones in `.claude/skills/`, invoked without a plugin prefix (`/tdd`, not `/mattpocock-skills:tdd`). `ui-ux-pro-max` is not available here.

## Workflow
- For new feature work, reach for the Matt Pocock skills (`/tdd`, `/research`, `/prototype`) as needed rather than a formal GSD-style process — no forced planning ceremony for every phase.
- When debugging, invoke `/diagnosing-bugs` before proposing fixes.
- Before claiming anything is complete or fixed, invoke `/verification-before-completion`.
- When doing UI work, invoke `ui-ux-pro-max` before planning or implementing.

### Triviality gate
The rules above are for real feature/debugging work. Skip the formal skill and just do the thing when a task is small: a change under ~20 lines, a single obvious root cause (typo, off-by-one, wrong import, missing null check), a one-off script, or a cosmetic tweak (spacing, color, copy). Use judgment — if you're not sure whether something counts as trivial, do the lightweight version rather than the full skill. Verification for trivial changes can be "I read the diff and it does what was asked" — it doesn't need a full test-suite run unless the change touches shared/critical logic.

## Skill Suggestions
- If you notice the same multi-step pattern recurring across sessions, flag it: "We've done this a few times — want me to write a skill for it?" Do not create skills without explicit approval.

## Learning Context
- User is a new grad transitioning from physics into SWE — limited full-stack experience.
- For any significant architectural or technical decision, briefly explain *why* that approach is preferred over alternatives. Frame it the way a senior engineer would explain it to a junior.
- Don't skip the technical depth. Concise ≠ shallow.
- After a significant feature or phase of work completes, offer to quiz on key decisions (architecture, data flow, failure modes). User will get most wrong early — that's expected, focus on the reasoning not the answer.

## Code Quality
- Write code to company standards: clean, readable, testable.
- Include unit tests for non-trivial logic. Don't ship features without test coverage.
- CI/CD should be considered a first-class concern, not an afterthought.
- Prefer simple, explicit code over clever abstractions.

## Resume & Content Writing
- NEVER fabricate, embellish, or overclaim skills, job titles, degree names, or experience. Only use what the user has explicitly stated or confirmed.
- Avoid corporate jargon, LinkedIn-speak (e.g., "owned end-to-end", "hub-and-spoke", "multiplayer"), em dashes, and overly polished tone.
- Match the user's natural writing voice — direct and casual. When in doubt, ask rather than assume a polished tone.
- Keep resumes to ONE page unless explicitly told otherwise.
- Before including any claim that feels like a stretch, pause and ask the user — a quick "I'm about to write X, is that accurate?" is better than shipping something the user can't defend.

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
