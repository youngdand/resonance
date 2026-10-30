'use strict';
Object.assign(S, { releaseDetails: null, releaseDetailLoading: false });
const showcaseSafeURL = (value) => {
  try {
    const u = new URL(value);
    return u.protocol === 'https:' ? u.href : '';
  } catch {
    return '';
  }
};
function artworkCredit(item) {
  const url = showcaseSafeURL(item.artworkSourceUrl);
  if (!url || !S.discovery.online) return '';
  return `<a class="artwork-credit" href="${esc(url)}" target="_blank" rel="noreferrer" aria-label="View this release at ${esc(item.artworkSource || 'artwork source')}">${item.artworkSource === 'Apple Music' ? '<img class="artwork-badge" alt="Listen on Apple Music" src="https://tools.applemediaservices.com/api/badges/listen-on-apple-music/badge/en-us?size=small"><span hidden>Apple Music ↗</span>' : esc(item.artworkSource || 'Artwork source') + ' ↗'}</a>`;
}
function showcaseImage(item, large = false) {
  const url = S.discovery.online ? showcaseSafeURL(item.artwork) : '';
  return `<div class="showcase-cover ${large ? 'large' : ''}" data-artwork-id="${esc(item.id || '')}">${url ? `<img class="album-art" src="${esc(url)}" alt="Cover of ${esc(item.album)} by ${esc(item.artist)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : `<div class="cover-fallback c${hash(item.artist)}">${icon('music')}<span>${esc(item.artist)}</span></div>`}<span class="cover-type">${esc(item.releaseType || 'Album')}</span>${url ? artworkCredit(item) : ''}</div>`;
}
function showcaseScores(item) {
  return (item.ratings || [])
    .filter((r) => r.best > 0)
    .map(
      (r) =>
        `<a class="critic-score" href="${esc(showcaseSafeURL(r.url))}" target="_blank" rel="noreferrer"><strong>${esc(r.value)}<small>/${esc(r.best)}</small></strong><span>${esc(r.publisher)}<small>critic score</small></span></a>`,
    )
    .join('');
}
function releaseCard(item) {
  const dateLabel =
    item.dateBasis === 'listing-week'
      ? 'Listed week of'
      : item.provider === 'independent'
        ? 'Release listing'
        : 'Released';
  return `<article class="discovery-card release-card showcase-card">${showcaseImage(item)}<div class="discovery-card-body">${item.classification === 'catalogue-edition' ? '<p class="hint">NEW EDITION / REGIONAL RELEASE</p>' : item.classification === 'original-date-unconfirmed' ? '<p class="hint">ORIGINAL DATE UNCONFIRMED</p>' : ''}<div class="story-kicker">${esc(item.genres?.slice(0, 2).join(' / ') || 'Unclassified')}<span>${esc(releaseDate(item.releaseDate))}</span></div><h3>${esc(item.album)}</h3><p class="discovery-artist">${esc(item.artist)}</p><p class="story-deck">${item.coveragePreview ? `“${esc(item.coveragePreview.text)}”<small class="preview-credit">${esc(item.coveragePreview.publisher)} · ${item.coveragePreview.kind === 'review' ? 'review preview' : 'release coverage'}</small>` : 'Open for reviews, release notes and available track details.'}</p>${showcaseScores(item)}<div class="story-meta"><span>${dateLabel}${item.originalDate ? ' · Original ' + esc(releaseDate(item.originalDate)) : ''}</span><span>${['album-in-library', 'possible-album'].includes(item.libraryStatus) ? 'Library match' : 'Explore / collect'}</span></div><button class="primary explore-release" data-release-detail="${esc(item.id)}">Explore this release ${icon('arrow')}</button>${discoveryActions(item)}<div class="discovery-source">${(item.sources || [{ name: item.source, url: item.url }]).map((src) => `<a href="${esc(showcaseSafeURL(src.url))}" target="_blank" rel="noreferrer">${esc(src.name)} ↗</a>`).join(' · ')}</div></div></article>`;
}
function showcaseToolbar(feed, options) {
  return `<div class="showcase-toolbar"><label class="showcase-search">Find your next record<input id="showcaseQuery" type="search" maxlength="200" placeholder="Artist, album, genre or label…" value="${esc(options.q || '')}"></label><label>Genre<select class="select" id="showcaseGenre">${[['all', 'All genres'], ...['Alternative & Indie', 'Blues', 'Classical', 'Country', 'Electronic & Dance', 'Folk & Acoustic', 'Hip-Hop & Rap', 'Jazz', 'Metal', 'Pop', 'Punk', 'R&B & Soul', 'Reggae', 'Rock', 'Soundtracks', 'World & Latin'].map((g) => [g, g]), ['unclassified', 'Unclassified']].map(([v, label]) => `<option value="${esc(v)}" ${(options.genre || 'all') === v ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></label><label>When<select class="select" id="showcaseDays">${[7, 30, 90].map((n) => `<option value="${n}" ${Number(options.days) === n ? 'selected' : ''}>Last ${n} days</option>`).join('')}</select></label><label>Order<select class="select" id="showcaseSort">${[
    ['recent', 'Newest first'],
    ['rating', 'Critic score'],
    ['artist', 'Artist A–Z'],
  ]
    .map(
      ([v, label]) =>
        `<option value="${v}" ${(options.sort || 'recent') === v ? 'selected' : ''}>${label}</option>`,
    )
    .join(
      '',
    )}</select></label></div><div class="showcase-focus" role="group" aria-label="Discovery focus">${[
    ['all', 'All releases'],
    ['reviewed', 'With critic scores'],
    ['saved', 'Saved'],
    ['new', 'New to my collection'],
  ]
    .map(
      ([key, label]) =>
        `<button class="${(options.focus || 'all') === key ? 'active' : ''}" aria-pressed="${(options.focus || 'all') === key}" data-showcase-focus="${key}">${label}</button>`,
    )
    .join(
      '',
    )}<button class="filter-reset" data-showcase-reset="true">Reset filters</button><span>${feed?.total || 0} releases</span></div>`;
}
function showcaseDialog() {
  let dialog = document.getElementById('releaseDossier');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'releaseDossier';
    dialog.setAttribute('aria-label', 'Release story');
    document.body.appendChild(dialog);
    dialog.addEventListener('close', () => {
      if (S.page === 'foryou') render();
    });
  }
  return dialog;
}
function publicationStory(p) {
  const kind = p.kind || (p.publisher === 'Official Charts' ? 'release-note' : 'review');
  return `<article class="publication-note story-publication"><div class="story-kicker">${esc(kind === 'review' ? 'REVIEW' : kind === 'release-note' ? 'RELEASE NOTES' : 'FEATURE')}<span>${esc(p.published && !Number.isNaN(Date.parse(p.published)) ? new Date(p.published).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '')}</span></div><h4>${esc(p.title || p.publisher)}</h4><p class="publication-byline">${esc(p.publisher)}${p.author && p.author !== p.publisher ? ' · ' + esc(p.author) : ''}${p.stale ? ' · cached' : ''}</p>${p.excerpt ? `<blockquote>${esc(p.excerpt)}</blockquote>` : ''}${showcaseScores(p)}<a href="${esc(showcaseSafeURL(p.url))}" target="_blank" rel="noreferrer">${kind === 'review' ? 'Continue reading the review' : kind === 'release-note' ? 'Read the release feature' : 'Read the feature'} at ${esc(p.publisher)} ↗</a><p class="hint">Publisher preview · short source excerpt</p></article>`;
}
function renderDossier(item, dossier) {
  const publications = dossier?.publications || [],
    readable = publications.filter((p) => p.excerpt),
    tracks = publications.find((p) => p.tracks?.length)?.tracks || [];
  const reviews = readable.filter(
      (p) => (p.kind || 'review') === 'review' && p.publisher !== 'Official Charts',
    ),
    features = readable.filter((p) => !reviews.includes(p));
  return `<button class="dossier-close icon-button" data-dossier-close="true" aria-label="Close release story">✕</button>
 <div class="dossier-hero">${showcaseImage(item, true)}<div><span class="eyebrow">DISCOVER THE RECORD</span><h2 id="dossierTitle">${esc(item.album)}</h2><p class="dossier-artist">${esc(item.artist)}</p><p class="hint">${esc(item.releaseType || 'Release')} · Listed ${esc(releaseDate(item.releaseDate))}${item.genres?.length ? ' · ' + esc(item.genres.join(' / ')) : ''}${item.label ? ' · ' + esc(item.label) : ''}</p>${showcaseScores(item)}${S.releaseDetailLoading ? discoveryActions(item).replaceAll('<button', '<button disabled') : discoveryActions(item)}</div></div>
 <div class="dossier-reading">
 ${S.releaseDetailLoading || dossier?.reviewsLoading ? '<p class="reading-progress" role="status"><span class="spinner"></span>Finding coverage for this album… You can read available material below.</p>' : ''}
 ${reviews.length ? `<section class="reading-section"><h3>What the critics wrote</h3>${reviews.map(publicationStory).join('')}</section>` : ''}
 ${features.length ? `<section class="reading-section"><h3>Behind the release</h3>${features.map(publicationStory).join('')}</section>` : ''}
 ${!readable.length && !S.releaseDetailLoading && !dossier?.reviewsLoading ? `<div class="reading-empty"><h3>No readable coverage found yet</h3><p>Resonance checked the connected publishers but couldn’t retrieve a matching review or feature for this release. Coverage can arrive after release day.</p><p class="hint">You can still save this album or find it on Soulseek. Source checks and optional external searches are below.</p></div>` : ''}
 ${tracks.length ? `<details class="reading-tracks"><summary>Tracklist · ${tracks.length} tracks</summary><ol class="dossier-tracks">${tracks.map((t) => `<li><span>${esc(t.title)}</span>${t.duration ? `<small>${esc(t.duration.replace(/^PT/, '').toLowerCase())}</small>` : ''}</li>`).join('')}</ol></details>` : ''}
 <details class="reading-sources"><summary>Sources & lookup details${dossier?.reviewSources?.length ? ' · ' + dossier.reviewSources.length + ' checks' : ''}</summary><p class="hint">Source-specific album searches supplement recent indexes. Coverage is incomplete; full reviews remain on their publishers’ sites. Scores use their original scales.</p><div class="source-checks">${(dossier?.reviewSources || []).map((src) => `<div><strong>${esc(src.name)}</strong><span class="hint">${esc(src.status)}${src.stale ? ' · cached' : ''}</span></div>`).join('')}</div><h4>Release sources</h4>${(item.sources || [{ name: item.source, url: item.url }]).map((src) => `<a class="research-link" href="${esc(showcaseSafeURL(src.url))}" target="_blank" rel="noreferrer">Open ${esc(src.name)} ↗</a>`).join('')}<details><summary>External searches</summary><p class="hint">These are search links, not fetched reviews. Aggregator and audience scores are not imported.</p>${(dossier?.researchLinks || []).map((src) => `<a class="research-link" href="${esc(showcaseSafeURL(src.url))}" target="_blank" rel="noreferrer">${esc(src.name)} ↗</a>`).join('')}${(
   dossier?.reviewSources || []
 )
   .filter((src, i, all) => all.findIndex((v) => v.name === src.name) === i)
   .map(
     (src) =>
       `<a class="research-link" href="${esc(showcaseSafeURL(src.searchUrl))}" target="_blank" rel="noreferrer">Search ${esc(src.name)} ↗</a>`,
   )
   .join(
     '',
   )}</details>${(dossier?.warnings || []).map((w) => `<p class="hint">${esc(w)}</p>`).join('')}</details>
 </div>`;
}
let dossierGeneration = 0,
  showcaseSearchTimer;
async function openReleaseDossier(id) {
  const item = [...(S.releaseFeed?.items || []), ...S.discovery.items].find((i) => i.id === id);
  if (!item) return;
  const generation = ++dossierGeneration,
    dialog = showcaseDialog();
  S.releaseDetails = { item, publications: [], warnings: [] };
  S.releaseDetailLoading = !S.demo;
  paintDossier(dialog, item, null);
  dialog.setAttribute('aria-labelledby', 'dossierTitle');
  if (!dialog.open) dialog.showModal();
  try {
    const dossier = S.demo
      ? {
          item,
          publications: [],
          warnings: ['Fictional demo. No publisher request was made.'],
        }
      : await api('discovery/releases/detail?id=' + encodeURIComponent(id));
    if (generation !== dossierGeneration || !dialog.open) return;
    S.releaseDetailLoading = false;
    S.releaseDetails = dossier;
    paintDossier(dialog, dossier.item, dossier);
    Object.assign(item, dossier.item);
    if (!S.demo) {
      dossier.reviewsLoading = true;
      paintDossier(dialog, dossier.item, dossier);
      try {
        const reviews = await api('discovery/releases/reviews?id=' + encodeURIComponent(id));
        if (generation !== dossierGeneration || !dialog.open) return;
        dossier.publications = [
          ...new Map(
            [...(dossier.publications || []), ...(reviews.publications || [])].map((p) => [
              p.url,
              p,
            ]),
          ).values(),
        ];
        const lead =
          (reviews.publications || []).find((p) => p.kind === 'review' && p.excerpt) ||
          (reviews.publications || []).find((p) => p.excerpt);
        if (lead)
          dossier.item.coveragePreview = {
            text: lead.excerpt.split(/\s+/).slice(0, 40).join(' '),
            publisher: lead.publisher,
            url: lead.url,
            kind: lead.kind,
          };
        dossier.reviewSources = reviews.reviewSources;
        const ratings = [
          ...(dossier.item.ratings || []),
          ...(reviews.publications || []).flatMap((p) => p.ratings || []),
        ];
        dossier.item.ratings = ratings.filter(
          (r, i) => ratings.findIndex((v) => v.publisher === r.publisher && v.url === r.url) === i,
        );
      } catch (error) {
        dossier.warnings = [...(dossier.warnings || []), 'Review lookup: ' + error.message];
      }
      if (generation === dossierGeneration && dialog.open) {
        dossier.reviewsLoading = false;
        Object.assign(item, dossier.item);
        paintDossier(dialog, dossier.item, dossier);
      }
    }
  } catch (e) {
    if (generation === dossierGeneration && dialog.open) {
      S.releaseDetailLoading = false;
      paintDossier(dialog, item, { warnings: [e.message] });
    }
  }
}
async function applyShowcase(key, value) {
  S.releaseOptions[key] = value;
  S.releaseOffset = 0;
  if (!S.demo && key !== 'q') await api('discovery/releases/preferences', S.releaseOptions);
  await loadReleaseFeed();
}
document.addEventListener('change', async (e) => {
  const fields = {
      showcaseGenre: 'genre',
      showcaseDays: 'days',
      showcaseSort: 'sort',
    },
    key = fields[e.target.id];
  if (!key) return;
  try {
    await changeReleaseOptions({
      id: key === 'genre' ? 'releaseGenre' : key === 'days' ? 'releaseDays' : 'releaseSort',
      type: 'select-one',
      value: e.target.value,
    });
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener('input', (e) => {
  if (e.target.id !== 'showcaseQuery') return;
  const value = e.target.value,
    position = e.target.selectionStart;
  clearTimeout(showcaseSearchTimer);
  showcaseSearchTimer = setTimeout(async () => {
    try {
      await applyShowcase('q', value);
      const field = document.getElementById('showcaseQuery');
      if (field) {
        field.focus();
        if (field.type !== 'search') field.setSelectionRange(position, position);
      }
    } catch (error) {
      toast(error.message, true);
    }
  }, 300);
});
document.addEventListener('click', async (e) => {
  const button = e.target.closest('button');
  if (!button) return;
  try {
    if (button.dataset.releaseDetail) await openReleaseDossier(button.dataset.releaseDetail);
    if (button.dataset.dossierClose) {
      ++dossierGeneration;
      showcaseDialog().close();
    }
    if (button.dataset.showcaseFocus) await applyShowcase('focus', button.dataset.showcaseFocus);
    if (button.dataset.showcaseReset) {
      Object.assign(S.releaseOptions, {
        q: '',
        genre: 'all',
        sort: 'recent',
        focus: 'all',
      });
      S.releaseOffset = 0;
      if (!S.demo) await api('discovery/releases/preferences', S.releaseOptions);
      await loadReleaseFeed();
    }
  } catch (error) {
    toast(error.message, true);
  }
});

document.addEventListener(
  'click',
  async (e) => {
    const button = e.target.closest('button');
    if (!button || !button.closest('#releaseDossier')) return;
    if (
      !button.dataset.discoverySave &&
      !button.dataset.discoverySearch &&
      !button.dataset.discoveryDismiss
    )
      return;
    e.stopImmediatePropagation();
    const dossier = S.releaseDetails;
    if (!dossier) return;
    const item = dossier.item;
    try {
      if (button.dataset.discoverySearch) {
        showcaseDialog().close();
        S.recovery = null;
        S.replaces = null;
        S.view = 'grouped';
        await search(item.artist + ' ' + item.album);
        return;
      }
      const status = button.dataset.discoveryDismiss
        ? 'dismissed'
        : item.feedback === 'saved'
          ? ''
          : 'saved';
      if (!S.demo) await api('discovery/feedback', { id: item.id, status });
      item.feedback = status;
      if (status === 'dismissed') showcaseDialog().close();
      else paintDossier(showcaseDialog(), item, dossier);
      await loadReleaseFeed(false);
    } catch (error) {
      toast(error.message, true);
    }
  },
  true,
);

function paintDossier(dialog, item, dossier) {
  const state = UIState.capture(dialog);
  dialog.innerHTML = renderDossier(item, dossier);
  UIState.restore(dialog, state);
}
