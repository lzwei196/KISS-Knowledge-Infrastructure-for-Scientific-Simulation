const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.resolve(__dirname, '../../kiss_cli/web/ki-scope.js'), 'utf8');
const scope = 'a'.repeat(32);

function browser() {
  const calls = [];
  const listeners = {};
  const location = new URL(`http://127.0.0.1:8799/setup?model=WOFOST&library_scope=${scope}`);
  const window = {fetch: async (...args) => { calls.push(args); return {ok: true}; }};
  const document = {addEventListener: (name, callback) => { listeners[name] = callback; }};
  const context = vm.createContext({window, document, location, URL, URLSearchParams, Headers});
  vm.runInContext(script, context);
  return {window, calls, listeners};
}

test('same-origin setup request carries the opaque selection and preserves the request', async () => {
  const {window, calls} = browser();
  await window.fetch('/api/setup-agent', {method: 'POST', body: '{}', headers: {'Content-Type': 'application/json'}});
  assert.equal(calls[0][1].headers.get('X-GeoForge-KI-Scope'), scope);
  assert.equal(calls[0][1].headers.get('Content-Type'), 'application/json');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].body, '{}');
});

test('another saved project is resolved by the server instead of the current tab scope', async () => {
  const {window, calls} = browser();
  await window.fetch('/api/session/0123456789ab/chat', {method: 'POST'});
  assert.equal(calls[0][1].headers, undefined);
});

test('scope is never sent to another origin or non-API resource', async () => {
  const {window, calls} = browser();
  await window.fetch('https://example.org/api/setup-agent');
  await window.fetch('/logo.svg');
  assert.equal(calls[0][1], undefined);
  assert.equal(calls[1][1], undefined);
});

test('project switching clears or replaces scope without persisting it across tabs', async () => {
  const {window, calls} = browser();
  window.GeoForgeKIScope.set('');
  await window.fetch('/api/status');
  assert.equal(calls[0][1], undefined);
  window.GeoForgeKIScope.set('b'.repeat(32));
  await window.fetch('/api/models');
  assert.equal(calls[1][1].headers.get('X-GeoForge-KI-Scope'), 'b'.repeat(32));
  assert.equal(browser().window.GeoForgeKIScope.get(), scope);
});

test('Setup, Library and project links retain the selection', () => {
  const {window} = browser();
  for (const target of ['/library', '/setup?model=WOFOST', '/?session=0123456789ab']) {
    const u = new URL(window.GeoForgeKIScope.url(target), 'http://127.0.0.1:8799');
    assert.equal(u.searchParams.get('library_scope'), scope);
  }
});

test('clearing the selected library removes stale scope from old links', () => {
  const {window} = browser();
  window.GeoForgeKIScope.set('');
  const url = window.GeoForgeKIScope.url(`/library?library_scope=${scope}&updates=1`);
  assert.equal(url, '/library?updates=1');
});

test('ordinary app-to-Library and Library-to-setup links retain scope on click', () => {
  const {listeners} = browser();
  for (const target of ['/library', '/setup?model=WOFOST', '/']) {
    const link = {href: `http://127.0.0.1:8799${target}`};
    listeners.click({target: {closest: () => link}});
    assert.equal(new URL(link.href, 'http://127.0.0.1:8799').searchParams.get('library_scope'), scope);
  }
});

test('a link to a different saved project does not inherit current scope', () => {
  const {listeners} = browser();
  const link = {href: 'http://127.0.0.1:8799/?session=0123456789ab'};
  listeners.click({target: {closest: () => link}});
  assert.equal(link.href, 'http://127.0.0.1:8799/?session=0123456789ab');
});

test('a slower old scoped catalogue cannot overwrite a newer opened global project', async () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../../kiss_cli/web/app.html'), 'utf8');
  const start = html.indexOf('async function openSession(');
  const end = html.indexOf('  rememberSessionSummary(CUR);', start);
  // Execute the shipped fetch/binding/cache portion; unrelated DOM painting
  // follows the accepted CUR assignment and does not control this race.
  const shipped = html.slice(start, end) + 'return CUR;\n}';
  let active = '', resolveA, resolveB;
  const catalogueA = new Promise(resolve => {resolveA = resolve;});
  const catalogueB = new Promise(resolve => {resolveB = resolve;});
  const response = value => ({ok: true, json: async () => value});
  const context = vm.createContext({OPEN_SEQ: 0, CUR: null, ACTION_SESSION: null,
    MODELS: [], STATUS: {}, STATUS_REFRESHING: null, LAST_STATUS_CHECK: 0,
    GeoForgeKIScope: {get: () => active, set: value => {active = value;}},
    refreshMachineStatus: async () => {},
    fetch: async url => {
      if (url === '/api/session/A') return response({id: 'A', library_scope: scope});
      if (url === '/api/session/B') return response({id: 'B'});
      if (url === '/api/models') return active ? catalogueA : catalogueB;
      if (url === '/api/status') return response({});
      throw new Error(url);
    }});
  vm.runInContext(shipped, context);
  const old = context.openSession('A');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(active, scope);
  const current = context.openSession('B');
  await new Promise(resolve => setImmediate(resolve));
  resolveB(response([{name: 'GLOBAL'}]));
  await current;
  resolveA(response([{name: 'SCOPED'}]));
  await old;
  assert.equal(context.CUR.id, 'B');
  assert.equal(context.MODELS[0].name, 'GLOBAL');
  assert.equal(active, '');
});

