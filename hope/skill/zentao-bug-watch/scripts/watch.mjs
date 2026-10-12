import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, realpath, readdir, unlink, open, access } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { hash, account, eligible, fingerprint, externalChanges, observe, nextBug, finishJob,
    validateResult, readJson, writeJson, processAlive, acquireLock } from "./core.mjs";
import { CodexClient, ZenTaoClient, git, workspaceProblem, verifyPublished } from "./clients.mjs";

const scriptFile = fileURLToPath(import.meta.url);
const skillFile = path.resolve(path.dirname(scriptFile), "../SKILL.md");

export function blankState() {
    return { version: 1, enabled: false, bugs: {}, inFlight: null, paused: null };
}

export function samePath(left, right) {
    if (!left || !right) return false;
    const normalize = value => process.platform === "win32" ? path.resolve(value).toLowerCase() : path.resolve(value);
    return normalize(left) === normalize(right);
}

export class WatchRunner {
    constructor(config, directory, dependencies = {}) {
        this.config = config;
        this.directory = directory;
        this.codex = dependencies.codex ?? new CodexClient(config);
        this.zentao = dependencies.zentao ?? new ZenTaoClient(config);
        this.checkWorkspace = dependencies.checkWorkspace ?? workspaceProblem;
        this.checkPublished = dependencies.checkPublished ?? verifyPublished;
        this.state = blankState();
        this.lastPoll = 0;
        this.cancelCurrent = false;
    }

    async load() {
        this.state = await readJson(path.join(this.directory, "state.json"), blankState());
        if (this.state.version !== 1) throw new Error("Unsupported monitor state version");
    }

    async save() {
        this.state.pid = process.pid;
        this.state.heartbeat = new Date().toISOString();
        await writeJson(path.join(this.directory, "state.json"), this.state);
    }

    async commands() {
        const directory = path.join(this.directory, "commands");
        await mkdir(directory, { recursive: true });
        for (const name of (await readdir(directory)).filter(name => name.endsWith(".json")).sort()) {
            const file = path.join(directory, name);
            const command = await readJson(file);
            if (command.type === "stop") {
                this.state.enabled = false;
                this.cancelCurrent ||= command.cancelCurrent === true;
            } else if (command.type === "retry") {
                if (this.state.inFlight) {
                    if (this.state.inFlight.phase === "uncertain" && command.bugId === this.state.inFlight.bugId) {
                        this.state.inFlight.manualRetry = true;
                    } else {
                        this.state.message = "Retry postponed: an existing job must be reconciled first";
                        continue;
                    }
                }
                const row = this.state.bugs[String(command.bugId)];
                if (row) row.handledRevision = null;
                this.state.paused = null;
                this.lastPoll = 0;
            }
            await this.save();
            await unlink(file);
        }
    }

    async scan() {
        await this.zentao.connect();
        const bugs = await this.zentao.scan();
        observe(this.state, bugs, this.config);
        this.lastPoll = Date.now();
        await this.save();
    }

    async settle(job, result, bug) {
        finishJob(this.state, job, result, bug, this.config);
        if (result.pauseMonitor) this.state.paused = result.summary;
        await writeJson(path.join(this.directory, "jobs", job.runId, "verified.json"), this.state.lastResult);
        await this.save();
    }

