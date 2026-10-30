const artworkFormats = new Set([
  'jpg',
  'jpeg',
  'png',
  'webp',
  'gif',
  'bmp',
  'tif',
  'tiff',
  'avif',
  'pdf',
]);
const isArtwork = (f) => artworkFormats.has(fmt(f));
function albumQueueSelection(audio, artwork, chosen, skip, includeExisting = false) {
  const keepHide = S.settings.hideOwned;
  S.settings.hideOwned = skip;
  let tracks;
  try {
    tracks = filtered(audio).filter(
      (f) => (includeExisting || !f.localStatus) && (chosen === 'all' || fmt(f) === chosen),
    );
  } finally {
    S.settings.hideOwned = keepHide;
  }
  return [...tracks, ...artwork.filter((f) => includeExisting || !f.localStatus)];
}
