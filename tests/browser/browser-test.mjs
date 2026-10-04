import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '@playwright/test';

// These are browser acceptance checks, not a replacement for the independent
// partition oracle. All searches use the genuine worker except the explicitly
// named incomplete-result UI check below. Never disable the Chromium sandbox.
const baseURL = process.env.BASE_URL || 'http://127.0.0.1:4173/';
const artifactDir = path.resolve(process.env.BROWSER_ARTIFACT_DIR || 'test-results/browser');
const appFile = path.resolve(process.env.APP_FILE || 'dist/index.html');
const results = [];
const pageErrors = [];
await mkdir(artifactDir, { recursive: true });
let browser;

const sample = (seconds = 60) => ({
  modelVersion: 1,
  roles: ['A', 'B', 'C', 'D'].map(id => ({ id, name: `Role ${id}` })),
  appearances: [
    { id: 'a1', roleId: 'A', start: 0, end: 60, cue: 'Opening' },
    { id: 'a2', roleId: 'A', start: 300, end: 360, cue: 'Return' },
    { id: 'b1', roleId: 'B', start: 90, end: 150, cue: 'Entrance B' },
    { id: 'c1', roleId: 'C', start: 180, end: 240, cue: 'Entrance C' },
    { id: 'd1', roleId: 'D', start: 120, end: 210, cue: 'Entrance D' },
  ],
  defaultChangeover: 20,
  overrides: [{ from: 'B', to: 'C', seconds }],
  mustShare: [], neverShare: [], targetTracks: 2,
});
const hostile = JSON.parse(await readFile(new URL('../../fixtures/consumer-adversarial.json', import.meta.url), 'utf8'));
const hostileCue = hostile.appearances.find(a => a.id === 'B1').cue;
const canonicalNewlines = text => text.replace(/\r\n?/g, '\n');

async function report(status, extra = {}) {
  await writeFile(path.join(artifactDir, 'results.json'), JSON.stringify({
    status, sandbox: true, baseURL, genuineWorkerExcept: 'incomplete-result-ui-only',
    testsRun: results.length, passed: results.filter(r => r.status === 'passed').length,
    failed: results.filter(r => r.status === 'failed').length,
    skipped: results.filter(r => r.status === 'skipped').length,
    results, pageErrors, ...extra,
  }, null, 2) + '\n');
}
try {
  browser = await chromium.launch({ headless: true, chromiumSandbox: true,
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) });
} catch (error) {
  await report('blocked', { stage: 'launch', error: error.stack });
  console.error('Browser launch blocked; no scenarios ran. Chromium sandbox remains enabled.');
  throw error;
}