test('overlapping opens in the same new scope still load its catalogue and installation status', async () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../../kiss_cli/web/app.html'), 'utf8');
  const start = html.indexOf('async function openSession(');
  const end = html.indexOf('  rememberSessionSummary(CUR);', start);
  const shipped = html.slice(start, end) + 'return CUR;\n}';
  let active = '', finishA, finishB, catalogueCalls = 0;
  const catalogueA = new Promise(resolve => {finishA = resolve;});
  const catalogueB = new Promise(resolve => {finishB = resolve;});
  const response = value => ({ok: true, json: async () => value});
  const context = vm.createContext({OPEN_SEQ: 0, CUR: null, ACTION_SESSION: null,
    MODELS: [{name: 'GLOBAL'}], STATUS: {GLOBAL: {}}, LAST_STATUS_CHECK: Date.now(),
    GeoForgeKIScope: {get: () => active, set: value => {active = value;}},
    fetch: async url => {
      if (url.startsWith('/api/session/')) return response({id: url.at(-1), library_scope: scope});
      if (url === '/api/models') return ++catalogueCalls === 1 ? catalogueA : catalogueB;
      if (url === '/api/status') return response({SCOPED: {can_run: false}});
      throw new Error(url);
    }});
  vm.runInContext(shipped, context);
  const old = context.openSession('A');
  await new Promise(resolve => setImmediate(resolve));
  const current = context.openSession('B');
  await new Promise(resolve => setImmediate(resolve));
  finishB(response([{name: 'SCOPED'}]));
  await current;
  finishA(response([{name: 'STALE'}]));
  await old;
  assert.equal(context.CUR.id, 'B');
  assert.equal(context.MODELS[0].name, 'SCOPED');
  assert.equal(context.STATUS.SCOPED.can_run, false);
  assert.equal(context.STATUS.GLOBAL, undefined);
});

test('a pending global update watcher cannot overwrite a newly selected project scope', async () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../../kiss_cli/web/app.html'), 'utf8');
  const start = html.indexOf('async function watchKiUpdates(');
  const end = html.indexOf('function workLabel(', start);
  let active = '', release;
  const pending = new Promise(resolve => {release = resolve;});
  const context = vm.createContext({KI_UPDATE_REVISION: 'old', KI_UPDATE_REFRESHING: null,
    KI_UPDATE_POLL: null, KI_UPDATE_NOTICE: '', MODELS: [{name: 'GLOBAL'}], STATUS: {},
    GeoForgeKIScope: {get: () => active},
    $: () => ({classList: {remove() {}, add() {}}}),
    clearTimeout() {}, setTimeout: () => 1,
    kiUpdateReadJSON: async url => {
      if (url === '/api/ki-updates') return {state: 'updated', active_revision: 'new'};
      await pending;
      return url === '/api/models' ? [{name: 'OLD_SCOPE'}] : {OLD_SCOPE: {}};
    }});
  vm.runInContext(html.slice(start, end), context);
  const checking = context.watchKiUpdates();
  await new Promise(resolve => setImmediate(resolve));
  active = scope;
  context.MODELS = [{name: 'SCOPED'}];
  context.STATUS = {SCOPED: {}};
  release();
  await checking;
  assert.equal(context.MODELS[0].name, 'SCOPED');
  assert.ok(context.STATUS.SCOPED);
  assert.equal(context.KI_UPDATE_REVISION, 'old');
});

test('all affected pages load the scope helper and their inline scripts compile', () => {
  for (const name of ['setup', 'library', 'app']) {
    const html = fs.readFileSync(path.resolve(__dirname, `../../kiss_cli/web/${name}.html`), 'utf8');
    assert.ok(html.includes('<script src="/ki-scope.js"></script>'));
    for (const [, code] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(code);
  }
});
