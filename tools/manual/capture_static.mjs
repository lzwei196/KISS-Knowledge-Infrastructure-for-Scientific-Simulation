// Capture the manual's static screenshots from a running GeoForge Desktop.
//
//   node tools/manual/capture_static.mjs --base http://127.0.0.1:8801 \
//        --workroot D:\GeoForge-Manual --out docs/manual/0.6.54/images
//
// Start the app first with a clean demo work folder, for example:
//   "GeoForge Desktop.exe" gui --port 8801 --no-browser --workroot D:\GeoForge-Manual
// Each scene is captured in English and Simplified Chinese. Scenes are
// idempotent except "create the demo chat", which runs once.
import { launch, sleep } from "./cdp.mjs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://127.0.0.1:8801");
const WORKROOT = arg("workroot", "D:\\GeoForge-Manual");
const OUT = arg("out", "docs/manual/0.6.54/images");
const ONLY = arg("only", "");
const LANGS = (arg("langs", "en,zh-CN")).split(",");
const DEMO_CHAT = "Alptal snow example";

const { tab, close } = await launch({ profile: join(tmpdir(), "geoforge-manual-chrome"), port: 9351 });

async function home(lang) {
  await tab.goto(BASE + "/");
  await tab.eval(`localStorage.setItem('kiss.lang', '${lang}'); localStorage.setItem('kiss.kind', 'api');
    localStorage.setItem('kiss-dark', '0')`);
  await tab.goto(BASE + "/");
  await tab.waitFor("document.querySelector('#newsess')", 20000);
  // Provider detection runs after start; wait until the AI count settles.
  await tab.waitFor("/\\d/.test(document.querySelector('#nprov').innerText)", 30000);
  await sleep(1500);
}

async function openDemoChat() {
  const id = await tab.eval(`fetch('/api/sessions').then(r => r.json()).then(list =>
    ((list.sessions || list).find(s => (s.title || s.name) === ${JSON.stringify(DEMO_CHAT)}) || {}).id || null)`);
  if (!id) return false;
  await tab.eval(`openSession(${JSON.stringify(id)})`);
  await sleep(1500);
  return true;
}

async function closeModals() {
  await tab.eval(`document.querySelectorAll('#modal,#sessionpick,#mpick,#guide,#skillpick,#actionpick')
    .forEach(e => e.classList.remove('open')); document.querySelectorAll('.inspector.open')
    .forEach(e => e.classList.remove('open'))`);
  await sleep(300);
}

const shot = (lang, name, opts) => tab.shot(`${OUT}/${lang}/${name}.png`, opts);

const SCENES = [
  ["01-home", async lang => { await shot(lang, "01-home"); }],
  ["02-settings-ai", async lang => {
    await tab.click("#settings"); await tab.waitFor("document.querySelector('#modal .setwin').offsetParent");
    await sleep(1200); await shot(lang, "02-settings-ai", { selector: "#modal .setwin" });
  }],
  ["03-settings-db", async lang => {
    await tab.click("#modal .setnav-item[data-page=db]"); await sleep(1500);
    await shot(lang, "03-settings-db", { selector: "#modal .setwin" });
  }],
  ["04-settings-net", async lang => {
    await tab.click("#modal .setnav-item[data-page=net]"); await sleep(800);
    await shot(lang, "04-settings-net", { selector: "#modal .setwin" });
  }],
  ["05-settings-perm", async lang => {
    await tab.click("#modal .setnav-item[data-page=perm]"); await sleep(800);
    await shot(lang, "05-settings-perm", { selector: "#modal .setwin" });
    await closeModals();
  }],
  ["06-newchat-dialog", async lang => {
    await tab.click("#newsess"); await tab.waitFor("document.querySelector('#sessionpick .card2').offsetParent");
    await tab.type("#project-name", DEMO_CHAT);
    await tab.type("#project-parent", WORKROOT + "\\projects");
    await tab.waitFor("/projects/.test(document.querySelector('#project-path-preview').innerText)", 10000);
    await sleep(500);
    await shot(lang, "06-newchat-dialog", { selector: "#sessionpick .card2" });
    await tab.click("#project-cancel");
  }],
  ["07-guide", async lang => {
    await tab.click("#help"); await sleep(600);
    await shot(lang, "07-guide", { selector: "#guide .card2" });
    await tab.click("#guide-close");
  }],
  ["08-library", async lang => {
    await tab.goto(BASE + "/library"); await sleep(4000); await shot(lang, "08-library");
  }],
  ["09-observatory", async lang => {
    await tab.goto(BASE + "/observatory"); await sleep(5000); await shot(lang, "09-observatory");
  }],
  ["10-studio", async lang => {
    await tab.goto(BASE + "/studio"); await sleep(3000); await shot(lang, "10-studio");
  }],
  // Chat scenes need the demo chat (created once, through the real dialog).
  ["11-chat-empty", async lang => {
    await home(lang);
    if (!(await openDemoChat())) {
      await tab.click("#newsess"); await tab.waitFor("document.querySelector('#sessionpick .card2').offsetParent");
      await tab.type("#project-name", DEMO_CHAT);
      await tab.type("#project-parent", WORKROOT + "\\projects");
      await tab.waitFor("/projects/.test(document.querySelector('#project-path-preview').innerText)", 10000);
      await tab.click("#project-create"); await sleep(2500);
      await openDemoChat();
    }
    await tab.click("#kindtog button[data-k=api]"); await sleep(800);
    await shot(lang, "11-chat-empty");
  }],
  ["12-ki-picker", async lang => {
    await tab.click("#pickmodels"); await tab.waitFor("document.querySelector('#mpick .card2').offsetParent");
    await tab.type("#mq", "FSM2"); await sleep(800);
    await shot(lang, "12-ki-picker", { selector: "#mpick .card2" });
    await tab.click("#m-close");
  }],
  ["13-project-status-new", async lang => {
    await tab.click("#opendata"); await sleep(2500);
    await shot(lang, "13-project-status-new", { selector: "#datapanel" });
    await closeModals();
  }],
];

try {
  for (const lang of LANGS) {
    await home(lang);
    for (const [name, run] of SCENES) {
      if (ONLY && !ONLY.split(",").includes(name)) continue;
      try { await run(lang); console.log("ok  ", lang, name); }
      catch (e) { console.log("FAIL", lang, name, e.message); await closeModals(); await home(lang); }
    }
  }
} finally { close(); }