async function realWorkerProbe(page) {
  await page.addInitScript(() => {
    const NativeWorker = window.Worker;
    window.__workerProbe = { created: 0, posted: 0, received: 0, terminated: 0 };
    window.Worker = class extends NativeWorker {
      constructor(...args) {
        super(...args);
        window.__workerProbe.created++;
        this.addEventListener('message', () => window.__workerProbe.received++);
      }
      postMessage(...args) { window.__workerProbe.posted++; return super.postMessage(...args); }
      terminate() { window.__workerProbe.terminated++; return super.terminate(); }
    };
  });
}
async function open(page) {
  await page.goto(baseURL);
  await page.locator('#solve').waitFor({ state: 'visible' });
  assert.equal(await page.locator('html').getAttribute('lang'), 'en');
}
async function noResult(page) {
  assert.equal(await page.locator('#results').isVisible(), false, 'No stale or uncertified result');
  const download = page.locator('#download');
  assert.ok(!(await download.isVisible()) || await download.isDisabled(), 'No export is available');
}
async function solve(page, minimum) {
  await page.locator('#solve').click();
  if (minimum === null) {
    await page.waitForFunction(() => /infeasible|no feasible/i.test(document.querySelector('#status').textContent));
    await noResult(page);
  } else {
    await page.locator('#results').waitFor({ state: 'visible', timeout: 15_000 });
    assert.equal(await page.locator('#results .track').count(), minimum, 'Exact minimum track count');
    assert.match(await page.locator('#result-summary').innerText(), new RegExp(`\\b${minimum}\\b`));
    assert.equal(await page.locator('#download').isDisabled(), false);
  }
  assert.equal(await page.locator('#solve').isDisabled(), false, 'Search control restored');
}
async function chooseRecipe(page, file) {
  const pending = page.waitForEvent('filechooser');
  await page.locator('#import').click();
  const chooser = await pending;
  await chooser.setFiles(file);
}
async function recipe(page, model) {
  await chooseRecipe(page, { name: 'recipe.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(model)) });
  const roles = [...model.roles].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0).map(r => [r.id, canonicalNewlines(r.name ?? r.id)]);
  const appearances = [...model.appearances].sort((a, b) => a.start - b.start || a.end - b.end || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map(a => [a.id, a.roleId, String(a.start), String(a.end), canonicalNewlines(a.cue ?? '')]);
  // Wait for the imported controls themselves. A prior "loaded" status alone
  // must not let an asynchronous file read appear complete prematurely.
  await page.waitForFunction(expected => {
    const values = selector => [...document.querySelectorAll(selector)].map(row => [...row.querySelectorAll('input, textarea, select')].map(control => control.value));
    return JSON.stringify(values('#roles-body tr')) === JSON.stringify(expected.roles)
      && JSON.stringify(values('#appearances-body tr')) === JSON.stringify(expected.appearances)
      && document.querySelector('#default').value === String(expected.defaultChangeover)
      && document.querySelector('#target').value === String(expected.targetTracks);
  }, { roles, appearances, defaultChangeover: model.defaultChangeover, targetTracks: model.targetTracks });
  assert.match(await page.locator('#status').innerText(), /imported|loaded/i);
}

async function download(page, filename) {
  const pending = page.waitForEvent('download');
  await page.locator('#download').click();
  const item = await pending;
  assert.match(item.suggestedFilename(), /\.zip$/i);
  const dest = path.join(artifactDir, filename);
  await item.saveAs(dest);
  assert.equal(await item.failure(), null);
  assert.ok((await stat(dest)).size > 500, 'Actual browser ZIP download is nonempty');
  return dest;
}
function extractReview(zip, directory) {
  // Python's standard ZIP parser consumes the actual browser bytes. The separate
  // consumer job validates every CSV cell and imports those bytes in LibreOffice.
  execFileSync('python3', ['-c', `import pathlib,sys,zipfile
out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.testzip() is None
 for name in ('run-sheet.html','recipe.json'):
  (out/name).write_bytes(z.read(name))
`, zip, directory], { stdio: 'inherit' });
  return path.join(directory, 'run-sheet.html');
}
async function noPageOverflow(page) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth,
    overflowing: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0, 20).map(el => {
      const box = el.getBoundingClientRect();
      const parent = el.parentElement;
      return { tag: el.tagName, id: el.id, class: el.className, left: Math.round(box.left), right: Math.round(box.right), width: Math.round(box.width), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, overflowX: getComputedStyle(el).overflowX, parent: parent?.className };
    }) }));
  assert.ok(sizes.width <= sizes.viewport + 1, `Page overflow: ${sizes.width}px at ${sizes.viewport}px; ${JSON.stringify(sizes.overflowing)}`);
}
async function inputsSnapshot(page) {
  return page.locator('#roles-body input, #roles-body textarea, #appearances-body input, #appearances-body textarea, #appearances-body select, #default, #target, #overrides, #must-share, #never-share').evaluateAll(nodes => nodes.map(n => n.value));
}
async function test(name, fn, { viewport = { width: 1440, height: 1080 }, offline = false } = {}) {
  const context = await browser.newContext({ viewport, acceptDownloads: true, reducedMotion: 'reduce' });
  if (offline) await context.setOffline(true);
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const output = await fn(page, context);
    assert.deepEqual(errors, [], 'No uncaught browser errors');
    results.push({ name, status: output?.skip ? 'skipped' : 'passed', ...(output || {}) });
    console.log(`${output?.skip ? 'SKIP' : 'PASS'} ${name}${output?.skip ? ': ' + output.skip : ''}`);
  } catch (error) {
    results.push({ name, status: 'failed', error: error.stack });
    await page.screenshot({ path: path.join(artifactDir, `${name}-failure.png`), fullPage: true }).catch(() => {});
    console.error(`FAIL ${name}\n${error.stack}`);
  } finally {
    pageErrors.push(...errors.map(error => ({ test: name, error })));
    await context.close();
    await report('running');
  }
}

