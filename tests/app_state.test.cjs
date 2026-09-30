// Run with: node --test tests/app_state.test.cjs
// Exercise the real app script with deferred network responses. Plotting and
// layout are stubbed here; the browser smoke check covers their integration.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../app/index.html'), 'utf8');

function element() {
  const classes = new Set();
  let content = '';
  const listeners = {};
  return {
    value: '', style: {}, dataset: {},
    get innerHTML() { return content; },
    set innerHTML(value) { content = value; },
    get textContent() { return content; },
    set textContent(value) { content = value; },
    classList: {
      add: value => classes.add(value), remove: value => classes.delete(value),
      contains: value => classes.has(value),
    },
    addEventListener: (name, callback) => { listeners[name] = callback; },
    click(event = {}) { listeners.click?.({ currentTarget: this, preventDefault() {}, ...event }); },
    querySelectorAll: () => [],
    setAttribute() {}, getAttribute() { return null; },
    getBoundingClientRect: () => ({ left: 0, height: 46 }),
  };
}

function app(search = '') {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const views = ['start', 'mlprimer', 'overview', 'matrix', 'pathway', 'detail', 'dynamics', 'anatomy', 'anatomy3d'];
  const buttons = views.map(view => Object.assign(element(), { dataset: { view } }));
  const jumpLinks = [...html.matchAll(/<a\b[^>]*\bdata-jump="[^"]+"[^>]*>/g)].map(([tag]) => {
    const dataset = Object.fromEntries([...tag.matchAll(/data-([\w-]+)="([^"]*)"/g)]
      .map(([, key, value]) => [key, value]));
    return Object.assign(element(), { dataset });
  });
  buttons[0].classList.add('active');
  const pending = new Map();
  const alerts = [], purged = [], plots = [];
  const context = vm.createContext({
    console, URLSearchParams, setTimeout, clearTimeout, Set,
    location: { search, pathname: '/index.html' },
    history: { replaceState() {} },
    window: { addEventListener() {} },
    requestAnimationFrame() {},
    document: {
      documentElement: element(), getElementById: get,
      addEventListener() {},
      querySelector(selector) {
        if (selector === 'nav button.active') return buttons.find(b => b.classList.contains('active'));
        const view = selector.match(/^nav button\[data-view="([^"]+)"\]$/)?.[1];
        if (view) return buttons.find(b => b.dataset.view === view);
        return get(selector);
      },
      querySelectorAll(selector) {
        if (selector === 'nav button') return buttons;
        if (selector === '.view') return views.map(v => get('view-' + v));
        if (selector === 'a[data-jump]') return jumpLinks;
        return [];
      },
    },
    Plotly: { purge: id => purged.push(id), react: (...args) => plots.push(args) },
    alert: message => alerts.push(message),
    fetch(url) {
      return new Promise((resolve, reject) => {
        const queue = pending.get(url) || [];
        queue.push({ resolve: data => resolve({ ok: true, json: async () => data }), reject });
        pending.set(url, queue);
      });
    },
  });
  vm.runInContext(source, context);
  vm.runInContext('initFilters = () => {}; renderPathwayGraph = () => {}; renderPathsTable = () => {};', context);
  return {
    context, get, alerts, purged, plots, jumpLinks,
    request: url => pending.get(url)?.shift(),
    evaluate: code => vm.runInContext(code, context),
    activeView: () => buttons.find(b => b.classList.contains('active')).dataset.view,
  };
}

function pathway(input, output, bodyid = 42) {
  return {
    input_category: input, output_category: output,
    params: { max_hops: 3, minimum_weight: 1, max_nodes: 150, top_n_paths: 20 },
    nodes: [{ bodyid, name: 'Example neuron', type: 'Example' }], edges: [], paths: [],
  };
}

for (const modality of ['vision', 'olfaction', 'proprioception']) {
  test(`Start Here caption describes the displayed ${modality} seeds`, () => {
    const a = app();
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../app/data/start_animation.json'), 'utf8'));
    const wave = data.waves.find(w => w.modality === modality);
    const canvas = a.get('start-flow-anim');
    canvas.getContext = () => ({ setTransform() {} });
    canvas.clientWidth = 0; // No layout in this harness; exercise the real caption path.
    canvas.clientHeight = 0;
    a.context.window.matchMedia = () => ({ matches: true });
    a.context.initStartAnimation({ ...data, waves: [wave] });
    const caption = a.get('start-anim-origin').textContent;
    const seeds = wave.layer.filter(layer => layer === 0).length;
    if (seeds === 0) {
      assert.match(caption, /No sensory neurons .* shown in this sample/);
      assert.match(caption, /downstream neurons/);
    } else {
      assert.ok(caption.includes(`${seeds} sensory neurons`));
      assert.match(caption, /shown at step 0/);
    }
    assert.doesNotMatch(caption, /no recorded position/);
  });
}

