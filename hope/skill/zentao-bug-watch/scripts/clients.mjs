import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import { Duplex } from "node:stream";
import path from "node:path";
import WebSocket from "ws";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { eligible } from "./core.mjs";

const exec = promisify(execFile);

export async function git(repo, ...args) {
    const result = await exec("git", ["-C", repo, ...args], { windowsHide: true, timeout: 60_000, maxBuffer: 4 * 1024 * 1024 });
    return result.stdout.trim();
}

export async function workspaceProblem(config) {
    if (await git(config.repo, "branch", "--show-current") !== config.branch) return "Repository branch changed";
    if (await git(config.repo, "status", "--porcelain")) return "Uncommitted workspace changes; waiting for the user";
    if (Number(await git(config.repo, "rev-list", "--count", "@{upstream}..HEAD")) > 0) return "Unpublished commits exist; publish/review them before automatic repair";
    return null;
}

export async function verifyPublished(config, commit) {
    await git(config.repo, "merge-base", "--is-ancestor", commit, "HEAD");
    const output = await git(config.repo, "ls-remote", "--exit-code", config.remote, config.remoteRef);
    const remoteHash = output.split(/\s+/)[0];
    if (!/^[a-f0-9]{40}$/i.test(remoteHash)) throw new Error("Cannot verify upstream head");
    try { await git(config.repo, "cat-file", "-e", remoteHash); }
    catch { await git(config.repo, "fetch", config.remote, config.remoteRef); }
    await git(config.repo, "merge-base", "--is-ancestor", commit, remoteHash);
}

export class CodexClient {
    constructor(config) {
        this.config = config;
        this.pending = new Map();
        this.turns = new Map();
        this.sequence = 0;
    }

    async connect() {
        if (this.initialized && this.ws?.readyState === WebSocket.OPEN) return;
        this.close();
        const child = spawn(this.config.codex, ["app-server", "proxy", "--sock", this.config.socket], {
            windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
        });
        this.child = child;
        child.stderr.resume();
        const socket = Duplex.from({ readable: child.stdout, writable: child.stdin });
        const ws = new WebSocket("ws://localhost/", {
            createConnection: () => socket, handshakeTimeout: 10_000,
            perMessageDeflate: false, maxPayload: 128 * 1024 * 1024,
        });
        this.ws = ws;
        ws.on("error", () => {});
        child.on("error", error => ws.emit("error", error));
        ws.on("message", raw => {
            let message;
            try { message = JSON.parse(raw.toString()); } catch { return; }
            if (!message.method && message.id !== undefined && this.pending.has(message.id)) {
                const entry = this.pending.get(message.id);
                this.pending.delete(message.id);
                clearTimeout(entry.timer);
                if (message.error) entry.reject(Object.assign(new Error(message.error.message), { rpcCode: message.error.code }));
                else entry.resolve(message.result);
            } else if (message.method === "turn/completed") {
                this.turns.set(message.params.turn.id, message.params.turn);
            }
            // Never approve requests automatically; existing Codex UI/permission policy owns them.
        });
        ws.on("close", () => {
            // A delayed close from the old connection must not kill its replacement.
            if (this.ws === ws) {
                this.initialized = false;
                this.rejectPending();
            }
            child.kill();
        });
        try {
            await new Promise((resolve, reject) => {
                ws.once("open", resolve);
                ws.once("error", reject);
                ws.once("close", () => reject(new Error("Codex closed during handshake")));
            });
            await this.call("initialize", {
                clientInfo: { name: "hope_zentao_bug_watch", version: "1.0.0" },
                capabilities: { experimentalApi: true },
            });
            ws.send(JSON.stringify({ method: "initialized" }));
            this.initialized = true;
        } catch (error) { this.close(); throw error; }
    }

