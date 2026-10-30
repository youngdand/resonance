'use strict';
const FRONTEND_VERSION = window.RESONANCE_BUILD?.version || 'unknown';
if (document.getElementById('appVersion'))
  document.getElementById('appVersion').textContent = 'v' + FRONTEND_VERSION;
let uiErrors = [];
try {
  uiErrors = JSON.parse(localStorage.getItem('resonance-errors') || '[]');
  if (!Array.isArray(uiErrors)) uiErrors = [];
} catch {}
function scrubDiagnostic(value) {
  let t = String(value ?? '');
  try {
    for (const v of [S.token, document.getElementById('slskKey')?.value])
      if (v && v.length >= 4) t = t.split(v).join('[REDACTED]');
  } catch {}
  return t
    .replace(/(bearer\s+)[\w.\-]+/gi, '$1[REDACTED]')
    .replace(
      /((?:password|api[_-]?key|authorization|secret|token)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi,
      '$1[REDACTED]',
    )
    .replace(/\b[A-Za-z]:[\\/][^\r\n"<>]*/g, '[LOCAL PATH]')
    .replace(/\b[a-f\d]{32,}\b/gi, '[REDACTED ID]')
    .slice(0, 3000);
}
function recordUiError(message, context = {}) {
  const text = scrubDiagnostic(message),
    last = uiErrors[0],
    now = new Date().toISOString();
  if (last && last.message === text && Date.now() - Date.parse(last.time) < 3000) {
    last.count = (last.count || 1) + 1;
    Object.assign(last, context);
  } else
    uiErrors.unshift({
      time: now,
      message: text,
      page: location.hash || '#foryou',
      frontendVersion: FRONTEND_VERSION,
      ...context,
    });
  uiErrors = uiErrors.slice(0, 200);
  try {
    localStorage.setItem('resonance-errors', JSON.stringify(uiErrors));
  } catch {}
  updateErrorBadge();
  if (document.getElementById('diagnosticPanel')?.open) drawDiagnostics();
}
function updateErrorBadge() {
  const b = document.getElementById('diagnosticsButton');
  if (b) {
    b.textContent = uiErrors.length ? 'Errors (' + uiErrors.length + ')' : 'Diagnostics';
    b.classList.toggle('has-errors', uiErrors.length > 0);
  }
}
function diagnosticEscape(v) {
  return String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}
function drawDiagnostics() {
  const d = document.getElementById('diagnosticPanel');
  let backend = 'Unknown';
  try {
    backend = S.serverVersion || 'Not checked';
  } catch {}
  d.innerHTML = `<div class="dialog-top"><div><span class="eyebrow">KEEP THE DETAILS</span><h2>Errors & diagnostics</h2><p class="subtitle">Interface ${FRONTEND_VERSION} · local service ${diagnosticEscape(backend)}</p></div><button class="icon-button" id="closeDiagnostics" aria-label="Close diagnostics">✕</button></div><p class="hint">Errors remain here after notifications disappear. The report includes redacted error logs and version details; it excludes your configuration, database, music files and chat messages. Review it before sharing.</p><div class="dialog-actions"><button class="secondary" id="copyErrorHistory">Copy error history</button><button class="primary" id="downloadDiagnostics">Download diagnostic report</button></div><div class="diagnostic-errors">${uiErrors.length ? uiErrors.map((e) => `<article><small>${diagnosticEscape(e.time)}${e.count ? ' · ' + e.count + ' occurrences' : ''}</small><p>${diagnosticEscape(e.message)}</p><code>${diagnosticEscape([e.method, e.endpoint, e.requestId ? 'ref ' + e.requestId : ''].filter(Boolean).join(' · '))}</code></article>`).join('') : '<p class="hint">No browser errors recorded yet. Reproduce the problem, then download a report.</p>'}</div><p class="hint" id="diagnosticStatus" role="status"></p>`;
}
function saveDiagnosticBlob(blob, name) {
  const url = URL.createObjectURL(blob),
    a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
async function downloadDiagnosticReport() {
  const status = document.getElementById('diagnosticStatus');
  status.textContent = 'Preparing the report…';
  try {
    const r = await fetch('/api/diagnostics/download', {
      method: 'POST',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'X-Resonance-Token': S.token,
      },
      body: JSON.stringify({ errors: uiErrors }),
    });
    if (!r.ok) throw Error('Local service report is unavailable (HTTP ' + r.status + ').');
    const blob = await r.blob();
    if (!r.headers.get('Content-Type')?.includes('zip'))
      throw Error('Local service returned an unexpected report format.');
    saveDiagnosticBlob(blob, 'Resonance-Diagnostics.zip');
    status.textContent =
      'Downloaded one ZIP containing server logs, browser errors and version details. Send it back with a short description of what you clicked.';
  } catch (e) {
    saveDiagnosticBlob(
      new Blob(
        [
          JSON.stringify(
            {
              frontendVersion: FRONTEND_VERSION,
              errors: uiErrors,
              reportError: scrubDiagnostic(e.message),
            },
            null,
            2,
          ),
        ],
        { type: 'application/json' },
      ),
      'Resonance-Browser-Errors.json',
    );
    status.textContent =
      'Downloaded browser error history. The running service does not provide the diagnostic endpoint. Close its Python console, copy all update files and restart.';
  }
}
window.addEventListener('error', (e) => {
  recordUiError(e.message || 'Browser script error', {
    source: String(e.filename || '')
      .split('/')
      .pop(),
    line: e.lineno,
  });
  sendBrowserError(e.message, e.filename, e.lineno);
});
window.addEventListener('unhandledrejection', (e) => {
  const text = e.reason?.message || String(e.reason || 'Unhandled promise rejection');
  recordUiError(text);
  sendBrowserError(text);
});
function sendBrowserError(message, source = '', line = '') {
  try {
    if (!S.token) return;
    fetch('/api/client-error', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Resonance-Token': S.token,
      },
      body: JSON.stringify({
        message: scrubDiagnostic(message),
        source: String(source).split('/').pop(),
        line,
        page: location.hash,
      }),
    }).catch(() => {});
  } catch {}
}
document.addEventListener('click', async (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.id === 'diagnosticsButton') {
    drawDiagnostics();
    document.getElementById('diagnosticPanel').showModal();
  }
  if (b.id === 'closeDiagnostics') document.getElementById('diagnosticPanel').close();
  if (b.id === 'downloadDiagnostics') await downloadDiagnosticReport();
  if (b.id === 'copyErrorHistory') {
    try {
      await navigator.clipboard.writeText(JSON.stringify(uiErrors, null, 2));
      document.getElementById('diagnosticStatus').textContent = 'Error history copied.';
    } catch {
      document.getElementById('diagnosticStatus').textContent =
        'Clipboard unavailable. Use Download diagnostic report instead.';
    }
  }
});
window.addEventListener('load', () => {
  updateErrorBadge();
  setTimeout(() => {
    try {
      if (S.serverVersion && S.serverVersion !== FRONTEND_VERSION) {
        const message =
          'Version mismatch: interface ' +
          FRONTEND_VERSION +
          ', service ' +
          S.serverVersion +
          '. Close the Resonance Python console, copy all update files, restart and press Ctrl+F5.';
        recordUiError(message);
        toast(message, true);
      }
    } catch {}
  }, 2000);
});

document.getElementById('toast').addEventListener('click', () => {
  if (document.getElementById('toast').classList.contains('error'))
    document.getElementById('toast').className = '';
});

let backendVersionWarned = '';
function checkBackendVersion() {
  try {
    if (
      S.serverVersion &&
      S.serverVersion !== FRONTEND_VERSION &&
      backendVersionWarned !== S.serverVersion
    ) {
      backendVersionWarned = S.serverVersion;
      toast(
        'Version mismatch: interface ' +
          FRONTEND_VERSION +
          ', service ' +
          S.serverVersion +
          '. Close the Resonance Python console, copy all update files, restart and press Ctrl+F5.',
        true,
      );
    }
  } catch {}
}
