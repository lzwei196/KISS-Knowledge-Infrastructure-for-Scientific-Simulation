// Capture the manual's worked example (FSM2 Alptal) from a live run.
//
//   node tools/manual/capture_live.mjs --base http://127.0.0.1:8801 \
//        --workroot D:\GeoForge-Manual --out docs/manual/0.6.54/images [--fresh]
//        [--say "follow-up message" --say-shot 52-follow-up-working] [--idle-minutes 10]
//
// Needs a configured API AI (DeepSeek was used for 0.6.54). It makes real AI
// calls: it creates the demo chat, pins FSM2, sends the request, answers each
// planning question with its first (recommended) option, approves the plan and
// captures every state in English and Simplified Chinese.
//
// Two browsers. The "driver" sends every message and is never reloaded while a
// turn is in flight: the chat turn streams over that tab's connection, and a
// reload ends it (0.6.54 on Windows treats the dropped connection as a failed
// turn). The "camera" reloads freely to take each screenshot in both languages;
// it only selects options for the pictures and never sends anything. A chat
// opened in another tab does not show a running turn, so pictures taken while
// the agent works come from the driver: English first, then the driver
// switches to Chinese in place (no reload) and is reloaded in English only
// after the turn has ended.
import { launch, sleep } from "./cdp.mjs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { writeFileSync } from "node:fs";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://127.0.0.1:8801");
const WORKROOT = arg("workroot", "D:\\GeoForge-Manual");
const OUT = arg("out", "docs/manual/0.6.54/images");
const FRESH = process.argv.includes("--fresh");
const SAY = arg("say", "");                      // one follow-up message to send when the chat is idle
const SAY_SHOT = arg("say-shot", "52-follow-up-working");
const IDLE_MINUTES = Number(arg("idle-minutes", "10"));
const DEMO_CHAT = "Alptal snow example";
const LANGS = ["en", "zh-CN"];
const REQUEST = "Run an end-to-end FSM2 snow simulation using the official Alptal example case that ships " +
  "with the FSM2 repository (its sample meteorological forcing and namelist, winter 2004-2005, two points: " +
  "open and forest) with the default physics options. Produce the snow depth and snow water equivalent (SWE) " +
  "time series with a plot, and summarise peak SWE and the melt-out date for each point. " +
  "No GeoForge Database data is needed. Use only the FSM2 KI's own tools for every step.";
const RETRY = "Please retry planning from your saved draft.";
// What the manual tells readers to write when the card says "Not ready to execute yet".
const NOT_READY_NOTE = "Some steps cannot run yet (see Not ready to execute yet). Please revise the plan so " +
  "that every step uses one of the KI's own tools, and drop any step this example does not need.";
const t0 = Date.now();
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const timeline = [];
const mark = (what, extra = {}) => { timeline.push({ at: new Date().toISOString(), minutes: +((Date.now() - t0) / 60000).toFixed(1), what, ...extra }); log(what, extra.title || ""); };

const driver = await launch({ profile: join(tmpdir(), "geoforge-manual-driver"), port: 9361 });
const camera = await launch({ profile: join(tmpdir(), "geoforge-manual-camera"), port: 9362 });
const D = driver.tab, C = camera.tab;
let SID = null;
let driverLang = "en";

async function open(tab, lang) {
  await tab.goto(BASE + "/");
  await tab.eval(`localStorage.setItem('kiss.lang', '${lang}'); localStorage.setItem('kiss.kind', 'api');
    localStorage.setItem('kiss-dark', '0')`);
  await tab.goto(BASE + "/");
  await tab.waitFor("/\\d/.test(document.querySelector('#nprov').innerText)", 30000);
  if (SID) { await tab.eval(`openSession(${JSON.stringify(SID)})`); await sleep(2500); }
}
const findChat = tab => tab.eval(`fetch('/api/sessions').then(r => r.json()).then(list =>
  ((list.sessions || list).find(s => (s.title || s.name) === ${JSON.stringify(DEMO_CHAT)}) || {}).id || null)`);
const busy = () => D.eval("typeof INFLIGHT !== 'undefined' && INFLIGHT.size > 0");
async function reloadDriver() {
  if (await busy()) throw new Error("refusing to reload the driver during a turn");
  await open(D, "en");
  driverLang = "en";
}
// A picture of the running turn in both languages, from the driver.
async function live(name, opts) {
  if (driverLang === "en") await save(D, "en", name, opts);
  await D.eval("GeoForgeI18n.setLanguage('zh-CN')");
  driverLang = "zh-CN";
  await sleep(2500);
  await save(D, "zh-CN", name, opts);
}
const run = () => fetch(`${BASE}/api/session/${SID}/run`).then(r => r.json()).catch(() => ({}));
const cardOpen = tab => tab.eval("!!document.querySelector('#actionpick.open')");
const cardTitle = tab => tab.eval("(document.querySelector('#action-title')||{}).innerText || ''");
const save = (tab, lang, name, opts) => tab.shot(`${OUT}/${lang}/${name}.png`, opts).then(() => log("shot", lang, name));

