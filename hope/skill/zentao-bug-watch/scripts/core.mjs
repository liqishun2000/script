import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile, open, unlink } from "node:fs/promises";
import path from "node:path";

export function hash(value) {
    return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function account(value) {
    return typeof value === "object" && value ? value.account ?? value.realname ?? "" : value ?? "";
}

export function eligible(bug, config) {
    return Number(bug.product) === config.product && Number(bug.project) === config.project
        && ![true, 1, "1"].includes(bug.deleted) && bug.status === "active"
        && account(bug.assignedTo) === config.account;
}

export function fingerprint(bug) {
    return hash([bug.id, bug.title, bug.steps, bug.status, account(bug.assignedTo), bug.activatedCount,
        bug.files, bug.actions?.map(action => [action.id, action.action, action.comment, action.history])]);
}

export function externalChanges(bug, config) {
    // API detail returns some actors as display names, others as account objects.
    const own = new Set([config.account, config.realname].filter(Boolean));
    return hash(bug.actions?.filter(action => !own.has(account(action.actor)))
        .map(action => [action.id, action.action, action.comment, action.history]) ?? []);
}

export function observe(state, bugs, config) {
    const present = new Set();
    for (const bug of bugs) {
        if (!eligible(bug, config)) continue;
        const id = String(bug.id);
        present.add(id);
        const previous = state.bugs[id] ?? {};
        const revision = fingerprint(bug);
        state.bugs[id] = {
            ...previous, id: Number(bug.id), title: bug.title, revision,
            externalRevision: externalChanges(bug, config), eligible: true,
            priority: Number(bug.pri) || 3, severity: Number(bug.severity) || 3,
            openedDate: bug.openedDate ?? "", observedAt: new Date().toISOString(),
        };
    }
    for (const [id, row] of Object.entries(state.bugs)) row.eligible = present.has(id);
    state.checkedAt = new Date().toISOString();
}

export function nextBug(state) {
    if (state.inFlight || state.paused) return null;
    return Object.values(state.bugs).filter(row => row.eligible && row.revision !== row.handledRevision)
        .sort((a, b) => a.severity - b.severity || a.priority - b.priority
            || a.openedDate.localeCompare(b.openedDate) || a.id - b.id)[0] ?? null;
}

export function finishJob(state, job, result, currentBug, config) {
    const row = state.bugs[String(job.bugId)];
    const revision = currentBug ? fingerprint(currentBug) : job.revision;
    const newExternalInformation = currentBug && externalChanges(currentBug, config) !== job.externalRevision;
    row.handledRevision = newExternalInformation && eligible(currentBug, config) ? job.revision : revision;
    row.revision = revision;
    row.eligible = !!currentBug && eligible(currentBug, config);
    row.outcome = result.outcome;
    row.summary = result.summary;
    row.commit = result.commit ?? null;
    row.finishedAt = new Date().toISOString();
    row.lastRunId = job.runId;
    state.lastResult = { bugId: job.bugId, runId: job.runId, ...result, finishedAt: row.finishedAt };
    state.inFlight = null;
}

export function validateResult(result, job, bug, config) {
    if (result.runId !== job.runId || Number(result.bugId) !== job.bugId) throw new Error("Result/job identity mismatch");
    if (!result.summary?.trim()) throw new Error("Result requires an evidence summary");
    if (!["fixed", "needs-info", "sdk-deferred", "blocked", "skipped", "smoke-tested"].includes(result.outcome)) {
        throw new Error("Unknown result outcome");
    }
    if (result.outcome === "smoke-tested") {
        if (config.mode !== "smoke") throw new Error("Smoke outcome rejected in production");
        return;
    }
    if (!bug || Number(bug.id) !== job.bugId || Number(bug.product) !== config.product
        || Number(bug.project) !== config.project) throw new Error("Fresh ZenTao detail is outside the configured scope");
    if (result.outcome === "fixed") {
        if (!config.publish) throw new Error("Publishing/resolution is disabled for this profile");
        if (!/^[a-f0-9]{40}$/i.test(result.commit ?? "")) throw new Error("Fixed result requires a full commit hash");
        if (!result.verification?.trim()) throw new Error("Fixed result requires verification evidence");
        if (!["resolved", "closed"].includes(bug.status) || bug.resolution !== "fixed") throw new Error("ZenTao fix did not persist");
        const build = bug.resolvedBuild?.id ?? bug.resolvedBuild;
        if (!build || String(build) !== String(result.resolvedBuild)) throw new Error("Resolved build does not match");
        if (bug.status === "resolved" && account(bug.assignedTo) !== (config.qaAccount ?? account(bug.openedBy))) {
            throw new Error("Bug was not returned to its QA owner");
        }
        if (!bug.actions?.some(action => action.action === "resolved"
            && action.comment?.includes(job.marker) && action.comment.includes(result.commit.slice(0, 7)))) {
            throw new Error("Persisted resolution lacks this job marker/commit");
        }
    }
    if (result.outcome === "needs-info") {
        if (bug.status !== "active" || account(bug.assignedTo) !== (config.qaAccount ?? account(bug.openedBy))) {
            throw new Error("Clarification request was not returned to QA as active");
        }
        if (!bug.steps?.includes(job.marker) && !bug.actions?.some(action => action.comment?.includes(job.marker))) {
            throw new Error("Clarification request was not persisted");
        }
    }
    if (result.outcome === "sdk-deferred" && bug.status !== "active") throw new Error("SDK deferral must remain unresolved");
    if (result.outcome === "skipped" && eligible(bug, config)) throw new Error("Use blocked/deferred for an eligible unfinished bug");
}

export async function readJson(file, fallback) {
    try { return JSON.parse(await readFile(file, "utf8")); }
    catch (error) { if (error.code === "ENOENT" && fallback !== undefined) return fallback; throw error; }
}

export async function writeJson(file, value) {
    await mkdir(path.dirname(file), { recursive: true });
    const temporary = `${file}.${randomUUID()}.tmp`;
    await writeFile(temporary, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 });
    await rename(temporary, file);
}

export function processAlive(pid) {
    try { process.kill(pid, 0); return true; }
    catch (error) { return error.code !== "ESRCH"; }
}

export async function acquireLock(file) {
    await mkdir(path.dirname(file), { recursive: true });
    const owner = { pid: process.pid, token: randomUUID() };
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const handle = await open(file, "wx", 0o600);
            try { await handle.writeFile(JSON.stringify(owner)); } finally { await handle.close(); }
            return async () => {
                const stored = await readJson(file, {});
                if (stored.token === owner.token) await unlink(file);
            };
        } catch (error) {
            if (error.code !== "EEXIST") throw error;
            // Never kill by a persisted PID. A malformed lock requires explicit inspection.
            const existing = await readJson(file);
            if (!Number.isInteger(existing.pid) || existing.pid <= 0 || processAlive(existing.pid)) {
                throw new Error(`Watcher already owns repository lock: ${file}`);
            }
            await unlink(file);
        }
    }
    throw new Error("Could not acquire repository lock");
}
