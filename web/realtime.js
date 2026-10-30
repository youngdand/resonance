'use strict';
let resonanceEvents = null,
  realtimeTransferScope = '',
  lastTransferEvent = 0,
  lastTransferResponse = 0,
  transferFallbackBusy = false,
  nextTransferRetry = 0,
  transferRetryDelay = 1000;
function transferScope() {
  return !document.hidden && ['downloads', 'uploads'].includes(S.page) ? S.page : '';
}
function startRealtime() {
  if (document.hidden || S.demo || !S.settings.hasKey) {
    if (resonanceEvents) {
      resonanceEvents.close();
      resonanceEvents = null;
      realtimeTransferScope = '';
    }
    return;
  }
  const scope = transferScope();
  if (resonanceEvents && scope === realtimeTransferScope) return;
  if (resonanceEvents) resonanceEvents.close();
  realtimeTransferScope = scope;
  lastTransferEvent = 0;
  nextTransferRetry = 0;
  if (scope === 'uploads' && !S.uploadsInitialized) loadUploads(true);
  if (scope) markTransferFeed('Connecting live progress…');
  resonanceEvents = new EventSource('/api/events' + (scope ? '?transfers=' + scope : ''));
  resonanceEvents.addEventListener('transfers', (e) => {
    try {
      const update = JSON.parse(e.data);
      if (update.direction !== transferScope()) return;
      lastTransferEvent = Date.now();
      lastTransferResponse = Date.now();
      transferRetryDelay = 1000;
      applyTransferSnapshot(update);
    } catch {
      markTransferFeed('Reconnecting · keeping last progress');
    }
  });
  resonanceEvents.addEventListener('transfer-error', () => {
    if (transferScope()) markTransferFeed('Reconnecting · keeping last progress');
  });
  resonanceEvents.addEventListener('error', () => {
    if (transferScope()) markTransferFeed('Reconnecting · keeping last progress');
  });
  resonanceEvents.addEventListener('state', (e) => {
    try {
      if (S.demo) return;
      const state = JSON.parse(e.data);
      S.slskdShares = state.shares;
      S.connected = /loggedin/i.test(state.server.state || '');
      nav();
    } catch {}
  });
  resonanceEvents.addEventListener('search-response', (e) => {
    try {
      const update = JSON.parse(e.data);
      if (S.demo || update.id !== S.searchId) return;
      const files = new Map(S.files.map((f) => [f.username + '\0' + f.filename, f]));
      for (const f of update.files) files.set(f.username + '\0' + f.filename, f);
      S.files = [...files.values()];
      markAttempted();
      if (S.page === 'search') render();
    } catch {}
  });
  // EventSource reconnects automatically; the existing search/scan polling stays active.
}
setInterval(startRealtime, 5000);
window.addEventListener('load', () => setTimeout(startRealtime, 1500));

// Automatic HTTP fallback covers proxies that buffer event streams and dropped connections.
setInterval(async () => {
  const direction = transferScope(),
    now = Date.now();
  if (
    !direction ||
    S.demo ||
    !S.settings.hasKey ||
    transferFallbackBusy ||
    now - lastTransferEvent < 3500 ||
    now < nextTransferRetry
  )
    return;
  transferFallbackBusy = true;
  try {
    const snapshot = await api('transfer-progress?direction=' + direction);
    if (direction !== transferScope()) return;
    lastTransferResponse = Date.now();
    applyTransferSnapshot(snapshot);
    transferRetryDelay = 1000;
    nextTransferRetry = Date.now() + 1000;
  } catch {
    markTransferFeed('Reconnecting · keeping last progress');
    nextTransferRetry = Date.now() + transferRetryDelay;
    transferRetryDelay = Math.min(15000, transferRetryDelay * 2);
  } finally {
    transferFallbackBusy = false;
  }
}, 1000);
const goBeforeTransferFeed = go;
go = function (page) {
  const result = goBeforeTransferFeed(page);
  startRealtime();
  return result;
};
document.addEventListener('visibilitychange', startRealtime);
