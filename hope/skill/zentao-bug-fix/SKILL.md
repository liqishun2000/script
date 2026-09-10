---
name: zentao-bug-fix
description: Handle ZenTao bugs against the current repository, from reading reproduction steps and attachments through fixes, verification, commits, push, and verified resolution updates. Use for requests to process or fix ZenTao bugs, including batches; preserve read-only or no-push restrictions when the user only requests inspection or diagnosis.
---

# ZenTao Bug Fix

## Scope and Defaults

For a request to process or fix bugs with this skill, the user's chosen default is the complete workflow: inspect, fix, verify, commit, push, and resolve in ZenTao. Announce that scope before starting. Immediately before each external mutation, check that it remains within the user's current authorization; an already authorized full workflow does not require repeated confirmation.

Explicit limits override the default. Reading, diagnosing, reviewing, or planning does not authorize code changes, commits, pushes, or status updates. A no-push request stops publication; do not mark an unpublished fix resolved unless the user explicitly chooses that handoff. Skill invocation never overrides tool permissions or Plan mode.

Infer no product, account, repository, build, branch, or bug IDs from prior executions. Determine them from the current repository and the user's current URL or bug list. If that mapping is ambiguous, ask before editing or changing external state.

## Read and Triage

1. Inspect repository instructions, worktree changes, branch/upstream, relevant code, and available verification tooling. Preserve unrelated user changes and never stage them incidentally.
2. Read [ZenTao browser operations](references/zentao-browser.md) before connecting or updating statuses. Reuse an authorized connection and the user's login. Inspect product identity, current filters, pagination, and each selected bug's current status. For an open-ended batch, capture the initial in-scope unresolved IDs; report later arrivals separately instead of silently expanding the batch.
3. Read each bug's reproduction steps, actual and expected results, screenshots, and relevant videos. Do not infer missing expectations from a clipped list screenshot. Confirm unclear requirements with the user while progressing independent bugs.
4. Maintain a compact per-bug ledger: ID/title, expected behavior, root cause, affected code, fix, verification evidence, commit, publication state, and confirmed ZenTao state. Keep temporary attachments and working notes outside the repository unless project conventions require a tracked artifact.

## Fix and Verify

- Reproduce or establish the code path before editing. Separate missing functionality, hidden UI, configuration, stale builds, and already-fixed behavior. An existing fix may qualify after verification; record its actual commit instead of making an empty change.
- Group shared root causes and keep edits scoped. Use independent agents only when authorized and useful, assign non-overlapping ownership, and centralize shared-device work, Git integration, and ZenTao writes in the coordinating agent.
- Test against the bug's expected result, not just build success. For Android work, read [Android verification](references/android-verification.md). Use repository-appropriate checks for other platforms.
- Inspect existing failures before classifying them as pre-existing. Do not suppress checks to obtain a green result. Report residual failures and verification limits precisely; unverified bugs stay unresolved.
- A blocker on one bug does not block verified independent fixes. Never manufacture a requirement or mark an ambiguous bug fixed to finish a batch.

## Publish and Resolve

1. Review the full intended diff and stage only the batch's changes. Commit with bug IDs or a traceable description. Use the available `git-push` skill for authorized publication and read its instructions first. If unavailable, inspect the upstream, commit scoped changes, fetch, rebase only unpublished commits, verify the integrated result, then push normally.
2. Always verify AFTER upstream integration and BEFORE push. An earlier build does not verify newly integrated changes. Preserve upstream changes, resolve conflicts semantically, and never force-push without separate explicit authorization. If push is rejected, fetch/rebase, reverify, and retry once; on a further rejection stop publication and report it.
3. Record the final commit hash after rebase and confirm the push succeeded. If the client times out or loses the response, first read the target remote branch to establish whether it contains the intended commit; do not assume failure or blindly retry. If publication remains uncertain, stop status writes and report it. Only published fixes are eligible for resolution by default. The sole unpublished-handoff exception requires an explicit user instruction, completed verification, and a note clearly stating the delivery method and that no push was confirmed. Re-read each current bug before writing; do not overwrite a concurrent closure, reassignment, or conflicting resolution. Skip an already correctly resolved bug without adding duplicate history.
4. Select resolution `已解决` (`fixed` where confirmed by the actual form), not merely status `resolved`. Select the existing build corresponding to the delivered fix. Never reuse a build ID from another project or create a new build without the user's direction. Preserve the form's normal assignee unless the user specifies otherwise.
5. Add a concise resolution note containing cause/fix, tested scenarios and result, final pushed commit/branch, and relevant limits. Save and then read the persisted detail page to verify product, bug ID, status, resolution, build, and note. Use the uncertain-save procedure in the browser reference if the response is lost.

## Handoff

Report fixed and verified IDs separately from pending or blocked ones, final pushed commits/branch, checks and limitations, and actual ZenTao updates. Distinguish code completion, publication, and status persistence; none implies the others. Mention material test-data cleanup or state left on a shared device.

Do not close bugs as accepted by QA, change unrelated fields, publish releases, or keep polling indefinitely unless separately requested.
