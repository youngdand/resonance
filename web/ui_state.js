'use strict';
const UIState = (() => {
  const generations = new Map(),
    pages = new Map();
  return {
    next(key) {
      const n = (generations.get(key) || 0) + 1;
      generations.set(key, n);
      return n;
    },
    current(key, n) {
      return generations.get(key) === n;
    },
    capture(root) {
      if (!root) return null;
      const active = document.activeElement;
      let selector = '';
      if (root.contains(active)) {
        if (active.id) selector = '#' + CSS.escape(active.id);
        else {
          const pair = Object.entries(active.dataset || {}).find(
            ([k]) => !k.startsWith('progress'),
          );
          if (pair)
            selector =
              '[data-' +
              pair[0].replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()) +
              '="' +
              CSS.escape(pair[1]) +
              '"]';
        }
      }
      return {
        selector,
        value: active?.value,
        selection:
          typeof active?.selectionStart === 'number'
            ? [active.selectionStart, active.selectionEnd]
            : null,
        scroll: root.scrollTop,
        windowScroll: window.scrollY,
        details: [...root.querySelectorAll('details')].map((d) => [
          d.dataset.resultKey || d.className || d.querySelector('summary')?.textContent,
          d.open,
        ]),
      };
    },
    restore(root, state) {
      if (!root || !state) return;
      for (const d of root.querySelectorAll('details')) {
        const key = d.dataset.resultKey || d.className || d.querySelector('summary')?.textContent;
        const old = state.details.find((x) => x[0] === key);
        if (old) d.open = old[1];
      }
      const target = state.selector ? root.querySelector(state.selector) : null;
      if (target) {
        if (state.value !== undefined && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
          target.value = state.value;
        target.focus({ preventScroll: true });
        if (state.selection)
          try {
            target.setSelectionRange(...state.selection);
          } catch {}
      }
      root.scrollTop = state.scroll;
      window.scrollTo(0, state.windowScroll);
    },
    before(root) {
      if (root?.dataset.page) pages.set(root.dataset.page, this.capture(root));
    },
    after(root, page) {
      root.dataset.page = page;
      this.restore(root, pages.get(page));
    },
  };
})();