    async reconcile(thread) {
        const job = this.state.inFlight;
        if (this.cancelCurrent && !job.turnId) {
            const original = await this.codex.findTurn(job);
            if (original) job.turnId = original.id;
        }
        if (this.cancelCurrent && job.turnId) {
            // Only interrupt the exact turn this watcher started, never the user's next turn.
            await this.codex.call("turn/interrupt", { threadId: this.config.threadId, turnId: job.turnId });
            this.cancelCurrent = false;
        }
        const completed = job.turnId && this.codex.turns.get(job.turnId);
        if (!completed && thread.status.type === "active") {
            this.state.message = `Bug ${job.bugId}: Codex active (${thread.status.activeFlags?.join(", ") || "working"})`;
            return;
        }
        const turn = completed || await this.codex.findTurn(job);
        if (!turn) {
            if (job.manualRetry && ["idle", "notLoaded"].includes(thread.status.type)) {
                // Only an explicit retry plus a fresh history read can abandon an unacknowledged request.
                await this.settle(job, { outcome: "blocked", summary: "Manual retry: original turn absent from the idle thread history" }, await this.zentao.bug(job.bugId));
                this.state.bugs[String(job.bugId)].handledRevision = null;
                this.state.paused = null;
                return;
            }
            job.phase = "uncertain";
            this.state.paused = `Cannot confirm turn/start for ${job.marker}; no automatic duplicate dispatch`;
            this.state.message = this.state.paused;
            return;
        }
        job.turnId = turn.id;
        job.phase = "running";
        if (turn.status === "inProgress") return;
        const bug = await this.zentao.bug(job.bugId);
        if (turn.status !== "completed") {
            await this.settle(job, { outcome: "blocked", pauseMonitor: true,
                summary: `Codex turn ${turn.status}; inspect its work before retry` }, bug);
            return;
        }
        const result = await readJson(job.resultFile, null);
        if (!result) {
            job.waitingForResultSince ??= Date.now();
            if (Date.now() - job.waitingForResultSince < 30_000) return;
            await this.settle(job, { outcome: "blocked", pauseMonitor: true,
                summary: "Completed Codex turn did not provide its structured result; inspect mode and work before retry" }, bug);
            return;
        }
        try { validateResult(result, job, bug, this.config); }
        catch (error) {
            await this.settle(job, { outcome: "blocked", summary: `Result verification failed: ${error.message}` }, bug);
            return;
        }
        if (result.outcome === "fixed") await this.checkPublished(this.config, result.commit);
        await this.settle(job, result, bug);
        this.state.message = `Bug ${job.bugId}: ${result.outcome}`;
    }

    async dispatch(row) {
        const bug = await this.zentao.bug(row.id);
        if (!eligible(bug, this.config)) { row.eligible = false; return; }
        row.revision = fingerprint(bug);
        row.externalRevision = externalChanges(bug, this.config);
        const runId = randomUUID();
        const jobDirectory = path.join(this.directory, "jobs", runId);
        const job = {
            version: 1, runId, marker: `[zentao-watch:${runId}]`, bugId: row.id,
            revision: row.revision, externalRevision: row.externalRevision,
            createdAt: new Date().toISOString(), phase: "dispatching", turnId: null,
            repo: this.config.repo, branch: this.config.branch, threadId: this.config.threadId,
            product: this.config.product, project: this.config.project, account: this.config.account,
            qaAccount: this.config.qaAccount ?? null, baseUrl: this.config.baseUrl,
            sdkChanges: false, publish: this.config.publish,
            mode: this.config.mode, resultFile: path.join(jobDirectory, "result.json"),
            ...(this.config.mode === "smoke" ? { fixture: true } : {}),
        };
        const inputFile = path.join(jobDirectory, "input.json");
        await writeJson(inputFile, job);
        this.state.inFlight = job;
        // Persist the intent before the RPC: a crash/lost response is reconciled by marker.
        await this.save();
        const prompt = `${job.marker}\nUse $zentao-bug-watch in worker mode. Read ${JSON.stringify(skillFile)} and the job ${JSON.stringify(inputFile)}. Process only this job and write its result file. Do not start another monitor. Existing user restrictions and Plan mode still apply.`;
        try {
            const response = await this.codex.call("turn/start", {
                threadId: this.config.threadId,
                input: [{ type: "text", text: prompt }, { type: "skill", name: "zentao-bug-watch", path: skillFile }],
            });
            job.turnId = response.turn.id;
            job.phase = "running";
            this.state.message = `Dispatched bug ${job.bugId} to existing thread`;
        } catch (error) {
            job.phase = "uncertain";
            this.state.message = `Dispatch requires reconciliation: ${error.message}`;
        }
        await this.save();
    }

    async tick() {
        await this.commands();
        if (!this.state.enabled && !this.state.inFlight) return;
        await this.zentao.connect();
        await this.codex.connect();
        const thread = await this.codex.readThread();
        if (!samePath(thread.cwd, this.config.repo)) throw new Error("Bound Codex thread changed working directory");
        if (this.state.inFlight) await this.reconcile(thread);
        if (this.state.enabled && Date.now() - this.lastPoll >= this.config.intervalSeconds * 1000) await this.scan();
        if (this.state.enabled && !this.state.inFlight && !this.state.paused) {
            const row = nextBug(this.state);
            if (row && thread.status.type !== "active") {
                const problem = await this.checkWorkspace(this.config);
                if (problem) this.state.message = problem;
                else if (["idle", "notLoaded"].includes(thread.status.type)) {
                    // Resume subscribes this connection to turn notifications. No model/mode/permission overrides.
                    await this.codex.call("thread/resume", { threadId: this.config.threadId });
                    const current = await this.codex.readThread();
                    if (current.status.type === "idle") await this.dispatch(row);
                }
            } else if (row) this.state.message = "Existing thread is busy; pending bugs are retained";
            else this.state.message = "Watching; no unhandled revisions";
        }
        await this.save();
    }

