// Capture the demo chat's current state (read-only) in both languages:
// the end of the chat, and the Project status panel scrolled to a section.
//
//   node tools/manual/capture_state.mjs --base http://127.0.0.1:8801 \
//        --out docs/manual/0.6.54/images --name 50-not-complete [--panel-scroll 0,900]
//        [--scroll-to "Results (from"] [--no-panel]
//
// Writes <name>-chat.png and <name>-status[-N].png. Safe while no turn runs; it
// only opens pages (a chat opened here does not show a turn running elsewhere).
import { launch, sleep } from "./cdp.mjs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://127.0.0.1:8801");
const OUT = arg("out", "docs/manual/0.6.54/images");
const NAME = arg("name", "50-state");
const CHAT = arg("chat", "Alptal snow example");
const SCROLLS = arg("panel-scroll", "0").split(",").map(Number);
const LANGS = arg("langs", "en,zh-CN").split(",");
const SCROLL_TO = arg("scroll-to", "");          // show the chat from the heading/line with this text
const PANEL = !process.argv.includes("--no-panel");

const { tab, close } = await launch({ profile: join(tmpdir(), "geoforge-manual-state"), port: 9391 });
const save = (lang, file, opts) => tab.shot(`${OUT}/${lang}/${file}.png`, opts).then(() => console.log("ok  ", lang, file));
try {
  for (const lang of LANGS) {
    await tab.goto(BASE + "/");
    await tab.eval(`localStorage.setItem('kiss.lang', '${lang}'); localStorage.setItem('kiss.kind', 'api');
      localStorage.setItem('kiss-dark', '0')`);
    await tab.goto(BASE + "/");
    await tab.waitFor("/[0-9]/.test(document.querySelector('#nprov').innerText)", 30000);
    const sid = await tab.eval(`fetch('/api/sessions').then(r => r.json()).then(list =>
      ((list.sessions || list).find(s => (s.title || s.name) === ${JSON.stringify(CHAT)}) || {}).id || null)`);
    if (!sid) throw new Error(`no chat named ${CHAT}`);
    await tab.eval(`openSession(${JSON.stringify(sid)})`); await sleep(3000);
    const found = SCROLL_TO && await tab.eval(`(() => {
      const chat = document.querySelector('#chat');
      const el = [...chat.querySelectorAll('h1,h2,h3,h4,p,strong,td,li')]
        .find(e => e.innerText && e.innerText.includes(${JSON.stringify(SCROLL_TO)}));
      if (!el) return false;
      chat.scrollTop += el.getBoundingClientRect().top - chat.getBoundingClientRect().top - 16;
      return true; })()`);
    if (!found) await tab.eval("document.querySelector('#chat').scrollTop = document.querySelector('#chat').scrollHeight");
    await sleep(800);
    await save(lang, `${NAME}-chat`);
    if (!PANEL) continue;
    await tab.click("#opendata"); await sleep(3000);
    for (const [i, y] of SCROLLS.entries()) {
      await tab.eval(`(() => { const p = document.querySelector('#datapanel .body') || document.querySelector('#datapanel');
        [...document.querySelectorAll('#datapanel *')].filter(e => e.scrollHeight > e.clientHeight + 20)
          .forEach(e => e.scrollTop = ${y}); p.scrollTop = ${y}; })()`);
      await sleep(600);
      await save(lang, SCROLLS.length > 1 ? `${NAME}-status-${i + 1}` : `${NAME}-status`, { selector: "#datapanel" });
    }
  }
} finally { close(); }
