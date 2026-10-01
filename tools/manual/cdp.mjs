// Minimal Chrome DevTools Protocol driver for manual screenshots.
// No npm dependencies: Node 22+ ships fetch and WebSocket.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const CHROME_CANDIDATES = [
  process.env.CHROME,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

export async function launch({ port = 9333, profile, width = 1280, height = 820, scale = 2 } = {}) {
  const chrome = CHROME_CANDIDATES.find(existsSync);
  if (!chrome) throw new Error("Chrome or Edge not found; set CHROME");
  mkdirSync(profile, { recursive: true });
  const proc = spawn(chrome, [
    "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
    `--window-size=${width},${height}`, "about:blank",
  ], { stdio: "ignore" });
  let targets;
  for (let i = 0; i < 100; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; }
    catch { await sleep(100); }
  }
  const page = targets.find(t => t.type === "page");
  const tab = new Tab(page.webSocketDebuggerUrl);
  await tab.open();
  await tab.send("Page.enable");
  await tab.send("Runtime.enable");
  await tab.viewport(width, height, scale);
  return { tab, close: () => proc.kill() };
}

export class Tab {
  constructor(url) { this.url = url; this.id = 0; this.pending = new Map(); this.events = []; }
  open() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
      this.ws.onmessage = ({ data }) => {
        const msg = JSON.parse(data);
        if (msg.id && this.pending.has(msg.id)) {
          const { res, rej } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
        } else if (msg.method) this.events.push(msg);
      };
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  async viewport(width, height, scale = 2) {
    this.width = width; this.height = height;
    await this.send("Emulation.setDeviceMetricsOverride",
      { width, height, deviceScaleFactor: scale, mobile: false });
  }
  async eval(expression) {
    const r = await this.send("Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "eval failed");
    return r.result.value;
  }
  async goto(url) {
    await this.send("Page.navigate", { url });
    await this.waitFor("document.readyState === 'complete'", 30000);
    await sleep(600);
  }
  async waitFor(expression, timeout = 15000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      try { if (await this.eval(`!!(${expression})`)) return true; } catch {}
      await sleep(200);
    }
    throw new Error(`timed out waiting for: ${expression}`);
  }
  // Click the first visible element matching a CSS selector, or whose text matches.
  async click(target) {
    const ok = await this.eval(`(() => {
      const t = ${JSON.stringify(target)};
      const visible = e => e && e.offsetParent !== null;
      let el = null;
      try { el = [...document.querySelectorAll(t)].find(visible); } catch {}
      if (!el) el = [...document.querySelectorAll('button,a,label,summary,[role=button],.opt,.option,li')]
        .find(e => visible(e) && e.innerText && e.innerText.trim().startsWith(t));
      if (!el) return false;
      el.scrollIntoView({block: 'center'}); el.click(); return true;
    })()`);
    if (!ok) throw new Error(`nothing to click: ${target}`);
    await sleep(400);
  }
  async type(selector, text) {
    await this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      el.focus(); el.value = ${JSON.stringify(text)};
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    })()`);
  }
  // Screenshot the viewport, or the box of a selector (with padding).
  async shot(file, { selector, pad = 12 } = {}) {
    let clip;
    if (selector) {
      const r = await this.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
        if (!e) return null; const b = e.getBoundingClientRect();
        return {x: b.left, y: b.top, w: b.width, h: b.height}; })()`);
      if (!r) throw new Error(`no element for shot: ${selector}`);
      const x = Math.max(0, r.x - pad), y = Math.max(0, r.y - pad);
      clip = { x, y, width: Math.min(this.width - x, r.w + 2 * pad), height: Math.min(this.height - y, r.h + 2 * pad), scale: 1 };
    }
    const { data } = await this.send("Page.captureScreenshot", { format: "png", ...(clip ? { clip } : {}) });
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from(data, "base64"));
    return file;
  }
}

export { sleep };
