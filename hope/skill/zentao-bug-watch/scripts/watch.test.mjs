import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { eligible, fingerprint, externalChanges, observe, nextBug, finishJob, validateResult,
    writeJson, readJson, acquireLock } from "./core.mjs";
import { WatchRunner, blankState } from "./watch.mjs";
import { git, workspaceProblem, verifyPublished } from "./clients.mjs";

const config = { product: 12, project: 34, account: "developer", realname: "Developer",
    branch: "main", threadId: "test-thread", intervalSeconds: 30, mode: "production", publish: true };
const commit = "1234567890abcdef1234567890abcdef12345678";

function bug(overrides = {}) {
    return { id: 101, product: 12, project: 34, assignedTo: "developer", status: "active",
        title: "Example", steps: "Reproduce", openedBy: "tester", openedBuild: "7", pri: 3,
        actions: [{ id: 1, actor: "tester", action: "opened", comment: "" }], ...overrides };
}

function jobFor(detail) {
    return { runId: "one-run", marker: "[zentao-watch:one-run]", bugId: detail.id,
        revision: fingerprint(detail), externalRevision: externalChanges(detail, config) };
}

function fixed(job) {
    return { runId: job.runId, bugId: job.bugId, outcome: "fixed", summary: "Reproduced and repaired",
        commit, resolvedBuild: "8", verification: "Physical device regression passed" };
}

function resolved(job) {
    return bug({ status: "resolved", resolution: "fixed", resolvedBuild: "8", assignedTo: "tester",
        actions: [{ id: 1, actor: "tester", action: "opened", comment: "" },
            { id: 2, actor: "Developer", action: "resolved", comment: `${job.marker} ${commit}` }] });
}

async function directory(t) {
    const dir = await mkdtemp(path.join(tmpdir(), "zentao-watch-test-"));
    t.after(() => rm(dir, { recursive: true, force: true }));
    return dir;
}

test("scope excludes deleted, reassigned, resolved and other project bugs", () => {
    assert.ok(eligible(bug({ assignedTo: { account: "developer" } }), config));
    for (const change of [{ product: 13 }, { project: 35 }, { assignedTo: "tester" },
        { status: "resolved" }, { deleted: true }, { deleted: 1 }, { deleted: "1" }]) {
        assert.equal(eligible(bug(change), config), false);
    }
});

test("initial backlog and new comments are queued; unchanged snapshots stay deduplicated", () => {
    const state = blankState();
    const detail = bug();
    observe(state, [detail], config);
    assert.equal(nextBug(state).id, 101);
    state.bugs[101].handledRevision = state.bugs[101].revision;
    observe(state, [detail], config);
    assert.equal(nextBug(state), null);
    const commented = bug({ actions: [...detail.actions, { id: 2, actor: "tester", action: "commented", comment: "New steps" }] });
    observe(state, [commented], config);
    assert.equal(nextBug(state).id, 101); // lastEditedDate did not change.
    observe(state, [], config);
    assert.equal(nextBug(state), null);
});

test("queue respects severity/priority and does not dispatch while busy or paused", () => {
    const state = blankState();
    observe(state, [bug(), bug({ id: 102, severity: 1 }), bug({ id: 103, severity: 1, pri: 1 })], config);
    assert.equal(nextBug(state).id, 103);
    state.inFlight = {};
    assert.equal(nextBug(state), null);
    state.inFlight = null;
    state.paused = "User paused";
    assert.equal(nextBug(state), null);
});

test("own writes are the completion baseline, while QA information arriving during work stays queued", () => {
    const initial = bug();
    const job = jobFor(initial);
    const state = blankState();
    observe(state, [initial], config);
    const ownWrite = bug({ steps: "Reproduce + SDK diagnosis", actions: [...initial.actions,
        { id: 2, actor: "Developer", action: "edited", comment: "SDK deferral" }] });
    finishJob(state, job, { outcome: "sdk-deferred", summary: "SDK required" }, ownWrite, config);
    observe(state, [ownWrite], config);
    assert.equal(nextBug(state), null);
    const concurrent = bug({ actions: [...initial.actions,
        { id: 2, actor: "tester", action: "commented", comment: "Additional log" }] });
    finishJob(state, job, { outcome: "blocked", summary: "Waiting" }, concurrent, config);
    assert.equal(nextBug(state).id, 101);
});

