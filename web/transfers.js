'use strict';
const transferNumbers = (v) => (Number.isFinite(Number(v)) ? Math.max(0, Number(v)) : 0);
function transferEta(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  seconds = Math.ceil(seconds);
  if (seconds < 60) return seconds + 's remaining';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's remaining';
  return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm remaining';
}
function transferModel(t, kind) {
  const state = String(t.status || t.state || ''),
    done = succeeded(state) || state === 'Selected files complete';
  const total = transferNumbers(t.file?.size ?? t.size),
    bytes = done ? total : Math.min(total || Infinity, transferNumbers(t.bytesTransferred));
  const stopped =
    kind === 'album'
      ? done
      : /completed|succeeded|errored|cancelled|rejected|replaced|denied|failed|unconfirmed/i.test(
          state,
        );
  const speed =
    stopped || (kind !== 'album' && /queued/i.test(state))
      ? 0
      : transferNumbers(t.currentSpeed ?? t.averageSpeed ?? t.speed);
  const active =
    !stopped &&
    (kind === 'album' || !/queued/i.test(state)) &&
    (/transferring|inprogress/i.test(state) || speed > 0);
  const percent = done ? 100 : total ? Math.min(100, (bytes / total) * 100) : null;
  const eta =
    kind === 'album' && t.failed > 0
      ? 'Some files need attention'
      : done
        ? 'Complete'
        : stopped
          ? 'Not transferring'
          : speed > 0 && total
            ? transferEta((total - bytes) / speed)
            : active
              ? 'Waiting for data'
              : /unconfirmed/i.test(state)
                ? 'Not confirmed'
                : 'Queued / waiting';
  return { percent, bytes, total, speed, eta, active, done };
}
function transferProgressKey(t, kind) {
  return kind === 'upload'
    ? 'upload:' + JSON.stringify([t.username, t.id || t.filename])
    : kind + ':' + t.id;
}
function transferProgress(t, kind) {
  const m = transferModel(t, kind),
    key = transferProgressKey(t, kind),
    label =
      kind === 'album'
        ? 'Album download progress'
        : kind === 'upload'
          ? 'Upload progress'
          : 'Download progress';
  return `<div class="live-transfer-progress" data-transfer-progress="${esc(key)}"><div class="transfer-metrics"><strong data-progress-percent>${m.percent === null ? '—' : m.percent.toFixed(1) + '%'}</strong><span data-progress-bytes>${size(m.bytes)} / ${m.total ? size(m.total) : 'size unknown'}</span><span data-progress-speed>${m.speed > 0 ? size(m.speed) + '/s' : m.active ? '0 KB/s' : '—'}</span><span data-progress-eta>${esc(m.eta)}</span></div><div class="progress" role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="100" ${m.percent === null ? '' : `aria-valuenow="${m.percent.toFixed(1)}"`}><i data-progress-fill style="width:${m.percent ?? 0}%"></i></div></div>`;
}
function transferFeedStatus(direction) {
  return `<span class="transfer-live-status" data-transfer-feed="${direction}" role="status">${S.demo ? 'Demo progress' : esc(S.transferFeedText || 'Connecting live progress…')}</span>`;
}
function patchProgressNode(node, model) {
  const values = {
    percent: model.percent === null ? '—' : model.percent.toFixed(1) + '%',
    bytes: size(model.bytes) + ' / ' + (model.total ? size(model.total) : 'size unknown'),
    speed: model.speed > 0 ? size(model.speed) + '/s' : model.active ? '0 KB/s' : '—',
    eta: model.eta,
  };
  for (const [name, value] of Object.entries(values)) {
    const el = node.querySelector('[data-progress-' + name + ']');
    if (el && el.textContent !== value) el.textContent = value;
  }
  const fill = node.querySelector('[data-progress-fill]');
  if (fill) {
    const width = (model.percent ?? 0) + '%';
    if (fill.style.width !== width) fill.style.width = width;
  }
  const bar = node.querySelector('[role="progressbar"]');
  if (bar) {
    if (model.percent === null) bar.removeAttribute('aria-valuenow');
    else bar.setAttribute('aria-valuenow', model.percent.toFixed(1));
  }
}
function transferStructure(direction) {
  return direction === 'uploads'
    ? JSON.stringify(S.uploads.map((f) => [f.username, f.id || f.filename, f.state]))
    : JSON.stringify([
        S.requests.filter((r) => !r.archived).map((r) => [r.id, r.status, r.transferId]),
        (S.albumJobs || [])
          .filter((j) => !j.archived)
          .map((j) => [j.id, j.completed, j.failed, j.expected, j.status]),
      ]);
}
let lastTransferSample = { downloads: 0, uploads: 0 };
function applyTransferSnapshot(data) {
  if (S.demo || data.direction !== S.page || !['uploads', 'downloads'].includes(data.direction))
    return;
  if (data.sampledAt < lastTransferSample[data.direction]) return;
  lastTransferSample[data.direction] = data.sampledAt;
  markTransferFeed('Live · updates every second');
  if (clearingTransfers || featureBusy) return;
  const before = transferStructure(data.direction);
  if (data.direction === 'uploads') S.uploads = data.uploads;
  else {
    S.requests = data.requests;
    S.albumJobs = data.albumJobs;
  }
  if (before !== transferStructure(data.direction)) {
    const scroll = window.scrollY;
    render();
    window.scrollTo(0, scroll);
  } else {
    const models = new Map();
    if (data.direction === 'uploads') {
      for (const f of S.uploads)
        models.set(transferProgressKey(f, 'upload'), transferModel(f, 'upload'));
    } else {
      for (const r of S.requests)
        models.set(transferProgressKey(r, 'download'), transferModel(r, 'download'));
      for (const j of S.albumJobs || [])
        models.set(transferProgressKey(j, 'album'), transferModel(j, 'album'));
    }
    for (const node of document.querySelectorAll('[data-transfer-progress]')) {
      const model = models.get(node.dataset.transferProgress);
      if (model) patchProgressNode(node, model);
    }
  }
}
function markTransferFeed(text) {
  S.transferFeedText = text;
  for (const el of document.querySelectorAll('[data-transfer-feed]')) {
    if (el.textContent !== text) el.textContent = text;
    el.classList.toggle('reconnecting', /reconnect|unavailable/i.test(text));
  }
}
