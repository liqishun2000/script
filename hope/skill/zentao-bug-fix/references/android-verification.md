# Android Bug Verification

Read this reference only for Android repositories. Derive package ID, build variant, app name, A/B mode, device serial, and build commands from the current project; do not reuse another app's values.

## Device and Build

- Inspect connected devices and select the intended serial explicitly for mutations when more than one is present. Record initial app mode, permission state, locale, and test-owned data before changing them.
- Build the intended variant using the repository wrapper and restore any build-time source transformations according to existing project tooling. Inspect the worktree after building. Do not run multiple builds over a shared generated-source workspace.
- Installing an update is preferable to clearing application data. Do not uninstall, clear all data, delete user media, or reset global device settings merely to simplify a regression test. Ask when a destructive reset is genuinely necessary.
- Use UI hierarchy inspection to locate controls and a fresh snapshot after navigation. Fixed coordinates from an earlier screen can hit a different control during transitions. Screenshots should show the actual fixed state, not a loading screen.
- Test competitors only when in scope and available; inspect their behavior without modifying their account data. They clarify the provided expectation, not a mandate to copy unrelated features.

## Choose Checks by Failure Mode

- Permission bugs: first ungranted entry, deny, no repeated prompt loop, explicit retry, grant, and affected entry visibility. Revoke/grant only the relevant permission and restore the original state afterward when feasible.
- Playback bugs: prove the error path with a test-owned invalid or unsupported file. Deleting a playing file may still use an open handle or cache. Check prompt visibility, retry, next/previous recovery, paused behavior, duration units, unknown-duration seek handling, and the queue beyond any display limit as relevant.
- Scroll/layout bugs: use enough content to reach the actual end, verify no unbounded blank region, and return to the top. Confirm that the fix did not merely disable scrolling. Check meaningful long text and both actual artwork and placeholders for visual regressions.
- Deletion dialogs: use a uniquely named test-owned item; cancel must preserve it and confirm must remove only it. Do not use an existing user item as a deletion fixture.
- Localization bugs: audit all supported resource sets for missing/duplicate keys, placeholders, hard-coded visible strings, app-name consistency, and quantity forms. Test cold restart and switching through app settings and system per-app language; stale application preferences must not override the system choice. Distinguish app-owned labels from third-party article/music metadata.
- Existing test/lint failures: identify the concrete pre-existing lines or baseline, verify no new in-scope errors, and disclose the residual result. Build success alone does not establish a behavioral fix.

## Cleanup and Evidence

Record what was tested, on which build/device, and the observed result per bug. Keep screenshots and fixtures in explicit temporary locations, not the source tree. Remove only validated, test-owned files/items and refresh media indexing if applicable. Restore mode, locale, and permissions changed for testing; if exact restoration is not safe or possible, report what remains. Do not clear a user's entire history to remove a few test entries.

Re-run risk-appropriate checks after upstream integration before pushing. If a device or required fixture is unavailable, report the verification gap and leave the affected bug unresolved rather than claiming a complete regression pass.