test("fixed outcomes require actual build, QA assignment, marked action and verification", () => {
    const job = jobFor(bug());
    assert.doesNotThrow(() => validateResult(fixed(job), job, resolved(job), config));
    const invalidResults = [{ runId: "another" }, { bugId: 999 }, { commit: "short" },
        { verification: "" }, { resolvedBuild: "9" }, { summary: "" }];
    for (const change of invalidResults) assert.throws(() => validateResult({ ...fixed(job), ...change }, job, resolved(job), config));
    for (const change of [{ status: "active" }, { resolution: "wontfix" }, { assignedTo: "developer" },
        { actions: [] }, { product: 99 }]) assert.throws(() => validateResult(fixed(job), job, { ...resolved(job), ...change }, config));
    assert.throws(() => validateResult(fixed(job), job, resolved(job), { ...config, publish: false }));
});

test("clarification must persist and return to QA; smoke cannot masquerade as a production result", () => {
    const job = jobFor(bug());
    const result = { runId: job.runId, bugId: 101, summary: "Need device log", outcome: "needs-info" };
    assert.throws(() => validateResult(result, job, bug(), config));
    assert.doesNotThrow(() => validateResult(result, job, bug({ assignedTo: "tester", steps: job.marker }), config));
    assert.throws(() => validateResult({ ...result, outcome: "smoke-tested" }, job, null, config));
    assert.doesNotThrow(() => validateResult({ ...result, outcome: "smoke-tested" }, job, null, { ...config, mode: "smoke" }));
    assert.throws(() => validateResult({ ...result, outcome: "skipped" }, job, bug(), config));
});

async function harness(t, overrides = {}) {
    const dir = await directory(t);
    const conf = { ...config, repo: dir, ...overrides };
    const details = new Map([[101, bug()]]);
    let threadType = "idle";
    let history = null;
    let lostResponse = false;
    let workspaceIssue = null;
    let published = true;
    const calls = [];
    const codex = {
        turns: new Map(),
        async connect() {},
        async readThread() { return { id: conf.threadId, cwd: dir, status: { type: threadType } }; },
        async findTurn() { return history; },
        async call(method, params) {
            calls.push({ method, params });
            if (method === "turn/start") {
                threadType = "active";
                history = { id: "turn-1", status: "inProgress" };
                if (lostResponse) throw new Error("Lost response");
                return { turn: history };
            }
            if (method === "thread/resume") threadType = "idle";
            if (method === "turn/interrupt") {
                history.status = "interrupted";
                threadType = "idle";
                codex.turns.set(history.id, history);
            }
            return {};
        },
        close() {},
    };
    const dependencies = { codex, zentao: {
        async connect() {},
        async scan() { return [...details.values()]; },
        async bug(id) { return details.get(id); },
        async close() {},
    }, async checkWorkspace() { return workspaceIssue; },
    async checkPublished() { if (!published) throw new Error("Commit not published"); } };
    const runner = new WatchRunner(conf, dir, dependencies);
    runner.state.enabled = true;
    return { runner, conf, dir, codex, dependencies, calls, details,
        busy(value) { threadType = value ? "active" : "idle"; },
        loseResponse() { lostResponse = true; },
        dirty(value) { workspaceIssue = value; },
        unpublished() { published = false; },
        absentTurn() { history = null; threadType = "idle"; },
        complete(status = "completed") {
            threadType = "idle";
            history = { id: "turn-1", status };
            codex.turns.set(history.id, history);
        },
    };
}

