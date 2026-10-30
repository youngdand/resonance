/* Synthetic local integration tests. No account or peer connection is used. */
const assert = require('node:assert/strict');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium, firefox } = require(process.env.RESONANCE_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'resonance-browser-'));
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const seed = spawnSync(
  python,
  [
    '-c',
    `import server,storage
server.init()
storage.settings_patch(server,{'librarySource':'folders','discoveryOnline':False})
with server.db() as c:
 c.executemany('INSERT INTO tracks VALUES (?,?,?,?,?,?,?,?)',[(f'/fixture/{i}.flac','/fixture',f'Artist {i//10:04}',f'Album {i//10:04}',f'Track {i:04}',200,'flac',1000) for i in range(3000)])
`,
  ],
  { cwd: root, env: { ...process.env, RESONANCE_DATA_DIR: data }, encoding: 'utf8' },
);
assert.equal(seed.status, 0, seed.stderr);
const service = spawn(python, ['server.py', '--port', '18765', '--no-browser'], {
  cwd: root,
  env: { ...process.env, RESONANCE_DATA_DIR: data },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serviceLog = '';
service.stdout.on('data', (d) => (serviceLog += d));
service.stderr.on('data', (d) => (serviceLog += d));
const base = 'http://127.0.0.1:18765';
(async () => {
  try {
    for (let n = 0; ; n++) {
      try {
        const r = await fetch(base + '/api/state');
        if (r.ok) break;
      } catch {}
      if (n >= 100 || service.exitCode !== null)
        throw new Error('Local server did not start: ' + serviceLog);
      await new Promise((r) => setTimeout(r, 100));
    }
    const pageData = await (await fetch(base + '/api/library?offset=2900&limit=100')).json();
    assert.equal(pageData.total, 3000);
    assert.equal(pageData.items.length, 100);
    assert.equal(pageData.albums, 300);
    for (const [name, type] of Object.entries({ chromium, firefox })) {
      const browser = await type.launch({
        headless: true,
        timeout: 15000,
        ...(process.env.RESONANCE_DISABLE_FIREFOX_SANDBOX && name === 'firefox'
          ? {
              env: { ...process.env, MOZ_DISABLE_CONTENT_SANDBOX: '1' },
              firefoxUserPrefs: { 'security.sandbox.content.level': 0 },
            }
          : {}),
      });
      try {
        const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
        context.setDefaultTimeout(15000);
        context.setDefaultNavigationTimeout(15000);
        const errors = [],
          remote = [];
        await context.route('**/*', (route) => {
          if (!route.request().url().startsWith(base)) {
            remote.push(route.request().url());
            return route.abort();
          }
          return route.continue();
        });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        console.log(name + ': opening collection');
        await page.goto(base + '/#library');
        await page.waitForFunction(() => S.trackCount === 3000 && S.library.length === 100);
        assert.equal(await page.locator('.results-table tbody tr').count(), 100);
        await page.locator('[data-library-page="100"]').click();
        await page.waitForFunction(
          () => S.libraryOffset === 100 && S.library[0].title === 'Track 0100',
        );
        await page.locator('#libraryQuery').fill('Track 2999');
        await page.locator('#libraryForm').evaluate((form) => form.requestSubmit());
        await page.waitForFunction(() => S.libraryTotal === 1);
        assert.match(await page.locator('#main').innerText(), /Track 2999/);
        // Refreshes preserve keyboard editing and disclosure state.
        await page.locator('#libraryQuery').fill('unfinished text');
        await page.locator('#libraryQuery').focus();
        await page.evaluate(() => render());
        assert.equal(await page.locator('#libraryQuery').inputValue(), 'unfinished text');
        assert.equal(await page.evaluate(() => document.activeElement.id), 'libraryQuery');
        // 10,000 peer results keep grouped DOM bounded.
        await page.evaluate(() => {
          S.page = 'search';
          S.query = 'fixture';
          S.files = Array.from({ length: 10000 }, (_, i) => ({
            username: 'peer' + Math.floor(i / 100),
            filename: `Music/Artist/Album ${Math.floor(i / 100)}/${i}.flac`,
            size: 1000,
            format: 'flac',
            ownership: 'new',
            duration: 200,
          }));
          S.view = 'grouped';
          render();
        });
        assert.ok((await page.locator('.results-table tbody tr').count()) <= 300);
        for (const view of ['downloads', 'uploads', 'messages', 'browse', 'foryou']) {
          await page.evaluate((view) => {
            S.page = view;
            render();
          }, view);
          assert.ok((await page.locator('#main').innerText()).length > 0, view);
        }
        await page.locator('#settingsNav').click();
        await page.waitForSelector('#settingsDialog[open]');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#settingsDialog').evaluate((d) => d.open), false);
        await page.setViewportSize({ width: 390, height: 844 });
        await page.evaluate(() => {
          S.page = 'search';
          S.files = [];
          S.query = '';
          render();
        });
        assert.ok(await page.locator('#main').isVisible());
        if (process.env.RESONANCE_SCREENSHOTS)
          await page.screenshot({
            path: path.join(process.env.RESONANCE_SCREENSHOTS, name + '-mobile.png'),
            fullPage: true,
          });
        assert.deepEqual(errors, [], name + ' page errors');
        assert.deepEqual(remote, [], 'offline default must not contact suppliers');
        await context.close();
        console.log(
          name +
            ': pagination, grouped DOM, views, keyboard, focus, mobile and offline checks passed',
        );
      } finally {
        await browser.close();
      }
    }
  } finally {
    service.kill();
    await new Promise((resolve) => {
      if (service.exitCode !== null) resolve();
      else {
        service.once('exit', resolve);
        setTimeout(resolve, 3000);
      }
    });
    fs.rmSync(data, { recursive: true, force: true });
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
