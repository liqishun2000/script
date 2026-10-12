// Explicitly authorized integration test only. ZenTao is an in-memory fixture.
import assert from "node:assert/strict";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir, homedir } from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { CodexClient } from "./clients.mjs";
import { WatchRunner } from "./watch.mjs";
import { nextBug, writeJson } from "./core.mjs";

const { values } = parseArgs({ options: { codex: { type: "string" }, socket: { type: "string" } } });
const directory = await mkdtemp(path.join(tmpdir(), "zentao-watch-smoke-"));
const repo = path.join(directory, "isolated-workspace");
await mkdir(repo);
const config = {
    mode: "smoke", repo, branch: "synthetic", product: 1, project: 1, account: "synthetic-worker",
    intervalSeconds: 30, publish: false,
    codex: values.codex ?? "codex.exe",
    socket: values.socket ?? path.join(homedir(), ".codex", "app-server-control", "app-server-control.sock"),
};
const codex = new CodexClient(config);
let threadId;
let runner;
let completed = false;
try {
    await codex.connect();
    // This is the only new thread created by the test. Production always resumes the bound thread.
    const response = await codex.call("thread/start", { cwd: repo });
    threadId = response.thread.id;
    config.threadId = threadId;
    await codex.call("thread/name/set", { threadId, name: "ZenTao watcher isolated smoke test" });
    let present = false;
    const fixture = { id: 1, product: 1, project: 1, assignedTo: config.account, status: "active",
        title: "Synthetic arrival; write only the structured smoke result", steps: "No real bug or repository", actions: [] };
    const zentao = {
        async connect() {},
        async scan() { return present ? [fixture] : []; },
        async bug(id) { assert.equal(id, 1); return fixture; },
        async close() {},
    };
    runner = new WatchRunner(config, path.join(repo, ".watch-state"), {
        codex, zentao, async checkWorkspace() { return null; },
        async checkPublished() { throw new Error("Smoke must not publish commits"); },
    });
    runner.state.enabled = true;
    await runner.tick();
    assert.equal(runner.state.inFlight, null);
    present = true;
    runner.lastPoll = 0;
    await runner.tick();
    assert.ok(runner.state.inFlight);
    const runId = runner.state.inFlight.runId;
    console.log(JSON.stringify({ phase: "dispatched", threadId, runId, evidence: directory }));
    const deadline = Date.now() + 240_000;
    while (runner.state.inFlight && Date.now() < deadline) {
        await delay(2000);
        await runner.tick();
    }
    assert.equal(runner.state.inFlight, null, "Synthetic turn did not finish before the test deadline");
    assert.equal(runner.state.lastResult?.outcome, "smoke-tested");
    runner.lastPoll = 0;
    await runner.tick();
    assert.equal(nextBug(runner.state), null);
    assert.equal(runner.state.lastResult.runId, runId);
    const turns = await codex.call("thread/turns/list", { threadId, limit: 25, itemsView: "notLoaded" });
    assert.equal(turns.data.length, 1, "Only one synthetic turn should be dispatched");
    assert.equal(turns.data[0].status, "completed");
    completed = true;
} catch (error) {
    console.error(JSON.stringify({ passed: false, reason: error.message, threadId, evidence: directory }));
    process.exitCode = 1;
} finally {
    if (runner) {
        runner.state.enabled = false;
        await runner.save();
    }
    if (threadId) {
        try {
            const thread = await codex.readThread();
            if (thread.status.type === "active") {
                const turn = runner?.state.inFlight && await codex.findTurn(runner.state.inFlight);
                if (turn) await codex.call("turn/interrupt", { threadId, turnId: turn.id });
            }
            await codex.call("thread/archive", { threadId });
        } catch (error) {
            console.error(`Test thread cleanup requires inspection (${threadId}): ${error.message}`);
            process.exitCode = 1;
            completed = false;
        }
    }
    codex.close();
    const result = { passed: completed, threadId, evidence: directory, realZenTaoRequests: 0,
        businessRepositoryWrites: 0, productionMonitorStarted: false };
    await writeJson(path.join(directory, "smoke-verification.json"), result);
    console.log(JSON.stringify(result));
}