test("busy and dirty workspaces retain pending work without starting a turn", async t => {
    const h = await harness(t);
    h.busy(true);
    await h.runner.tick();
    assert.equal(h.calls.length, 0);
    assert.equal(nextBug(h.runner.state).id, 101);
    h.busy(false);
    h.dirty("User changes");
    await h.runner.tick();
    assert.equal(h.calls.length, 0);
    h.dirty(null);
    await h.runner.tick();
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
    assert.equal(h.calls.at(-1).params.threadId, config.threadId);
    assert.deepEqual(Object.keys(h.calls.at(-1).params).sort(), ["input", "threadId"]);
    assert.ok(h.calls.at(-1).params.input[0].text.includes(h.runner.state.inFlight.marker));
});

test("a changed thread directory is rejected before dispatch", async t => {
    const h = await harness(t);
    h.codex.readThread = async () => ({ cwd: path.dirname(h.dir), status: { type: "idle" } });
    await assert.rejects(h.runner.tick(), /working directory/);
    assert.equal(h.calls.length, 0);
});

test("lost start response and monitor restart recover the original turn without a duplicate", async t => {
    const h = await harness(t);
    h.loseResponse();
    await h.runner.tick();
    const job = h.runner.state.inFlight;
    assert.equal(job.phase, "uncertain");
    await writeJson(job.resultFile, { runId: job.runId, bugId: 101, outcome: "sdk-deferred", summary: "SDK owns this behavior" });
    h.complete();
    const restarted = new WatchRunner(h.conf, h.dir, h.dependencies);
    await restarted.load();
    await restarted.tick();
    assert.equal(restarted.state.inFlight, null);
    assert.equal(restarted.state.lastResult.outcome, "sdk-deferred");
    restarted.lastPoll = 0;
    await restarted.tick();
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
});

test("an uncertain request is never resent automatically; explicit retry first reads history", async t => {
    const h = await harness(t);
    h.loseResponse();
    await h.runner.tick();
    h.absentTurn();
    await h.runner.tick();
    await h.runner.tick();
    assert.ok(h.runner.state.paused);
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
    await writeJson(path.join(h.dir, "commands", "retry.json"), { type: "retry", bugId: 101 });
    await h.runner.tick();
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 2);
});

test("a fixed claim remains in flight until remote publication is independently verified", async t => {
    const h = await harness(t);
    await h.runner.tick();
    const job = h.runner.state.inFlight;
    await writeJson(job.resultFile, fixed(job));
    h.details.set(101, resolved(job));
    h.unpublished();
    h.complete();
    await assert.rejects(h.runner.tick(), /not published/);
    assert.equal(h.runner.state.inFlight.runId, job.runId);
    assert.equal(h.runner.state.lastResult, undefined);
});

test("verified resolution settles once and the next independent bug gets a new job", async t => {
    const h = await harness(t);
    h.details.set(102, bug({ id: 102 }));
    await h.runner.tick();
    const first = h.runner.state.inFlight;
    await writeJson(first.resultFile, fixed(first));
    h.details.set(101, resolved(first));
    h.complete();
    await h.runner.tick();
    assert.equal(h.runner.state.lastResult.outcome, "fixed");
    assert.equal(h.runner.state.inFlight.bugId, 102);
    assert.notEqual(h.runner.state.inFlight.runId, first.runId);
    assert.equal((await readJson(path.join(h.dir, "jobs", first.runId, "verified.json"))).commit, commit);
});

test("interrupted or completed-without-result jobs do not loop on the same revision", async t => {
    for (const status of ["interrupted", "completed"]) {
        const h = await harness(t);
        h.details.set(102, bug({ id: 102 }));
        await h.runner.tick();
        h.runner.state.inFlight.waitingForResultSince = Date.now() - 31_000;
        h.complete(status);
        await h.runner.tick();
        assert.equal(h.runner.state.lastResult.outcome, "blocked");
        assert.ok(h.runner.state.paused);
        assert.equal(h.runner.state.inFlight, null);
        await h.runner.tick();
        assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
    }
});