try {
  await test('english-keyboard-skip-add-rows', async page => {
    await open(page);
    assert.equal(await page.getByRole('columnheader', { name: 'Remove', exact: true }).count(), 2, 'English remove-column headers have accessible names');
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('.skip').evaluate(n => n === document.activeElement), true);
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#planner').evaluate(n => n === document.activeElement), true);
    assert.equal(await page.locator('#planner').getAttribute('tabindex'), '-1');
    const roles = await page.locator('#roles-body tr').count();
    await page.locator('#add-role').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#roles-body tr').count(), roles + 1);
    assert.equal(await page.locator('#roles-body tr').last().evaluate(n => n.contains(document.activeElement)), true);
    const appearances = await page.locator('#appearances-body tr').count();
    await page.locator('#add-appearance').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#appearances-body tr').count(), appearances + 1);
    assert.equal(await page.locator('#appearances-body tr').last().evaluate(n => n.contains(document.activeElement)), true);
  });

  await test('genuine-worker-three-tracks-and-download', async page => {
    await realWorkerProbe(page);
    await open(page);
    await page.locator('#demo60').click();
    await solve(page, 3);
    const probe = await page.evaluate(() => window.__workerProbe);
    assert.equal(probe.created, 1);
    assert.equal(probe.posted, 1);
    assert.ok(probe.received >= 1, 'A genuine worker delivered its response');
    const zip = await download(page, 'downloaded.zip');
    extractReview(zip, path.join(artifactDir, 'downloaded'));
    execFileSync('python3', ['tests/consume.py', '--bundle', zip, '--out', path.join(artifactDir, 'consumer-default'), '--skip-libreoffice'], { stdio: 'inherit' });
    await page.screenshot({ path: path.join(artifactDir, 'desktop-three-tracks.png'), fullPage: true });
  });

  await test('threshold-equality-one-second-and-direction', async page => {
    await open(page);
    await page.locator('#demo30').click();
    await solve(page, 2);
    await page.locator('#overrides').fill('B,C,31');
    await solve(page, 3);
    await page.locator('#overrides').fill('C,B,60');
    await solve(page, 2);
  });

  await test('edits-invalidate-witness-and-reset', async page => {
    await open(page);
    await solve(page, 3);
    await page.locator('#roles-body tr').first().locator('input, textarea').nth(1).fill('Changed role');
    await noResult(page);
    await solve(page, 3);
    await page.locator('#target').fill('4');
    await noResult(page);
    await page.locator('#reset').click();
    await noResult(page);
    assert.equal(await page.locator('#roles-body tr').count(), 4);
    await solve(page, 3);
  });

  await test('genuine-worker-cancel-and-repeated-search', async page => {
    await realWorkerProbe(page);
    await open(page);
    // Two clicks in one task guarantee Cancel runs before the worker's result
    // event can be delivered, without substituting a delayed/fake worker.
    await page.evaluate(() => { document.querySelector('#solve').click(); document.querySelector('#cancel').click(); });
    const cancelled = await page.evaluate(() => window.__workerProbe);
    assert.equal(cancelled.created, 1);
    assert.equal(cancelled.posted, 1);
    assert.equal(cancelled.terminated, 1, 'Cancel actually terminates the native worker');
    assert.match(await page.locator('#status').innerText(), /cancel|incomplete/i);
    await noResult(page);
    await solve(page, 3);
    await page.locator('#demo30').click();
    await solve(page, 2);
    await solve(page, 2);
    const repeated = await page.evaluate(() => window.__workerProbe);
    assert.equal(repeated.created, 4);
    assert.equal(repeated.posted, 4);
    assert.equal(await page.locator('#results .track').count(), 2, 'Repeated search replaces its predecessor');
  });

  await test('intermediate-role-nonhereditary-feasibility', async page => {
    await open(page);
    const model = { roles: [{ id: 'A', name: 'A' }, { id: 'C', name: 'C' }],
      appearances: [{ id: 'a', roleId: 'A', start: 0, end: 10, cue: '' }, { id: 'c', roleId: 'C', start: 50, end: 60, cue: '' }],
      defaultChangeover: 0, overrides: [{ from: 'A', to: 'C', seconds: 100 }], mustShare: [['A', 'C']], neverShare: [], targetTracks: 1 };
    await recipe(page, model);
    await solve(page, null);
    model.roles.splice(1, 0, { id: 'B', name: 'B' });
    model.appearances.splice(1, 0, { id: 'b', roleId: 'B', start: 20, end: 30, cue: '' });
    await recipe(page, model);
    await solve(page, 1);
    assert.equal(await page.locator('.transition-table tbody tr').count(), 2);
  });

  await test('conflicting-group-rules-no-export', async page => {
    await open(page);
    const model = sample(30);
    model.mustShare = [['A', 'B'], ['B', 'C']];
    model.neverShare = [['A', 'C']];
    await recipe(page, model);
    await solve(page, null);
  });

  await test('blank-number-is-not-zero', async page => {
    await realWorkerProbe(page);
    await open(page);
    for (const selector of ['#default', '#target', '#appearances-body input[type="number"]']) {
      const input = page.locator(selector).first();
      const old = await input.inputValue();
      await input.fill('');
      await page.locator('#solve').click();
      await noResult(page);
      assert.equal(await page.evaluate(() => window.__workerProbe.created), 0, 'Invalid numeric input must not reach solver');
      await input.fill(old);
    }
  });

  await test('malformed-and-oversize-import-transactional', async page => {
    await open(page);
    const before = await inputsSnapshot(page);
    for (const [name, buffer] of [['malformed.json', Buffer.from('{broken')], ['oversize.json', Buffer.alloc(2 * 1024 * 1024, 32)]]) {
      await chooseRecipe(page, { name, mimeType: 'application/json', buffer });
      await page.waitForFunction(() => /rejected|invalid|error|large|size|JSON|parse/i.test(document.querySelector('#status').textContent));
      assert.deepEqual(await inputsSnapshot(page), before, 'Rejected import preserves editable model');
      await noResult(page);
    }
  });

  await test('schema-and-self-override-import-rejected', async page => {
    await open(page);
    const before = await inputsSnapshot(page);
    const models = [sample(30), sample(30)];
    models[0].roles[1].id = 'A';
    models[1].overrides = [{ from: 'A', to: 'A', seconds: 1 }];
    for (const model of models) {
      await chooseRecipe(page, { name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(model)) });
      await page.waitForFunction(() => /rejected|invalid|error|duplicate|self|same/i.test(document.querySelector('#status').textContent));
      assert.deepEqual(await inputsSnapshot(page), before);
      await noResult(page);
    }
  });

  await test('recipe-import-invalidates-existing-result', async page => {
    await open(page);
    await solve(page, 3);
    await recipe(page, sample(30));
    await noResult(page);
    await solve(page, 2);
    const before = await inputsSnapshot(page);
    await page.locator('#language').click();
    assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
    assert.deepEqual(await inputsSnapshot(page), before, 'Language switching preserves entered model');
    await page.locator('#language').click();
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
  });

  await test('deferred-import-stale-completion-and-same-file-reselect', async page => {
    await realWorkerProbe(page);
    await page.addInitScript(() => {
      const nativeText = File.prototype.text;
      window.__deferredFileReads = [];
      // Only file-read settlement timing is controlled. Successful reads still
      // use native File.text; no solver or worker response is substituted.
      File.prototype.text = function () {
        const file = this;
        return new Promise((resolve, reject) => {
          window.__deferredFileReads.push({ name: file.name, release: async outcome => {
            if (outcome === 'reject') reject(new Error('Deferred test read failure'));
            else resolve(await nativeText.call(file));
            // Let the application's awaiting change handler handle settlement.
            await new Promise(done => setTimeout(done, 0));
          } });
        });
      };
    });
    await open(page);
    const sameFile = { name: 'same-recipe.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(sample(30))) };
    let reads = 0;
    for (const action of ['reset', 'input-change', 'new-search']) {
      for (const outcome of ['resolve', 'reject']) {
        await page.locator('#demo60').click();
        await chooseRecipe(page, sameFile);
        reads++;
        await page.waitForFunction(count => window.__deferredFileReads.length === count, reads);
        assert.equal(await page.locator('#recipe-file').inputValue(), '', 'Selection is cleared immediately, even while its read is pending');
        if (action === 'reset') await page.locator('#reset').click();
        else if (action === 'input-change') await page.locator('#target').fill('4');
        else await solve(page, 3);
        const currentInputs = await inputsSnapshot(page);
        const currentStatus = await page.locator('#status').innerText();
        const currentSummary = await page.locator('#result-summary').innerText();
        await page.evaluate(async ({ index, outcome }) => {
          await window.__deferredFileReads[index].release(outcome);
        }, { index: reads - 1, outcome });
        assert.deepEqual(await inputsSnapshot(page), currentInputs, `${action}/${outcome}: stale read must not replace the newer model`);
        assert.equal(await page.locator('#status').innerText(), currentStatus, `${action}/${outcome}: stale read must not replace newer status`);
        if (action === 'new-search') {
          assert.equal(await page.locator('#results').isVisible(), true);
          assert.equal(await page.locator('#results .track').count(), 3);
          assert.equal(await page.locator('#download').isDisabled(), false);
          assert.equal(await page.locator('#result-summary').innerText(), currentSummary);
        } else await noResult(page);
        assert.equal(await page.locator('#recipe-file').inputValue(), '', 'Stale completion leaves the same file reselectable');
      }
    }
    // Reselect the identical file once more without invalidating it. A genuine
    // successful import and worker search must still work after all six races.
    await chooseRecipe(page, sameFile);
    reads++;
    await page.waitForFunction(count => window.__deferredFileReads.length === count, reads);
    assert.equal(await page.locator('#recipe-file').inputValue(), '');
    await page.evaluate(async index => window.__deferredFileReads[index].release('resolve'), reads - 1);
    await page.waitForFunction(() => /Recipe imported/.test(document.querySelector('#status').textContent));
    assert.equal(await page.locator('#overrides').inputValue(), 'B,C,30');
    assert.equal(await page.locator('#roles-body textarea').first().inputValue(), 'Role A');
    await solve(page, 2);
    const workerProbe = await page.evaluate(() => window.__workerProbe);
    assert.equal(workerProbe.created, 3, 'Two newer searches and the final imported search use native workers');
    assert.equal(workerProbe.posted, 3);
    return { deferredReadCases: 6, sameFileSelections: reads, solver: 'genuine Worker' };
  });

  await test('hostile-unicode-text-real-zip', async page => {
    await open(page);
    await recipe(page, hostile);
    await solve(page, 2);
    assert.ok((await page.locator('#results').innerText()).includes(hostile.roles[0].name));
    assert.equal(await page.locator('#appearances-body textarea').evaluateAll((nodes, cue) => nodes.some(n => n.value === cue), hostileCue), true, 'Cue editor retains the full hostile multiline text');
    assert.equal(await page.locator('#results img').count(), 0);
    assert.equal(await page.evaluate(() => window.__injected), undefined);
    const zip = await download(page, 'hostile-text.zip');
    const dir = path.join(artifactDir, 'hostile-text');
    extractReview(zip, dir);
    execFileSync('python3', ['tests/consume.py', '--bundle', zip, '--out', path.join(artifactDir, 'consumer-hostile'), '--skip-libreoffice'], { stdio: 'inherit' });
    const exported = JSON.parse(await readFile(path.join(dir, 'recipe.json'), 'utf8'));
    assert.equal(exported.roles.find(r => r.id === 'A').name, '=1+1', 'Canonical JSON preserves raw text');
    assert.equal(exported.appearances.find(a => a.id === 'B1').cue, hostileCue);
  });

  await test('crlf-and-cr-input-canonicalized-to-lf', async page => {
    await open(page);
    const model = sample(30);
    model.roles[0].name = 'Gate\r\nKeeper\rFinal\nLine';
    model.roles[1].name = '衣装\r\n変更\r日本語';
    model.appearances[0].cue = 'Opening\r\nBefore the bell\rAfter the bell\nEnd';
    model.appearances[2].cue = '引用, "quoted"\r\n第二行\r第三行';
    await recipe(page, model);
    assert.equal(await page.locator('#roles-body textarea').first().inputValue(), canonicalNewlines(model.roles[0].name));
    assert.equal(await page.locator('#appearances-body textarea').first().inputValue(), canonicalNewlines(model.appearances[0].cue));
    await solve(page, 2);
    const zip = await download(page, 'line-endings.zip');
    const dir = path.join(artifactDir, 'line-endings');
    extractReview(zip, dir);
    const exported = JSON.parse(await readFile(path.join(dir, 'recipe.json'), 'utf8'));
    for (const role of model.roles) {
      const actual = exported.roles.find(item => item.id === role.id).name;
      assert.equal(actual, canonicalNewlines(role.name), `Exported role ${role.id} uses canonical LF`);
      assert.equal(actual.includes('\r'), false);
    }
    for (const appearance of model.appearances) {
      const actual = exported.appearances.find(item => item.id === appearance.id).cue;
      assert.equal(actual, canonicalNewlines(appearance.cue), `Exported cue ${appearance.id} uses canonical LF`);
      assert.equal(actual.includes('\r'), false);
    }
    execFileSync('python3', ['tests/consume.py', '--bundle', zip, '--out', path.join(artifactDir, 'consumer-line-endings'), '--skip-libreoffice'], { stdio: 'inherit' });
    return { inputLineEndings: ['CRLF', 'CR', 'LF'], canonicalLineEnding: 'LF', download: 'line-endings.zip' };
  });

  await test('japanese-mobile-390', async page => {
    await open(page);
    await page.locator('#language').click();
    assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
    await page.locator('#demo30').click();
    await solve(page, 2);
    assert.match(await page.locator('body').innerText(), /役|登場|トラック/);
    const hiddenHeaders = await page.locator('.table-scroll th .sr-only').evaluateAll(labels => labels.map(label => ({
      text: label.textContent, contained: label.offsetParent === label.closest('th'),
      anchorPosition: getComputedStyle(label.closest('th')).position,
    })));
    assert.equal(hiddenHeaders.length, 2, 'Both remove-column headers retain their accessible labels');
    assert.ok(hiddenHeaders.every(label => label.text === '削除' && label.contained && label.anchorPosition === 'relative'), 'Offscreen accessible labels are positioned inside their table header, not the document');
    const headerDiagnostics = await page.locator('th[data-i18n-label="remove"]').evaluateAll(headers => headers.map(header => ({
      html: header.outerHTML, role: header.getAttribute('role'), scope: header.scope,
      ariaLabel: header.getAttribute('aria-label'), text: header.textContent,
      display: getComputedStyle(header).display, visibility: getComputedStyle(header).visibility,
    })));
    assert.equal(await page.getByRole('columnheader', { name: '削除', exact: true }).count(), 2, `Accessible remove headers: ${JSON.stringify(headerDiagnostics)}`);
    assert.ok(headerDiagnostics.every(header => header.scope === 'col' && header.role === 'columnheader' && header.ariaLabel === '削除'), 'Explicit column-header semantics and localized labels are retained');
    await noPageOverflow(page);
    await page.screenshot({ path: path.join(artifactDir, 'japanese-mobile-390.png'), fullPage: true });
    for (const selector of ['.appearances-table', '.transition-table']) {
      const bounds = await page.locator(selector).first().evaluate(table => {
        const port = table.parentElement;
        port.scrollLeft = port.scrollWidth;
        const last = table.querySelector('tr:last-child td:last-child');
        return { scrollable: port.scrollWidth > port.clientWidth, moved: port.scrollLeft > 0, endVisible: last.getBoundingClientRect().right <= port.getBoundingClientRect().right + 2 };
      });
      assert.equal(bounds.scrollable, true, `${selector} keeps a horizontal scrollport`);
      assert.equal(bounds.moved, true, `${selector} offscreen columns are reachable`);
      assert.equal(bounds.endVisible, true, `${selector} last column can be viewed`);
    }
    await noPageOverflow(page);
    await page.screenshot({ path: path.join(artifactDir, 'japanese-mobile-390-scrolled.png'), fullPage: true });
  }, { viewport: { width: 390, height: 844 } });

  await test('maximum-128-appearances-single-role', async page => {
    await open(page);
    const model = { roles: [{ id: 'A', name: 'Repeated role' }],
      appearances: Array.from({ length: 128 }, (_, i) => ({ id: `a${i}`, roleId: 'A', start: i * 10, end: i * 10 + 10, cue: `Cue ${i + 1}` })),
      defaultChangeover: 86_400, overrides: [], mustShare: [], neverShare: [], targetTracks: 1 };
    await recipe(page, model);
    await solve(page, 1);
    assert.equal(await page.locator('.transition-table tbody tr').count(), 127, 'Every consecutive same-role appearance is certified');
  });

  await test('incomplete-result-ui-only', async page => {
    // Explicit fault injection tests presentation/export suppression only. Engine
    // operation/time-budget behavior is covered by the genuine core tests.
    await page.addInitScript(() => {
      window.Worker = class {
        postMessage() { setTimeout(() => this.onmessage?.({ data: { type: 'result', result: { status: 'incomplete', minimumTracks: null, tracks: [] } } }), 0); }
        terminate() {}
      };
    });
    await open(page);
    await page.locator('#solve').click();
    await page.waitForFunction(() => /incomplete|budget|limit/i.test(document.querySelector('#status').textContent));
    await noResult(page);
    assert.equal(await page.locator('#solve').isDisabled(), false);
    assert.doesNotMatch(await page.locator('#status').innerText(), /minimum\s*[:=]?\s*\d|infeasible/i);
    return { evidenceScope: 'Injected incomplete result tests UI only; not an engine timeout' };
  });

  async function standalone(page, context, prefix, expectedText) {
    // This is a fresh browser context with no prior app document or origin state.
    await context.setOffline(true);
    const requests = [];
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    const file = path.join(artifactDir, prefix, 'run-sheet.html');
    await page.goto(pathToFileURL(file).href);
    await page.locator('body').waitFor({ state: 'visible' });
    await page.evaluate(() => document.fonts.ready);
    const body = await page.locator('body').textContent();
    for (const value of expectedText) assert.ok(body.includes(value), `Standalone document retains ${value.slice(0, 60)}`);
    assert.equal(await page.locator('script').count(), 0, 'Standalone review sheet is script-free');
    assert.equal(await page.locator('img').count(), 0, 'No text is interpreted as image markup');
    assert.deepEqual(requests, [], 'Standalone sheet makes no HTTP requests');
    await page.screenshot({ path: path.join(artifactDir, `${prefix}-standalone-desktop.png`), fullPage: true });
    await page.pdf({ path: path.join(artifactDir, `${prefix}-A4.pdf`), format: 'A4', printBackground: true, preferCSSPageSize: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await noPageOverflow(page);
    await page.screenshot({ path: path.join(artifactDir, `${prefix}-standalone-mobile.png`), fullPage: true });
  }
  await test('standalone-default-fresh-context-print-mobile', (page, context) => standalone(page, context, 'downloaded', ['A', 'B', 'C', 'D']));
  await test('standalone-hostile-fresh-context-print-mobile', (page, context) => standalone(page, context, 'hostile-text', [hostile.roles[0].name, hostile.roles[1].name, hostileCue]));

  await test('offline-file-app-genuine-blob-worker', async (page, context) => {
    await context.setOffline(true);
    await realWorkerProbe(page);
    await page.goto(pathToFileURL(appFile).href);
    // A platform-level probe is separate from the product. Only an independently
    // demonstrated unsupported file:// Blob Worker is a skip; product failures fail.
    const support = await page.evaluate(() => new Promise(resolve => {
      let worker, url;
      const timer = setTimeout(() => finish({ supported: false, reason: 'Platform Blob Worker probe timed out' }), 3000);
      function finish(result) { clearTimeout(timer); worker?.terminate(); if (url) URL.revokeObjectURL(url); resolve(result); }
      try {
        url = URL.createObjectURL(new Blob(['postMessage("ready")'], { type: 'text/javascript' }));
        worker = new Worker(url);
        worker.onmessage = event => finish({ supported: event.data === 'ready' });
        worker.onerror = event => { event.preventDefault(); finish({ supported: false, reason: event.message || 'Platform rejects file Blob Worker' }); };
      } catch (error) { finish({ supported: false, reason: error.message }); }
    }));
    if (!support.supported) return { skip: support.reason || 'Platform file Blob Worker unsupported' };
    await page.locator('#demo30').click();
    await solve(page, 2);
    assert.ok((await page.evaluate(() => window.__workerProbe)).received >= 2, 'Platform probe and real app worker returned messages');
    await page.screenshot({ path: path.join(artifactDir, 'offline-file-app.png'), fullPage: true });
  });
} finally {
  await browser.close();
}
const failed = results.some(r => r.status === 'failed');
await report(failed ? 'failed' : 'passed');
assert.equal(results.length, 20, 'All authored browser scenarios ran');
if (failed) process.exitCode = 1;
