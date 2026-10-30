'use strict';
const vm = require('node:vm'),
  fs = require('node:fs'),
  assert = require('node:assert/strict');
const handlers = {},
  boxes = [],
  observed = [];
let finish = [],
  calls = [],
  active = 0,
  maximum = 0;
const ctx = {
  URL,
  Map,
  Set,
  console,
  S: {
    demo: false,
    discovery: { online: true, items: [] },
    releaseFeed: { items: [] },
  },
  window: { innerHeight: 800 },
  document: {
    body: {},
    querySelectorAll: () => boxes,
    addEventListener: (name, fn) => (handlers[name] = fn),
  },
  IntersectionObserver: class {
    constructor(fn) {
      ctx.intersect = fn;
    }
    observe(box) {
      observed.push(box);
    }
    unobserve() {}
  },
  MutationObserver: class {
    observe() {}
  },
  requestAnimationFrame: (fn) => fn(),
  esc: (s) => String(s),
  showcaseSafeURL: (u) => u,
  artworkCredit: () => '',
  api: async (path) => {
    calls.push(path);
    active++;
    maximum = Math.max(maximum, active);
    return new Promise((resolve) =>
      finish.push((v) => {
        active--;
        resolve(v);
      }),
    );
  },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../web/artwork.js', 'utf8'), ctx);
const makeBox = (id) => ({
  dataset: { artworkId: id },
  classList: { remove() {} },
  innerHTML: '',
  querySelector: () => null,
});
(async () => {
  for (let i = 0; i < 3; i++) {
    const item = { id: String(i), album: 'Album', artist: 'Artist' };
    ctx.S.releaseFeed.items.push(item);
    boxes.push(makeBox(item.id));
  }
  ctx.scanArtwork();
  assert.equal(calls.length, 0, 'observing offscreen covers must not fetch them');
  assert.equal(observed.length, 3);
  ctx.intersect(boxes.map((target) => ({ isIntersecting: true, target })));
  assert.equal(calls.length, 2);
  assert.equal(maximum, 2);
  finish.shift()({
    id: '0',
    artwork: 'https://is1-ssl.mzstatic.com/cover.jpg',
    artworkSource: 'Apple Music',
  });
  await new Promise(setImmediate);
  assert.equal(calls.length, 3);
  assert.ok(boxes[0].innerHTML.includes('class="album-art"'));
  assert.equal(ctx.S.releaseFeed.items[0].artworkSource, 'Apple Music');
  while (finish.length) finish.shift()({ artwork: '' });
  await new Promise(setImmediate);
  ctx.queueArtwork('0');
  assert.equal(calls.length, 3, 'the same missing cover request must not repeat every redraw');
  const failed = boxes[0],
    image = {
      tagName: 'IMG',
      classList: { contains: (c) => c === 'album-art' },
      closest: () => failed,
      getAttribute: () => 'https://is1-ssl.mzstatic.com/cover.jpg',
      style: {},
    };
  failed.classList.add = () => {};
  handlers.error({ target: image });
  assert.ok(calls.at(-1).includes('failed=https%3A%2F%2Fis1-ssl.mzstatic.com%2Fcover.jpg'));
  assert.equal(image.style.display, 'none');
  finish.shift()({
    id: '0',
    artwork: 'https://cdn-images.dzcdn.net/other.jpg',
  });
  await new Promise(setImmediate);
  ctx.S.discovery.online = false;
  ctx.queueArtwork('new');
  assert.equal(calls.length, 4);
  ctx.paintArtwork('0', {
    artwork: 'https://is1-ssl.mzstatic.com/offline.jpg',
  });
  assert.ok(!boxes[0].innerHTML.includes('offline.jpg'));
  console.log(
    'Artwork UI passed: viewport loading, two-request bound, deduplication, in-place covers, broken-image fallback and offline privacy.',
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