test("daemon unavailability preserves the queue for a later connection", async t => {
    const h = await harness(t);
    h.busy(true);
    await h.runner.tick();
    h.codex.connect = async () => { throw new Error("Daemon unavailable"); };
    await assert.rejects(h.runner.tick(), /Daemon unavailable/);
    assert.equal(h.calls.length, 0);
    const restored = new WatchRunner(h.conf, h.dir, h.dependencies);
    await restored.load();
    assert.equal(nextBug(restored.state).id, 101);
    h.codex.connect = async () => {};
    h.busy(false);
    await restored.tick();
    assert.equal(restored.state.inFlight.bugId, 101);
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
});

test("stop drains only the current job and does not dispatch the queued bug", async t => {
    const h = await harness(t);
    h.details.set(102, bug({ id: 102 }));
    await h.runner.tick();
    const job = h.runner.state.inFlight;
    await writeJson(path.join(h.dir, "commands", "stop.json"), { type: "stop" });
    await h.runner.tick();
    assert.equal(h.runner.state.enabled, false);
    assert.equal(h.calls.filter(call => call.method === "turn/interrupt").length, 0);
    await writeJson(job.resultFile, { runId: job.runId, bugId: 101, outcome: "sdk-deferred", summary: "SDK change needed" });
    h.complete();
    await h.runner.tick();
    assert.equal(h.runner.state.inFlight, null);
    assert.equal(nextBug(h.runner.state).id, 102);
    assert.equal(h.calls.filter(call => call.method === "turn/start").length, 1);
});

test("explicit cancel interrupts the original watched turn, including a lost acknowledgement", async t => {
    const h = await harness(t);
    h.loseResponse();
    await h.runner.tick();
    await writeJson(path.join(h.dir, "commands", "stop.json"), { type: "stop", cancelCurrent: true });
    await h.runner.tick();
    assert.deepEqual(h.calls.find(call => call.method === "turn/interrupt").params,
        { threadId: config.threadId, turnId: "turn-1" });
    assert.equal(h.runner.state.lastResult.outcome, "blocked");
});

test("repository lock prevents two watchers and releases only its own token", async t => {
    const dir = await directory(t);
    const lockFile = path.join(dir, "repository.lock");
    const release = await acquireLock(lockFile);
    await assert.rejects(acquireLock(lockFile), /already owns/);
    await release();
    const again = await acquireLock(lockFile);
    await again();
    assert.equal(await readJson(lockFile, null), null);
});

test("Git publication verification distinguishes a real upstream commit from a local-only commit", async t => {
    const dir = await directory(t);
    const repo = path.join(dir, "work");
    const remote = path.join(dir, "remote.git");
    await git(dir, "init", "--bare", remote);
    await git(dir, "init", "--initial-branch=main", repo);
    await git(repo, "-c", "user.name=Watch Test", "-c", "user.email=watch@example.invalid", "commit", "--allow-empty", "-m", "initial");
    await git(repo, "remote", "add", "origin", remote);
    await git(repo, "push", "--set-upstream", "origin", "main");
    const conf = { ...config, repo, remote: "origin", remoteRef: "refs/heads/main" };
    const published = await git(repo, "rev-parse", "HEAD");
    await verifyPublished(conf, published);
    assert.equal(await workspaceProblem(conf), null);
    await git(repo, "-c", "user.name=Watch Test", "-c", "user.email=watch@example.invalid", "commit", "--allow-empty", "-m", "unpublished");
    const localOnly = await git(repo, "rev-parse", "HEAD");
    await assert.rejects(verifyPublished(conf, localOnly));
    assert.match(await workspaceProblem(conf), /Unpublished/);
    await writeJson(path.join(repo, "user-changes.json"), { preserve: true });
    assert.match(await workspaceProblem(conf), /Uncommitted/);
});
