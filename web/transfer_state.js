'use strict';
const TransferState = {
  classify(state) {
    const text = String(state || '').toLowerCase(),
      tokens = new Set(text.split(/[,\s]+/));
    if (tokens.has('replaced')) return 'replaced';
    if (tokens.has('cancelled') || tokens.has('canceled')) return 'cancelled';
    if (tokens.has('succeeded')) return 'succeeded';
    if (/errored|error|reject|denied|timedout|timed out|aborted|offline|failed/.test(text))
      return 'failed';
    if (/unconfirmed|missing|reconcil|submitting|pending/.test(text)) return 'uncertain';
    if (/transferring|inprogress|in progress/.test(text)) return 'active';
    return 'queued';
  },
  succeeded(state) {
    return this.classify(state) === 'succeeded';
  },
  failed(state) {
    return this.classify(state) === 'failed';
  },
  terminal(state) {
    return ['succeeded', 'failed', 'cancelled', 'replaced'].includes(this.classify(state));
  },
};
