// Capture the KI Library and Agent setup pages for one KI (read-only).
//
//   node tools/manual/capture_setup.mjs --base http://127.0.0.1:8801 \
//        --out docs/manual/0.6.54/images --ki FSM2 --prefix 14
//
// Run it before the worked example (--prefix 14: the KI still needs setup)
// and after it (--prefix 44: verified on this computer). Loading these pages
// only reads state; nothing is installed or started.
import { launch, sleep } from "./cdp.mjs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://127.0.0.1:8801");
const OUT = arg("out", "docs/manual/0.6.54/images");
const KI = arg("ki", "FSM2");
const PREFIX = Number(arg("prefix", "14"));
const LANGS = (arg("langs", "en,zh-CN")).split(",");

const { tab, close } = await launch({ profile: join(tmpdir(), "geoforge-manual-setupcam"), port: 9371, height: 900 });
const name = (i, what) => `${PREFIX + i}-${what}`;
const save = (lang, file, opts) => tab.shot(`${OUT}/${lang}/${file}.png`, opts).then(() => console.log("ok  ", lang, file));

try {
  for (const lang of LANGS) {
    await tab.goto(BASE + "/library");
    await tab.eval(`localStorage.setItem('kiss.lang', '${lang}'); localStorage.setItem('kiss-dark', '0')`);
    await tab.goto(BASE + "/library");
    await tab.waitFor(`document.querySelector('#list .item[data-n="${KI}"]')`, 30000);
    await tab.type("#q", KI); await sleep(800);
    await tab.click(`#list .item[data-n="${KI}"]`); await sleep(4000);
    await save(lang, name(0, "library-ki"));
    await tab.goto(`${BASE}/setup?model=${encodeURIComponent(KI)}&provider=api:deepseek`);
    await tab.waitFor("document.querySelector('#title') && !/^\\s*$/.test(document.querySelector('#title').innerText)", 20000);
    await sleep(3500);
    await save(lang, name(1, "setup-page"));
    const h = await tab.eval("document.documentElement.scrollHeight");
    if (h > 940) {
      await tab.eval("window.scrollTo(0, document.documentElement.scrollHeight)"); await sleep(800);
      await save(lang, name(1, "setup-page-lower"));
    }
  }
} finally { close(); }