test('the latest pathway selection wins when responses arrive out of order', async () => {
  const a = app();
  const first = a.context.loadPathway('olfaction', 'front_leg');
  const second = a.context.loadPathway('gustation', 'wing');
  a.request('data/pathways/gustation__wing.json').resolve(pathway('gustation', 'wing'));
  await second;
  a.request('data/pathways/olfaction__front_leg.json').resolve(pathway('olfaction', 'front_leg'));
  await first;
  assert.equal(a.get('pathway-select').value, 'gustation__wing');
  assert.equal(a.evaluate('pathwayData.input_category'), 'gustation');
});

test('a failed superseded request does not interrupt the current selection', async () => {
  const a = app();
  const first = a.context.loadPathway('olfaction', 'front_leg');
  const second = a.context.loadPathway('gustation', 'wing');
  a.request('data/pathways/gustation__wing.json').resolve(pathway('gustation', 'wing'));
  await second;
  a.request('data/pathways/olfaction__front_leg.json').reject(new Error('old request failed'));
  await first;
  assert.deepEqual(a.alerts, []);
  const latest = a.context.loadPathway('vision', 'wing');
  a.request('data/pathways/vision__wing.json').reject(new Error('current request failed'));
  await latest;
  assert.deepEqual(a.alerts, ['current request failed']);
});

test('changing pathways clears details and rejects an old morphology response', async () => {
  const a = app();
  a.evaluate('skeletonManifest = { bodyids: [42] }');
  const first = a.context.loadPathway('olfaction', 'front_leg', 42);
  a.request('data/pathways/olfaction__front_leg.json').resolve(pathway('olfaction', 'front_leg'));
  await first;
  assert.match(a.get('detail-standalone').innerHTML, /Example neuron/);
  assert.equal(a.activeView(), 'detail');
  const morphology = a.request('data/skeletons/42.json');
  const second = a.context.loadPathway('vision', 'wing');
  a.request('data/pathways/vision__wing.json').resolve(pathway('vision', 'wing', 99));
  await second;
  assert.equal(a.evaluate('lastSelectedBodyid'), null);
  assert.match(a.get('detail-standalone').textContent, /^Select a neuron/);
  assert.doesNotMatch(a.get('detail-panel').innerHTML, /Example neuron/);
  assert.equal(a.get('detail-standalone').classList.contains('placeholder'), true);
  assert.match(a.get('detail-skeleton-hint').textContent, /^Select a neuron/);
  assert.equal(a.purged.at(-1), 'detail-skeleton-plot');
  morphology.resolve({ bodyid: 42 });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(a.plots, []);
});

for (const view of ['overview', 'pathway', 'detail', 'mlprimer']) {
  test(`a deep link restores ${view} even with a pathway and selected neuron`, async () => {
    const a = app(`?view=${view}&pathway=olfaction__front_leg&bodyid=42`);
    a.request('data/pathways/olfaction__front_leg.json').resolve(pathway('olfaction', 'front_leg'));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(a.activeView(), view);
    assert.equal(a.evaluate('lastSelectedBodyid'), 42);
  });
}

test('the primer example opens its pathway and selected neuron without switching to detail', async () => {
  const a = app();
  a.context.showView('mlprimer');
  const link = a.jumpLinks.find(link => link.dataset.pathway === 'olfaction__front_leg');
  assert.ok(link, 'the example link is present in the real page');
  link.click();
  a.request('data/pathways/olfaction__front_leg.json').resolve(pathway('olfaction', 'front_leg', 10065));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(a.activeView(), 'pathway');
  assert.equal(a.get('pathway-select').value, 'olfaction__front_leg');
  assert.equal(a.evaluate('lastSelectedBodyid'), 10065);
});

test('a modified click on the primer example preserves its native deep link', () => {
  const a = app();
  const link = a.jumpLinks.find(link => link.dataset.pathway === 'olfaction__front_leg');
  for (const modifier of ['metaKey', 'ctrlKey', 'shiftKey', 'altKey']) {
    link.click({ [modifier]: true, preventDefault() { assert.fail('modified click was intercepted'); } });
    assert.equal(a.request('data/pathways/olfaction__front_leg.json'), undefined);
  }
});

for (const success of [true, false]) {
  test(`a pending search refreshes when the index ${success ? 'loads' : 'fails'}`, async () => {
    const a = app();
    a.get('search-modal').classList.add('open');
    a.get('search-input').value = '42';
    a.context.renderSearchResults('42');
    assert.match(a.get('search-results').innerHTML, /Loading search index/);
    const request = a.request('data/search_index.json');
    if (success) {
      request.resolve({ bodyid: [42], type: ['Example'], name: ['Example neuron'], superclass: ['cb_intrinsic'], class: [null], io_role: ['central_processing'], input_category: ['not_input'], output_category: ['not_output'], pathway_key: [null] });
    } else request.reject(new Error('index unavailable'));
    await a.evaluate('searchIndexReady');
    assert.match(a.get('search-results').innerHTML, success ? /Example neuron/ : /not found/);
    assert.doesNotMatch(a.get('search-results').innerHTML, /Loading search index/);
  });
}
