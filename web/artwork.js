'use strict';
// Fetch missing covers only when cards approach the viewport. Never redraw the feed.
const artworkPending = [],
  artworkQueued = new Set(),
  artworkDone = new Map(),
  artworkBad = new Map();
let artworkActive = 0,
  artworkScanScheduled = false;
function artworkItem(id) {
  return [
    S.releaseDetails?.item,
    ...(S.releaseFeed?.items || []),
    ...(S.discovery?.items || []),
  ].find((i) => i && i.id === id);
}
function paintArtwork(id, result) {
  const item = artworkItem(id);
  if (!item || !result.artwork || !S.discovery.online) return;
  for (const candidate of [
    S.releaseDetails?.item,
    ...(S.releaseFeed?.items || []),
    ...(S.discovery?.items || []),
  ])
    if (candidate?.id === id) Object.assign(candidate, result);
  document.querySelectorAll('[data-artwork-id]').forEach((box) => {
    if (box.dataset.artworkId !== id) return;
    box.classList.remove('art-unavailable');
    box.innerHTML = `<img class="album-art" src="${esc(showcaseSafeURL(result.artwork))}" alt="Cover of ${esc(item.album)} by ${esc(item.artist)}" loading="lazy" decoding="async" referrerpolicy="no-referrer"><span class="cover-type">${esc(item.releaseType || 'Album')}</span>${artworkCredit(item)}`;
  });
}
async function drainArtwork() {
  while (artworkActive < 2 && artworkPending.length) {
    const task = artworkPending.shift();
    if (!S.discovery.online || S.demo) {
      artworkQueued.delete(task.key);
      continue;
    }
    artworkActive++;
    (async () => {
      try {
        const result = await api(
          'discovery/releases/artwork?id=' +
            encodeURIComponent(task.id) +
            (task.failed ? '&failed=' + encodeURIComponent(task.failed) : ''),
        );
        if (S.discovery.online) paintArtwork(task.id, result);
        artworkDone.set(task.key, Date.now() + 1000 * (result.retryAfter || 900));
      } catch (error) {
        if (typeof recordUiError === 'function')
          recordUiError('Artwork lookup: ' + error.message, {
            endpoint: '/api/discovery/releases/artwork',
          });
      } finally {
        artworkQueued.delete(task.key);
        artworkActive--;
        drainArtwork();
      }
    })();
  }
}
function queueArtwork(id, failed = '') {
  if (!id || !S.discovery?.online || S.demo) return;
  const key = id + '|' + failed;
  if (artworkQueued.has(key) || (artworkDone.get(key) || 0) > Date.now()) return;
  artworkQueued.add(key);
  artworkPending.push({ id, failed, key });
  drainArtwork();
}
const artworkObserver =
  typeof IntersectionObserver === 'undefined'
    ? null
    : new IntersectionObserver(
        (entries) => {
          for (const entry of entries)
            if (entry.isIntersecting) {
              const box = entry.target;
              artworkObserver.unobserve(box);
              queueArtwork(box.dataset.artworkId);
            }
        },
        { rootMargin: '160px' },
      );
function scanArtwork() {
  if (!S.discovery?.online || S.demo) return;
  document.querySelectorAll('[data-artwork-id]').forEach((box) => {
    if (!box.dataset.artworkId || box.querySelector('.album-art')) return;
    if (artworkObserver) artworkObserver.observe(box);
    else {
      const r = box.getBoundingClientRect();
      if (r.bottom >= 0 && r.top < window.innerHeight + 160) queueArtwork(box.dataset.artworkId);
    }
  });
}
if (typeof MutationObserver !== 'undefined')
  new MutationObserver(() => {
    if (artworkScanScheduled) return;
    artworkScanScheduled = true;
    requestAnimationFrame(() => {
      artworkScanScheduled = false;
      scanArtwork();
    });
  }).observe(document.body, { childList: true, subtree: true });
document.addEventListener(
  'error',
  (e) => {
    const img = e.target;
    if (img.tagName === 'IMG' && img.classList.contains('artwork-badge')) {
      img.style.display = 'none';
      const label = img.parentElement.querySelector('span');
      if (label) label.hidden = false;
      return;
    }
    if (img.tagName !== 'IMG' || !img.classList.contains('album-art')) return;
    const box = img.closest('[data-artwork-id]');
    if (!box) return;
    const id = box.dataset.artworkId,
      url = img.getAttribute('src'),
      bad = artworkBad.get(id) || new Set();
    bad.add(url);
    artworkBad.set(id, bad);
    img.style.display = 'none';
    box.classList.add('art-unavailable');
    if (bad.size <= 4) queueArtwork(id, url);
  },
  true,
);
scanArtwork();
