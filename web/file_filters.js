function filtered(files) {
  return files
    .filter(
      (f) =>
        S.settings.formats.includes(fmt(f)) &&
        !(S.settings.blocked || []).includes(f.username) &&
        (!S.settings.hideOwned || f.ownership !== 'owned') &&
        (!Number(S.settings.minBitrate) ||
          !['mp3', 'm4a', 'aac', 'ogg', 'opus', 'wma'].includes(fmt(f)) ||
          Number(f.bitrate) >= Number(S.settings.minBitrate)),
    )
    .sort(
      (a, b) =>
        Number(b.speed || 0) - Number(a.speed || 0) ||
        Number(b.slots) - Number(a.slots) ||
        a.username.localeCompare(b.username) ||
        a.filename.localeCompare(b.filename),
    );
}
