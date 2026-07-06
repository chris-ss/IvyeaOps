import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class PipeCDP {
  constructor(process) {
    this.process = process;
    this.input = process.stdio[3];
    this.output = process.stdio[4];
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.buffer = Buffer.alloc(0);
    this.stderr = "";
    process.stderr.on("data", (chunk) => { this.stderr += chunk.toString("utf8"); });
    const rejectPending = (error) => {
      for (const pending of this.pending.values()) pending.reject(error);
      this.pending.clear();
    };
    this.input.on("error", (cause) => rejectPending(new Error(`Chrome input pipe failed: ${cause.message}`)));
    this.output.on("error", (cause) => rejectPending(new Error(`Chrome output pipe failed: ${cause.message}`)));
    process.on("exit", (code, signal) => {
      const error = new Error(
        `Chrome exited before E2E completion (code=${code}, signal=${signal}): ${this.stderr.slice(-2000)}`,
      );
      rejectPending(error);
    });
    process.on("error", (cause) => {
      const error = new Error(`Chrome failed to start: ${cause.message}`);
      rejectPending(error);
    });
    this.output.on("data", (chunk) => this.consume(chunk));
  }

  consume(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    let boundary;
    while ((boundary = this.buffer.indexOf(0)) >= 0) {
      const raw = this.buffer.subarray(0, boundary).toString("utf8");
      this.buffer = this.buffer.subarray(boundary + 1);
      if (!raw) continue;
      const message = JSON.parse(raw);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) continue;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result || {});
        continue;
      }
      for (const listener of this.listeners.get(message.method) || []) {
        listener(message.params || {}, message.sessionId || "");
      }
    }
  }

  send(method, params = {}, sessionId = "") {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      const message = { id, method, params };
      if (sessionId) message.sessionId = sessionId;
      this.input.write(`${JSON.stringify(message)}\0`);
    });
  }

  on(method, listener) {
    const rows = this.listeners.get(method) || [];
    rows.push(listener);
    this.listeners.set(method, rows);
  }
}

const governance = {
  ok: true,
  healthy: true,
  summary: {
    pending_reviews: 0,
    approved_not_published: 0,
    published_changes: 1,
    coverage_gaps: 0,
    stale_cards: 0,
    monitor_errors: 0,
    monitor_overdue: 0,
    conflicts: 0,
    unverified_approved: 0,
  },
  reviews: { summary: { pending: 0 }, changes: [] },
  coverage: {
    summary: { requirements: 41, covered: 41, gaps: 0, coverage_rate: 1, primary_current_rate: 0.976 },
    requirements: [{
      domain: "tax_compliance", marketplace: "GLOBAL", status: "strong", covered: true,
      primary_current: true, card_ids: ["tax.tax_reports_and_liability"], source_urls: [],
    }],
    policy: "GLOBAL applies to cross-market reporting and advertising domains.",
  },
  freshness: {
    summary: {
      cards: 71,
      card_freshness: { current: 70, reviewed: 1, stale_needs_review: 0 },
      monitor_sources: 47,
      monitor_status: { current: 47, unseen: 0, overdue: 0, error: 0 },
    },
    cards_requiring_review: [],
    sources: [],
  },
  conflicts: [],
};

let evidenceApplied = false;
function apiPayload(url, method) {
  const pathname = new URL(url).pathname;
  if (pathname === "/api/auth/me") return { username: "e2e-admin", role: "admin", permissions: [] };
  if (pathname === "/api/setup/status") return { needs_setup: false, setup_done: true, checks: {} };
  if (pathname === "/api/health") return { ok: true, version: "e2e" };
  if (pathname === "/api/setup/update-info") {
    return { current: "e2e", latest: "e2e", update_available: false, platform_update_supported: false };
  }
  if (pathname === "/api/skill-tools/pinned") return [];
  if (pathname === "/api/autofix/status") return { enabled: false, job: null };
  if (pathname === "/api/ivyea-agent/knowledge/governance") return governance;
  if (pathname === "/api/ivyea-agent/knowledge/changes") {
    return { ok: true, summary: { changes: 0, pending: 0, published: 0 }, changes: [], review_required: false };
  }
  if (pathname === "/api/ivyea-agent/knowledge/evidence" && method === "GET") {
    return {
      ok: true,
      summary: { evidence: evidenceApplied ? 1 : 0, ready_for_diagnosis: evidenceApplied ? 1 : 0 },
      evidence: evidenceApplied ? [{
        id: "ev-e2e", title: "E2E settlement evidence", kind: "settlement_report", marketplace: "US",
        card_id: "user.evidence.settlement.e2e", diagnostic: { ready_for_diagnosis: true },
      }] : [],
    };
  }
  if (pathname === "/api/ivyea-agent/knowledge/evidence/draft") {
    return {
      ok: true,
      raw_preserved: false,
      evidence: {
        id: "ev-e2e", redactions: { email: 1 },
        diagnostic: { ready_for_diagnosis: true, missing_inputs: [] },
      },
      draft: { diff: "--- old\n+++ new\n+sanitized settlement evidence" },
    };
  }
  if (pathname === "/api/ivyea-agent/knowledge/evidence/apply") {
    evidenceApplied = true;
    return { ok: true, evidence: { id: "ev-e2e" }, result: { ok: true, applied: true } };
  }
  return {};
}

async function evaluate(send, expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "browser evaluation failed");
  return result.result?.value;
}

