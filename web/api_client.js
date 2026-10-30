async function api(path, body) {
  const method = body === undefined ? 'GET' : 'POST';
  let r;
  try {
    r = await fetch('/api/' + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Resonance-Token': S.token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    let d;
    try {
      d = JSON.parse(text);
    } catch {
      throw Error(
        `Resonance returned HTTP ${r.status} with an unreadable response for ${path.split('?')[0]}. Restart the Python console and refresh the browser.`,
      );
    }
    if (!r.ok || d.error) {
      const message =
        (d.error || 'Request failed') + (d.requestId ? ' [ref ' + d.requestId + ']' : '');
      const e = Error(message);
      e.status = r.status;
      e.requestId = d.requestId;
      throw e;
    }
    return d;
  } catch (e) {
    recordUiError(e.message, {
      endpoint: path.split('?')[0],
      method,
      status: e.status,
      requestId: e.requestId,
    });
    throw e;
  }
}
