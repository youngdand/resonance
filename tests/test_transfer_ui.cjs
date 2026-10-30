'use strict';
const fs = require('fs'),
  vm = require('vm'),
  assert = require('assert'),
  path = require('path');
const context = {
  Number,
  Math,
  Map,
  JSON,
  Infinity,
  Date,
  S: { demo: false, page: 'downloads', requests: [], albumJobs: [] },
  clearingTransfers: false,
  featureBusy: false,
  succeeded: (s) => /(?:^|[,\s])succeeded(?:$|[,\s])/i.test(s),
  esc: (s) => String(s).replace(/"/g, '&quot;'),
  size: (n) => n + ' B',
  document: { querySelectorAll: () => [] },
  window: { scrollY: 42, scrollTo: () => {} },
  render: () => {
    context.renders++;
  },
  renders: 0,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/transfers.js'), 'utf8'), context);
const file = {
  id: 'a',
  status: 'InProgress, Transferring',
  file: { size: 1000 },
  bytesTransferred: 250,
  currentSpeed: 100,
};
assert.equal(context.transferModel(file, 'download').percent, 25);
assert.equal(context.transferModel(file, 'download').eta, '8s remaining');
assert.equal(
  context.transferModel({ ...file, status: 'Completed, Errored' }, 'download').percent,
  25,
);
assert.equal(context.transferModel({ ...file, status: 'Completed, Errored' }, 'download').speed, 0);
assert.equal(
  context.transferModel({ ...file, status: 'Completed, Succeeded' }, 'download').percent,
  100,
);
assert.equal(
  context.transferModel(
    { ...file, status: 'Queued', currentSpeed: undefined, averageSpeed: 999 },
    'download',
  ).speed,
  0,
);
assert.equal(context.transferModel({ ...file, bytesTransferred: 5000 }, 'download').percent, 100);
assert.equal(
  context.transferModel({ ...file, currentSpeed: 0 }, 'download').eta,
  'Waiting for data',
);
assert.equal(context.transferModel({ ...file, file: { size: 0 } }, 'download').percent, null);
assert.equal(context.transferModel({ ...file, bytesTransferred: -4 }, 'download').percent, 0);
assert.equal(context.transferModel({ ...file, currentSpeed: Infinity }, 'download').speed, 0);
assert.equal(context.transferModel({ ...file, bytesTransferred: 600 }, 'download').percent, 60);
const nodes = {};
for (const key of ['percent', 'bytes', 'speed', 'eta'])
  nodes['[data-progress-' + key + ']'] = { textContent: '' };
nodes['[data-progress-fill]'] = { style: { width: '0%' } };
nodes['[role="progressbar"]'] = {
  attrs: {},
  setAttribute(k, v) {
    this.attrs[k] = v;
  },
  removeAttribute(k) {
    delete this.attrs[k];
  },
};
const row = {
  dataset: { transferProgress: 'download:a' },
  querySelector: (key) => nodes[key],
};
context.document.querySelectorAll = (selector) =>
  selector === '[data-transfer-progress]' ? [row] : [];
context.S.requests = [file];
context.applyTransferSnapshot({
  direction: 'downloads',
  sampledAt: 1,
  requests: [{ ...file, bytesTransferred: 500, currentSpeed: 200 }],
  albumJobs: [],
});
assert.equal(context.renders, 0, 'byte updates must not rebuild rows');
assert.equal(nodes['[data-progress-fill]'].style.width, '50%');
assert.equal(nodes['[data-progress-bytes]'].textContent, '500 B / 1000 B');
assert.equal(nodes['[role="progressbar"]'].attrs['aria-valuenow'], '50.0');
context.applyTransferSnapshot({
  direction: 'downloads',
  sampledAt: 0.5,
  requests: [file],
  albumJobs: [],
});
assert.equal(
  nodes['[data-progress-fill]'].style.width,
  '50%',
  'stale snapshots must not roll progress backwards',
);
context.applyTransferSnapshot({
  direction: 'downloads',
  sampledAt: 2,
  requests: [{ ...file, status: 'Completed, Succeeded' }],
  albumJobs: [],
});
assert.equal(context.renders, 1, 'terminal states rebuild actions exactly when needed');
context.applyTransferSnapshot({
  direction: 'uploads',
  sampledAt: 3,
  uploads: [],
});
assert.equal(context.renders, 1, 'off-page snapshots must be ignored');
console.log(
  'Transfer UI passed: measured progress, speed/ETA, resume, stalls, failures, zero-size safety, stale snapshots, accessible values, and updates without replacing row nodes.',
);