async function waitFor(send, expression, label, timeout = 20_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(send, expression)) return;
    await delay(100);
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function setValue(send, selector, value) {
  await evaluate(send, `(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) throw new Error("missing element: ${selector}");
    const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  })()`);
}

async function run() {
  if (process.env.IVYEA_E2E_SKIP_BUILD !== "1") {
    const build = spawnSync("npm", ["run", "build"], { cwd: path.resolve("."), encoding: "utf8" });
    if (build.status !== 0) throw new Error(build.stderr || build.stdout || "client build failed");
  }
  const dist = path.resolve("dist");
  const rawHtml = await readFile(path.join(dist, "index.html"), "utf8");
  const assetRoot = pathToFileURL(path.join(dist, "assets")).href.replace(/\/$/, "");
  const appHtml = rawHtml
    .replace(/(?:<link rel="icon"[^>]*>|<link rel="apple-touch-icon"[^>]*>)/g, "")
    .replace(/(["'])\/assets\//g, `$1${assetRoot}/`)
    .replace("<script type=\"module\"", `<script>
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const value = typeof input === "string" && input.startsWith("/api/") ? "https://ivyea-e2e.local" + input : input;
        return originalFetch(value, init);
      };
      const originalOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        const value = typeof url === "string" && url.startsWith("/api/") ? "https://ivyea-e2e.local" + url : url;
        return originalOpen.call(this, method, value, ...rest);
      };
    </script><script type="module"`);

  const profile = await mkdtemp(path.join(os.tmpdir(), "ivyea-knowledge-e2e-"));
  const chrome = spawn("google-chrome", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--disable-breakpad", "--disable-crash-reporter", "--disable-crashpad-for-testing", "--noerrdialogs",
    "--allow-file-access-from-files", "--disable-web-security", "--remote-debugging-pipe",
    `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe", "pipe", "pipe"] });
  const cdp = new PipeCDP(chrome);
  try {
    const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    const send = (method, params = {}) => cdp.send(method, params, sessionId);
    const browserErrors = [];
    cdp.on("Runtime.exceptionThrown", (params, eventSession) => {
      if (eventSession === sessionId) browserErrors.push(params.exceptionDetails?.text || "browser exception");
    });
    cdp.on("Fetch.requestPaused", async ({ requestId, request }, eventSession) => {
      if (eventSession !== sessionId) return;
      let body;
      let contentType;
      if (request.url.startsWith("file:///brain")) {
        body = appHtml;
        contentType = "text/html; charset=utf-8";
      } else {
        body = JSON.stringify(apiPayload(request.url, request.method));
        contentType = "application/json; charset=utf-8";
      }
      await send("Fetch.fulfillRequest", {
        requestId,
        responseCode: 200,
        responseHeaders: [
          { name: "Content-Type", value: contentType },
          { name: "Access-Control-Allow-Origin", value: "*" },
        ],
        body: Buffer.from(body).toString("base64"),
      });
    });
    await Promise.all([
      send("Page.enable"),
      send("Runtime.enable"),
      send("Fetch.enable", { patterns: [
        { urlPattern: "file:///brain*", requestStage: "Request" },
        { urlPattern: "https://ivyea-e2e.local/api/*", requestStage: "Request" },
      ] }),
    ]);
    await send("Page.navigate", { url: "file:///brain?tab=governance" });
    await waitFor(send, `document.body.innerText.includes("IvyeaAgent 知识治理中心")`, "governance center");
    assert.equal(await evaluate(send, `document.body.innerText.includes("41/41")`), true);

    await evaluate(send, `document.querySelector('[data-testid="knowledge-view-evidence"]').click()`);
    await waitFor(send, `!!document.querySelector('[data-testid="knowledge-evidence-view"]')`, "evidence view");
    await setValue(send, '[data-testid="evidence-kind"]', "settlement_report");
    await setValue(send, '[data-testid="evidence-title"]', "E2E settlement evidence");
    await setValue(send, '[data-testid="evidence-message"]', "Payment released for settlement");
    await setValue(send, '[data-testid="evidence-content"]', "Contact email owner@example.com; settlement reconciled.");
    await evaluate(send, `document.querySelector('[data-testid="evidence-authorized"]').click()`);
    await evaluate(send, `document.querySelector('[data-testid="evidence-rights"]').click()`);
    await waitFor(send, `!document.querySelector('[data-testid="evidence-preview-button"]').disabled`, "enabled preview button");
    await evaluate(send, `document.querySelector('[data-testid="evidence-preview-button"]').click()`);
    await waitFor(send, `!!document.querySelector('[data-testid="evidence-preview"]')`, "sanitized evidence preview");
    assert.equal(await evaluate(send, `document.body.innerText.includes("原始文件保留：否")`), true);

    await evaluate(send, `document.querySelector('[data-testid="evidence-apply-button"]').click()`);
    await waitFor(send, `!!document.querySelector('.confirm-ok-normal')`, "confirmation dialog");
    await evaluate(send, `document.querySelector('.confirm-ok-normal').click()`);
    await waitFor(send, `document.body.innerText.includes("user.evidence.settlement.e2e")`, "applied evidence row");
    assert.deepEqual(browserErrors, []);
    process.stdout.write("knowledge governance browser E2E passed\n");
  } finally {
    try { chrome.kill("SIGTERM"); } catch {}
    await rm(profile, { recursive: true, force: true });
  }
}

await run();