// One picture in both languages from the camera, after an optional preparation.
async function both(name, prep, opts) {
  for (const lang of LANGS) {
    await open(C, lang);
    if (prep) await prep(lang);
    await save(C, lang, name, opts);
  }
}
// Capture the open card from top to bottom (it scrolls inside the window).
async function shootCard(tab, lang, name) {
  const parts = await tab.eval(`(() => { const c = document.querySelector('#action-card'); c.scrollTop = 0;
    return Math.max(1, Math.ceil(c.scrollHeight / (c.clientHeight - 60))); })()`);
  for (let i = 0; i < Math.min(parts, 4); i++) {
    await tab.eval(`(() => { const c = document.querySelector('#action-card'); c.scrollTop = ${i} * (c.clientHeight - 60); })()`);
    await sleep(400);
    await save(tab, lang, parts > 1 ? `${name}-${i + 1}` : name, { selector: "#action-card", pad: 4 });
  }
  await tab.eval("document.querySelector('#action-card').scrollTop = 0");
}
async function cameraCard(name, selectedName) {
  for (const lang of LANGS) {
    await open(C, lang);
    await C.waitFor("document.querySelector('#actionpick.open')", 20000);
    await sleep(1500);
    await shootCard(C, lang, name);
    if (selectedName) {
      await C.click("#action-options > *:first-child"); await sleep(500);
      await save(C, lang, selectedName, { selector: "#action-card", pad: 4 });
    }
  }
}
async function send(text) {
  await D.type("#msg", text); await sleep(300);
  await D.click("#send");
  await D.waitFor("INFLIGHT.size > 0", 15000);
}

