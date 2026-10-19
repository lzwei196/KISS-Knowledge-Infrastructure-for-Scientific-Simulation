const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const pagePath = process.env.GEOFORGE_TEST_PAGE || path.resolve(__dirname, '../../kiss_cli/web/app.html');
const page = fs.readFileSync(pagePath, 'utf8').replaceAll('\r\n', '\n');
function fn(name) {
  const start = page.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const lineEnd = page.indexOf('\n', start);
  if (page.slice(start, lineEnd).endsWith('}')) return page.slice(start, lineEnd);
  const end = page.indexOf('\n}', start);
  assert.ok(end > start, name);
  return page.slice(start, end + 2);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const providers = () => ({ providers: [
  { name: 'cli:claude', kind: 'cli', installed: true, usable: true, label: 'Claude Code' },
  { name: 'api:deepseek', kind: 'api', installed: true, usable: true, label: 'DeepSeek' },
], any_usable: true, default: 'cli:claude' });
const response = value => ({ ok: true, json: async () => value });
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function harness(options = {}) {
  const elements = new Map(), banners = new Map(), calls = [], requests = [], timers = [];
  let now = 10000;
  const buttons = ['cli', 'api'].map(k => ({ dataset: { k }, disabled: false, classes: new Set(),
    classList: { toggle(name, active) { active ? buttons.find(b => b.dataset.k === k).classes.add(name) : buttons.find(b => b.dataset.k === k).classes.delete(name); } } }));
  function el(id) {
    if (!elements.has(id)) elements.set(id, { id, innerHTML: '', value: '', textContent: '', disabled: false,
      focus() {}, remove() { banners.delete(id); },
      insertAdjacentHTML(_where, html) { const name = '#' + html.match(/id="([^"]+)"/)[1]; banners.set(name, html); },
    });
    return elements.get(id);
  }
  function $(id) {
    if (id === '#kindgap' || id === '#gatebanner') return banners.has(id) ? el(id) : null;
    if (id === '#quick-recheck') return banners.has('#kindgap') ? el(id) : null;
    return el(id);
  }
  const context = vm.createContext({ assert, Promise, URLSearchParams, console,
    Date: { now: () => now }, setTimeout: (callback, delay) => { timers.push({ callback, delay }); },
    $, document: { querySelectorAll: () => buttons }, esc: s => String(s),
    providerOptionLabel: p => p.label, providerIssue: () => 'check needed',
    sessionBusy: () => false, sessionUploading: () => false, updateActivityUI() {},
    INVESTIGATION: { sync() { calls.push('investigation'); } },
    drawLLM() {}, drawLocalSettings() { calls.push('local'); },
    drawProxyProviderSettings() { calls.push('proxy'); }, drawModelLabel() { calls.push('model'); },
    drawSessions() {}, drawEmpty() {}, chineseUI: () => false,
    location: { search: '' }, sessionStorage: { getItem: () => null }, history: { replaceState() {} },
    fetch: async (url, opts) => { requests.push(url); return options.fetch ? options.fetch(url, opts) : response(providers()); },
    openSession: options.openSession || (async () => {}),
    refreshMachineStatus: options.refreshMachineStatus || (async () => { calls.push('status'); }),
  });
  vm.runInContext(`let PROV={providers:[],any_usable:false,check_state:'loading'};
    let CUR={id:'locked',provider:'api:deepseek',binding_locked:true};
    let KIND='cli',KIND_SYNCED_FOR,LAST_PROVIDER_CHECK=0,PROVIDER_REFRESHING=null;
    let SESSIONS=[],MODELS=[],SKILLS=[],MCP={},PROJECT_LOCATION={};
    const PENDING_ACTIONS=new Map();
    const SESSION_SUMMARIES=new Map();
    ${fn('mergeSessionSummaries')}
    ${fn('kindOf')}
    ${fn('currentProviderReady')}
    ${fn('renderNextPhaseComposerNotice')}
    ${fn('setControls')}
    ${fn('drawProviders')}
    ${fn('refreshProviders')}
    ${fn('refreshProvidersOnFocus')}
    ${fn('loadAll')}`, context);
  return { context, $, calls, requests, buttons, banners, timers,
    run: code => vm.runInContext(code, context), setNow: value => { now = value; } };
}

test('unknown startup reports checking without claiming missing keys or CLIs', () => {
  const h = harness(); h.run('drawProviders()');
  assert.equal(h.$('#nprov').textContent, 'Checking AI connections…');
  assert.match(h.$('#prov').innerHTML, /Checking AI connections/);
  assert.equal(h.banners.size, 0);
  assert.ok(h.buttons.every(b => !b.classes.has('none')));
  assert.equal(h.$('#send').disabled, true);
  assert.match(page, /id="nprov"[^>]*>Checking AI connections/);
});

test('provider response renders while openSession and catalog scan are still pending', async () => {
  const status = deferred(); let opened = false;
  const h = harness({
    fetch: async url => response(url === '/api/providers' ? providers() : url === '/api/sessions' ? [{ id: 'locked' }] : []),
    openSession: async () => { opened = true; await status.promise; },
    refreshMachineStatus: () => status.promise,
  });
  h.context.location.search = '?session=locked';
  let finished = false; const loading = h.run('loadAll()').then(() => { finished = true; });
  await flush();
  assert.equal(opened, true); assert.equal(finished, false);
  await h.run('PROVIDER_REFRESHING');
  assert.equal(finished, false);
  assert.equal(h.requests.filter(url => url === '/api/providers').length, 1);
  assert.equal(h.$('#nprov').textContent, '2 AI ready');
  assert.equal(h.$('#prov').value, 'api:deepseek');
  assert.deepEqual(h.calls.filter(c => ['local', 'proxy', 'model'].includes(c)), ['local', 'proxy', 'model']);
  assert.equal(h.$('#prov').disabled, true); assert.equal(h.$('#llm').disabled, true);
  assert.ok(h.buttons.every(b => b.disabled));
  status.resolve({}); await loading;
  assert.equal(h.requests.filter(url => url.startsWith('/api/providers')).length, 1);
});

test('concurrent manual and focus refreshes share one in-flight request', async () => {
  const server = deferred(); const h = harness({ fetch: () => server.promise });
  const first = h.run('refreshProviders(false,false)');
  const second = h.run('refreshProviders(true)');
  h.run('refreshProvidersOnFocus(); refreshProvidersOnFocus()'); await flush();
  assert.deepEqual(h.requests, ['/api/providers']);
  server.resolve(response(providers())); assert.equal(await first, true); assert.equal(await second, true);
  assert.equal(h.$('#s-local-msg').textContent, 'checked');
  assert.equal(h.run('PROVIDER_REFRESHING'), null);
});

test('empty-list fetch failure is retryable on focus, throttled and deduplicated', async () => {
  let attempt = 0; const retry = deferred();
  const h = harness({ fetch: async () => { if (!attempt++) throw Error('offline'); return retry.promise; } });
  assert.equal(await h.run('refreshProviders(false,false)'), false);
  assert.equal(h.run('PROV.check_state'), 'error');
  assert.match(h.$('#nprov').textContent, /check failed/);
  assert.match(h.banners.get('#kindgap'), /Recheck/);
  assert.equal(h.banners.has('#gatebanner'), false);
  h.setNow(12999); h.run('refreshProvidersOnFocus()'); await flush(); assert.equal(h.requests.length, 1);
  h.setNow(13001); const done = h.run('refreshProvidersOnFocus()');
  h.run('refreshProvidersOnFocus()'); await flush(); assert.equal(h.requests.length, 2);
  assert.equal(h.requests[1], '/api/providers?refresh=1');
  retry.resolve(response(providers())); assert.equal(await done, true);
  assert.equal(h.$('#nprov').textContent, '2 AI ready'); assert.equal(h.banners.size, 0);
});

test('manual Recheck can recover without waiting for focus throttle', async () => {
  let fail = true; const h = harness({ fetch: async () => { if (fail) throw Error('offline'); return response(providers()); } });
  await h.run('refreshProviders()'); fail = false;
  await h.$('#quick-recheck').onclick();
  assert.equal(h.requests.length, 2); assert.equal(h.run('PROV.check_state'), 'ready');
});

for (const [name, bad] of [
  ['HTTP error', { ok: false, status: 500, json: async () => providers() }],
  ['invalid JSON', { ok: true, json: async () => { throw Error('json'); } }],
  ['wrong schema', response({ providers: [null], any_usable: true })],
]) test(`${name} retains known connection and locked session without claiming absence`, async () => {
  let badRequest = false; const h = harness({ fetch: async () => badRequest ? bad : response(providers()) });
  await h.run('refreshProviders()'); badRequest = true;
  assert.equal(await h.run('refreshProviders()'), false);
  assert.equal(h.run('PROV.providers.length'), 2);
  assert.equal(h.$('#prov').value, 'api:deepseek');
  assert.equal(h.$('#prov').disabled, true); assert.equal(h.$('#llm').disabled, true);
  assert.ok(h.buttons.every(b => b.disabled));
  assert.equal(h.$('#nprov').textContent, '2 AI ready · recheck needed');
});

test('manual provider-kind selection is not reset on later redraws', async () => {
  const h = harness(); h.run("CUR={id:'new',provider:'cli:claude'}");
  await h.run('refreshProviders()'); h.run("KIND='api'; drawProviders()");
  await h.run('refreshProviders()');
  assert.equal(h.run('KIND'), 'api'); assert.equal(h.$('#prov').value, 'api:deepseek');
});

test('successful absence is shown honestly and does not auto-retry forever', async () => {
  const h = harness({ fetch: async () => response({ providers: [], any_usable: false }) });
  await h.run('refreshProviders()');
  assert.equal(h.$('#nprov').textContent, 'AI setup needed');
  h.setNow(90000); h.run('refreshProvidersOnFocus()'); await flush(); assert.equal(h.requests.length, 1);
});

test('installed CLI awaiting login retains existing focus-recheck behavior', async () => {
  const h = harness({ fetch: async () => response({ providers: [{ name: 'cli:claude', kind: 'cli', installed: true, usable: false }], any_usable: false }) });
  await h.run('refreshProviders()'); h.setNow(13001);
  await h.run('refreshProvidersOnFocus()'); assert.equal(h.requests.length, 2);
});

test('window focus invokes bounded provider retry alongside independent status refresh', () => {
  const begin = page.indexOf('window.addEventListener("focus",()=>{');
  const end = page.indexOf('\n});', begin) + 4;
  const callback = page.slice(begin, end);
  const calls = []; let focus;
  vm.runInNewContext(callback, { window: { addEventListener(name, fn) { assert.equal(name, 'focus'); focus = fn; } },
    refreshSessionList() { calls.push('sessions'); }, watchKiUpdates() { calls.push('ki'); },
    CUR:{id:'current'},refreshRun(id,force) { assert.equal(id,'current');assert.equal(force,true);calls.push('project'); },
    refreshMachineStatus() { calls.push('status'); }, refreshProvidersOnFocus() { calls.push('providers'); } });
  focus(); assert.deepEqual(calls, ['sessions', 'ki', 'status', 'project', 'providers']);
});