    async run() {
        const release = await acquireLock(this.config.lockFile);
        let stopRequested = false;
        const stop = () => { stopRequested = true; this.state.enabled = false; };
        process.on("SIGINT", stop);
        process.on("SIGTERM", stop);
        try {
            await this.load();
            this.state.enabled = true;
            this.state.paused = null;
            await this.save();
            while (this.state.enabled || this.state.inFlight) {
                if (stopRequested) this.state.enabled = false;
                try {
                    await this.tick();
                    this.state.error = null;
                    if (!this.state.enabled && this.state.inFlight?.phase === "uncertain") break;
                } catch (error) {
                    this.state.error = error.message.split("\n")[0].slice(0,500);
                    await this.save();
                    this.codex.close();
                    await this.zentao.close();
                    // Keep servicing stop commands during the retry delay.
                    for (let i = 0; i < 15; i++) {
                        await delay(2000);
                        await this.commands();
                        if (!this.state.enabled && !this.state.inFlight) break;
                    }
                }
                if (!this.state.enabled && !this.state.inFlight) break;
                await delay(2000);
            }
        } finally {
            this.state.enabled = false;
            this.state.pid = null;
            this.state.stoppedAt = new Date().toISOString();
            await writeJson(path.join(this.directory, "state.json"), this.state);
            this.codex.close();
            await this.zentao.close();
            await release();
            process.off("SIGINT", stop);
            process.off("SIGTERM", stop);
        }
    }
}