try {
  // 1. A clean demo chat with FSM2 pinned and DeepSeek (direct API) selected.
  await open(D, "en");
  let existing = await findChat(D);
  if (existing && FRESH) {
    // Deleting a chat archives its project folder under _archived; nothing is lost.
    // (On Windows this fails while another program has a file of that project open.)
    const status = await D.eval(`fetch('/api/session/${existing}/delete', {method: 'POST', body: '{}'})
      .then(r => r.text()).catch(e => 'error: ' + e.message)`);
    if (await findChat(D)) throw new Error(`could not archive the previous demo chat: ${status}`);
    log("archived the previous demo chat", existing);
    existing = null;
    await open(D, "en");
  }
  if (!existing) {
    await D.click("#newsess"); await D.waitFor("document.querySelector('#sessionpick .card2').offsetParent");
    await D.type("#project-name", DEMO_CHAT);
    await D.type("#project-parent", WORKROOT + "\\projects");
    await D.waitFor("/projects/.test(document.querySelector('#project-path-preview').innerText)", 10000);
    await D.click("#project-create"); await sleep(2500);
  }
  SID = await findChat(D);
  if (!SID) throw new Error("could not create the demo chat");
  mark("chat ready", { session: SID });
  await reloadDriver();
  const n = (await (await fetch(`${BASE}/api/session/${SID}`)).json()).messages?.length || 0;
  if (n === 0) {
    await D.click("#kindtog button[data-k=api]"); await sleep(600);
    const prov = await D.eval(`(() => { const s = document.querySelector('#prov');
      const o = [...s.options].find(o => /deepseek/i.test(o.value + o.text));
      if (o && s.value !== o.value) { s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); }
      return s.value; })()`);
    log("provider", prov);
    await D.click("#pickmodels"); await D.waitFor("document.querySelector('#mpick .card2').offsetParent");
    await D.type("#mq", "FSM2"); await sleep(600);
    await D.eval(`(() => { const row = document.querySelector('.pickrow[data-n="FSM2"]');
      if (row && !row.classList.contains('on')) row.click(); })()`);
    await sleep(300); await D.click("#m-apply"); await sleep(1500);
    await both("20-ki-pinned");
    await both("21-request-typed", async () => { await C.type("#msg", REQUEST); await sleep(400); });
    await reloadDriver();
    await send(REQUEST);
    mark("request sent");
    await sleep(12000);
    await live("22-agent-working");
  }

  // 2. Answer questions, approve, and capture each state until the run ends.
  let questions = 0, approvals = 0, retries = 0, modifies = 0, idleSince = null, lastState = "";
  const shotOnce = new Set();
  if (SAY && !(await busy())) {
    shotOnce.add("setup"); shotOnce.add("exec"); shotOnce.add("planning");
    await send(SAY);
    mark("follow-up sent", { title: SAY.slice(0, 80) });
    await sleep(12000);
    if (await busy()) await live(SAY_SHOT);
  }
  const deadline = Date.now() + 150 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(5000);
    const r = await run();
    const state = r.flow_state || "";
    if (state !== lastState) { mark("flow state", { title: state }); lastState = state; }
    const inFlight = await busy();
    if (inFlight) {
      idleSince = null;
      if (state === "PLANNING" && !shotOnce.has("planning") && driverLang === "en") {
        shotOnce.add("planning"); await sleep(8000);
        if (await busy()) await live("22-agent-working");
      }
      if (state === "SETUP_RUNNING" && !shotOnce.has("setup")) {
        shotOnce.add("setup"); await sleep(20000);
        await live("30-setup-running");
        await both("31-setup-status", async () => { await C.click("#opendata"); await sleep(2500); },
          { selector: "#datapanel" });
      }
      if (state === "EXECUTING" && !shotOnce.has("exec")) {
        shotOnce.add("exec"); await sleep(15000);
        await live("33-running");
      }
      continue;
    }
    // The driver is idle: the turn has ended.
    idleSince ??= Date.now();
    if (state === "COMPLETED") break;
    if (["FAILED_VALIDATION", "BLOCKED"].includes(state)) {
      await both(`90-${state.toLowerCase()}`);
      throw new Error(`run stopped in ${state}; finish it by hand`);
    }
    if (driverLang !== "en") {                       // back to English, now that nothing is in flight
      await reloadDriver();
      await D.waitFor("document.querySelector('#actionpick.open')", 15000).catch(() => {});
    }
    if (!(await cardOpen(D))) {
      if (Date.now() - idleSince < 20000) continue;
      await reloadDriver();                         // safe: nothing is in flight
      if (!(await cardOpen(D))) {
        if (state === "PLANNING" && retries < 3) {
          if (!shotOnce.has("plan-retry")) { shotOnce.add("plan-retry"); await both("91-plan-not-submitted"); }
          retries++; await send(RETRY); mark("asked to retry planning", { title: String(retries) });
          idleSince = null; continue;
        }
        if (Date.now() - idleSince > IDLE_MINUTES * 60 * 1000) throw new Error(`idle in ${state} with nothing to answer`);
        continue;
      }
    }
    idleSince = null;
    const title = await cardTitle(D);
    const notReady = /Approve the plan/i.test(title) &&
      await D.eval("/Not ready to execute yet/i.test(document.querySelector('#action-card').innerText)");
    if (notReady && modifies < 2) {
      // Do what the manual says: ask for a plan whose steps can all run.
      modifies++;
      const suffix = modifies > 1 ? `-${modifies}` : "";
      mark("plan not ready: modify", { title });
      await cameraCard(`25-plan-not-ready${suffix}`, null);
      for (const lang of LANGS) {
        await open(C, lang);
        await C.waitFor("document.querySelector('#actionpick.open')", 20000);
        await C.click("#action-options > *:nth-child(2)"); await sleep(300);
        await C.type("#action-note", NOT_READY_NOTE); await sleep(300);
        await C.eval("document.querySelector('#action-note').scrollIntoView({block: 'center'})"); await sleep(400);
        await save(C, lang, `27-modify-plan${suffix}`, { selector: "#action-card", pad: 4 });
      }
      await D.click("#action-options > *:nth-child(2)"); await sleep(300);
      await D.type("#action-note", NOT_READY_NOTE); await sleep(300);
      await D.click("#action-continue");
      await D.waitFor("INFLIGHT.size > 0", 15000).catch(() => {});
      mark("asked for a plan change");
      continue;
    }
    if (/Approve the plan/i.test(title)) {
      approvals++;
      const suffix = approvals > 1 ? `-${approvals}` : "";
      mark("approval card", { title });
      await cameraCard(`25-approval-card${suffix}`, `26-approve-selected${suffix}`);
    } else {
      questions++;
      mark(`question ${questions}`, { title });
      await cameraCard(`23-question-${questions}`, questions === 1 ? "24-question-selected" : null);
    }
    await D.click("#action-options > *:first-child");   // the recommended option / "Approve and start"
    await sleep(400);
    await D.click("#action-continue");
    await D.waitFor("INFLIGHT.size > 0", 15000).catch(() => {});
    mark("answered", { title: title.slice(0, 80) });
  }

  // 3. Results: chat summary, project status, project view.
  await sleep(5000);
  mark("completed");
  await both("40-result-chat", async () => {
    await C.eval("document.querySelector('#chat').scrollTop = document.querySelector('#chat').scrollHeight");
    await sleep(800);
  });
  await both("41-status-completed", async () => { await C.click("#opendata"); await sleep(3000); },
    { selector: "#datapanel" });
  await both("42-project-view", async () => { await C.click("#openview"); await sleep(4000); });
} finally {
  writeFileSync(`${OUT}/live-run.json`, JSON.stringify({ session: SID, timeline }, null, 2));
  driver.close(); camera.close();
}