    async call(method, params) {
        if (this.ws?.readyState !== WebSocket.OPEN) throw new Error("Codex is disconnected");
        const id = ++this.sequence;
        return await new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error(`Codex ${method} response timed out; reconcile before retrying`));
            }, 20_000);
            this.pending.set(id, { resolve, reject, timer });
            this.ws.send(JSON.stringify({ id, method, params }));
        });
    }

    async readThread(includeTurns = false) {
        return (await this.call("thread/read", { threadId: this.config.threadId, includeTurns })).thread;
    }

    async findTurn(job) {
        if (job.turnId && this.turns.has(job.turnId)) return this.turns.get(job.turnId);
        // A lost turn/start response must not result in a second execution.
        let cursor;
        try {
            do {
                const page = await this.call("thread/turns/list", {
                    threadId: this.config.threadId, limit: 25, itemsView: "full", ...(cursor ? { cursor } : {}),
                });
                for (const turn of page.data) if (matchesTurn(turn, job)) return turn;
                cursor = page.nextCursor;
                if (page.data.length && page.data.every(turn => turn.startedAt && turn.startedAt * 1000 < Date.parse(job.createdAt) - 60_000)) break;
            } while (cursor);
        } catch (error) {
            if (![-32601, -32602].includes(error.rpcCode) && !/paginated|unsupported|legacy/i.test(error.message)) throw error;
            const thread = await this.readThread(true);
            return thread.turns?.find(turn => matchesTurn(turn, job));
        }
        return null;
    }

    rejectPending() {
        for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error("Codex connection closed")); }
        this.pending.clear();
    }

    close() {
        this.initialized = false;
        this.rejectPending();
        if (this.ws?.readyState !== WebSocket.CLOSED) this.ws?.terminate();
        this.child?.kill();
        this.ws = null;
        this.child = null;
    }
}

function matchesTurn(turn, job) {
    return turn.id === job.turnId || turn.items?.some(item => item.type === "userMessage"
        && item.content?.some(content => content.type === "text" && content.text?.includes(job.marker)));
}

export class ZenTaoClient {
    constructor(config) { this.config = config; }

    async connect() {
        if (this.client) return;
        this.client = new Client({ name: "hope-zentao-bug-watch", version: "1.0.0" });
        this.transport = new StdioClientTransport({
            command: "powershell.exe",
            args: ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path.join(this.config.mcpDir, "start.ps1")],
            cwd: this.config.mcpDir, stderr: "pipe",
            env: { ZENTAO_BASE_URL: this.config.baseUrl,
                PATH: `${path.dirname(process.execPath)}${path.delimiter}${process.env.PATH ?? ""}`,
                PATHEXT: process.env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD" },
        });
        this.transport.stderr?.resume();
        try {
            await this.client.connect(this.transport);
            const response = await this.read("/user");
            const user = response.profile ?? response.user ?? response;
            if (user.account !== this.config.account) throw new Error("Configured account differs from authenticated ZenTao account");
        } catch (error) {
            await this.close();
            throw new Error(`ZenTao connection/authentication failed: ${error.message.split("\n")[0]}`);
        }
    }

    async read(apiPath, query, refresh = false) {
        const result = await this.client.callTool({ name: "call", arguments: {
            method: "GET", path: apiPath, ...(query ? { query } : {}), ...(refresh ? { forceTokenRefresh: true } : {}),
        } }, undefined, { timeout: 30_000 });
        if (result.isError) throw new Error("ZenTao MCP read failed");
        const response = JSON.parse(result.content.filter(item => item.type === "text").map(item => item.text).join("\n"));
        if (response.status === 401 && !refresh) return this.read(apiPath, query, true);
        if (response.status !== 200) throw new Error(`ZenTao read returned HTTP ${response.status}`);
        return response.data;
    }

    async bug(id) { return await this.read(`/bugs/${id}`); }

    async scan() {
        const bugs = [];
        for (let page = 1; ; page++) {
            // This installation ignores/incorrectly filters status=active; filter locally.
            const data = await this.read(`/products/${this.config.product}/bugs`, { page, limit: 100 });
            if (!Array.isArray(data.bugs)) throw new Error("Unexpected ZenTao bug list");
            bugs.push(...data.bugs);
            if (data.bugs.length < 100 || bugs.length >= Number(data.total)) break;
            if (page >= 1000) throw new Error("ZenTao pagination did not terminate");
        }
        const result = [];
        // Detail reads include comments/attachments; comments may not change lastEditedDate.
        for (const bug of bugs.filter(bug => eligible(bug, this.config))) result.push(await this.bug(bug.id));
        return result;
    }

    async close() {
        await this.client?.close().catch(() => {});
        this.client = null;
    }
}