async function initialize(values) {
    const repo = await realpath(await git(path.resolve(values.repo ?? process.cwd()), "rev-parse", "--show-toplevel"));
    const product = Number(values.product), project = Number(values.project);
    const threadId = values.thread ?? process.env.CODEX_THREAD_ID;
    if (!Number.isInteger(product) || product <= 0 || !Number.isInteger(project) || project <= 0 || !values.account || !threadId) {
        throw new Error("init requires --product, --project, --account and the exact --thread (or CODEX_THREAD_ID)");
    }
    const branch = await git(repo, "branch", "--show-current");
    if (!branch) throw new Error("Detached HEAD is not an automatic repair target");
    const root = path.resolve(values["state-root"] ?? path.join(process.env.LOCALAPPDATA ?? homedir(), "Hope", "zentao-bug-watch"));
    const repoKey = hash(process.platform === "win32" ? repo.toLowerCase() : repo).slice(0, 20);
    const profile = path.join(root, `${repoKey}-${product}-${project}`);
    const configFile = path.join(profile, "config.json");
    try { await access(configFile); throw new Error(`Profile already exists; inspect ${configFile} instead of replacing it`); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    const config = {
        version: 1, mode: "production", repo, branch, product, project, account: values.account,
        threadId, intervalSeconds: Number(values.interval ?? 300), publish: !values["no-push"],
        baseUrl: values["base-url"] ?? "http://zentao.hopemobi.com/zentao",
        mcpDir: path.resolve(values["mcp-dir"] ?? path.join(homedir(), ".codex", "mcp", "zentao-v1")),
        codex: values.codex ?? "codex.exe",
        socket: path.resolve(values.socket ?? path.join(homedir(), ".codex", "app-server-control", "app-server-control.sock")),
        lockFile: path.join(root, `${repoKey}.lock`),
        remote: await git(repo, "config", "--get", `branch.${branch}.remote`),
        remoteRef: await git(repo, "config", "--get", `branch.${branch}.merge`),
        ...(values["qa-account"] ? { qaAccount: values["qa-account"] } : {}),
    };
    if (!Number.isFinite(config.intervalSeconds) || config.intervalSeconds < 30) throw new Error("Minimum polling interval is 30 seconds");
    if (!config.remote || config.remote === "." || !config.remoteRef.startsWith("refs/heads/")) throw new Error("A published upstream branch is required");
    const zentao = new ZenTaoClient(config);
    const codex = new CodexClient(config);
    try {
        await zentao.connect();
        const user = await zentao.read("/user");
        const identity = user.profile ?? user.user ?? user;
        if (identity.account !== config.account) throw new Error("Configured account differs from authenticated ZenTao account");
        config.realname = identity.realname;
        await zentao.read(`/products/${product}`);
        await zentao.read(`/projects/${project}`);
        await codex.connect();
        const thread = await codex.readThread();
        if (!samePath(thread.cwd, repo)) throw new Error("Codex thread does not belong to this repository");
        await writeJson(configFile, config);
        await writeJson(path.join(profile, "state.json"), blankState());
        console.log(JSON.stringify({ profile, enabled: false, threadId }));
    } finally { codex.close(); await zentao.close(); }
}

async function main() {
    const { values, positionals } = parseArgs({ allowPositionals: true, options: {
        repo: { type: "string" }, product: { type: "string" }, project: { type: "string" }, account: { type: "string" },
        thread: { type: "string" }, profile: { type: "string" }, interval: { type: "string" },
        "state-root": { type: "string" }, "base-url": { type: "string" }, "mcp-dir": { type: "string" },
        codex: { type: "string" }, socket: { type: "string" }, "qa-account": { type: "string" },
        "no-push": { type: "boolean" }, "cancel-current": { type: "boolean" }, bug: { type: "string" },
    } });
    const command = positionals[0];
    if (!command || command === "help") {
        console.log("init --repo PATH --product ID --project ID --account ACCOUNT [--thread ID]\nstart|status|stop|retry|doctor|check --profile PATH\nstop [--cancel-current]; retry --bug ID. check never starts Codex or writes ZenTao.");
        return;
    }
    if (command === "init") return initialize(values);
    if (!values.profile) throw new Error("Specify the exact --profile directory returned by init");
    const directory = await realpath(values.profile);
    const config = await readJson(path.join(directory, "config.json"));
    if (config.version !== 1) throw new Error("Unsupported profile version");
    const stateFile = path.join(directory, "state.json");
    const owner = await readJson(config.lockFile, {});
    const running = Number.isInteger(owner.pid) && owner.pid > 0 && processAlive(owner.pid);
    if (command === "status") {
        console.log(JSON.stringify({ profile: directory, running, ...(await readJson(stateFile)),
            configuration: { repo: config.repo, branch: config.branch, threadId: config.threadId, intervalSeconds: config.intervalSeconds } }, null, 2));
        return;
    }
    if (command === "start") {
        if (running) throw new Error("A watcher already owns this repository");
        const log = await open(path.join(directory, "watch.log"), "a", 0o600);
        const child = spawn(process.execPath, [scriptFile, "run", "--profile", directory], {
            detached: true, windowsHide: true, stdio: ["ignore", log.fd, log.fd], cwd: config.repo,
        });
        let spawnError;
        child.once("error", error => { spawnError = error; });
        child.unref();
        await log.close();
        for (let i = 0; i < 30; i++) {
            if (spawnError) throw spawnError;
            const state = await readJson(stateFile);
            if (state.pid === child.pid && state.enabled) { console.log(JSON.stringify({ running: true, pid: child.pid, profile: directory })); return; }
            if (!processAlive(child.pid)) throw new Error("Watcher exited during startup; inspect watch.log");
            await delay(200);
        }
        throw new Error("Watcher startup unconfirmed; inspect status before retrying");
    }
    if (command === "run") return new WatchRunner(config, directory).run();
    if (command === "stop" || command === "retry") {
        if (command === "retry" && (!Number.isInteger(Number(values.bug)) || Number(values.bug) <= 0)) throw new Error("retry requires --bug ID");
        if (!running && command === "stop") { console.log("Monitor is already stopped; no Codex turn interrupted"); return; }
        await writeJson(path.join(directory, "commands", `${Date.now()}-${randomUUID()}.json`), {
            type: command, bugId: Number(values.bug), cancelCurrent: !!values["cancel-current"],
        });
        console.log(command === "stop" ? "Stop requested; no further dispatch. Existing work will drain unless --cancel-current was specified."
            : "Retry queued; start the monitor if it is stopped.");
        return;
    }
    if (!["doctor", "check"].includes(command)) throw new Error(`Unknown command: ${command}`);
    const runner = new WatchRunner(config, directory);
    try {
        await runner.zentao.connect();
        const user = await runner.zentao.read("/user");
        if ((user.profile ?? user.user ?? user).account !== config.account) throw new Error("ZenTao authenticated account changed");
        await runner.codex.connect();
        const thread = await runner.codex.readThread();
        if (!samePath(thread.cwd, config.repo)) throw new Error("Bound thread working directory changed");
        const info = { connected: true, threadId: thread.id, threadStatus: thread.status,
            workspaceProblem: await workspaceProblem(config), monitorRunning: running };
        if (command === "check") info.eligibleBugIds = (await runner.zentao.scan()).map(bug => bug.id);
        console.log(JSON.stringify(info, null, 2));
    } finally { runner.codex.close(); await runner.zentao.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
    main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
