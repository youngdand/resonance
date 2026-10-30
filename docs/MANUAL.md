# User manual

## Workspace and settings

Use the left navigation for For you, Search, Downloads, My collection, Browse users, Uploads & sharing and Chat. `/` focuses search; Ctrl+, opens Settings. Demo mode uses sample records and makes no peer downloads or message sends.

Settings hold the local engine URL, private API key, YAML path, collection source, music folders and hidden users. The key is retained when its field is left blank. Save edits before `Test saved connection`. Engine API availability and Soulseek login readiness are separate: an accessible engine can still be disconnected from Soulseek.

## Find music

Search with an artist, album or track name. Audio filters are shared across search and browsing. Hide owned removes only confident matches; possible matches remain visible. A confident track match uses title, artist context and duration. Hidden users are local result exclusions; use sharing controls to block uploads.

Sources are ranked by reported upload speed. Open an album group to inspect a bounded track preview. Page through album groups for broad searches; browse the peer for the complete shared folder. Live updates retain open groups, keyboard focus and position.

`Get full album` fetches a full folder inventory. Choose an audio format, optionally skip confidently owned tracks, and confirm. Shared images and PDF booklets inside that album's folder tree are included even when audio filters exclude their extensions. Nested discs and artwork keep their subfolders. The app cannot guarantee the peer shared a complete or correctly labelled release.

## Downloads and recovery

Requests are saved locally before contacting the engine. Progress reflects transferred bytes; speed and ETA depend on available measurements. Queued, failed, cancelled, succeeded and unconfirmed are distinct states.

An **Unconfirmed** request means a response was lost or acceptance could not be established. Use **Reconcile / retry**. Resonance checks the stable engine batch and retries missing work with the same operation ID. If the engine is unreachable, the request remains uncertain. Do not assume an absent response means the engine rejected it.

An album's **Reconcile album / retry missing files** checks its expected-file manifest. All selected audio and artwork must succeed before the album is complete. A peer denial or confirmed failure can be recovered with **Find another source**. The original search and attempts remain attached. Confirm the track and edition; replacement files retain the intended album destination even if the new peer's remote folder differs.

Cancel affects an identifiable engine transfer. If acceptance is uncertain, reconciliation must establish it first. Clear completed removes successful list entries and keeps music files and failed requests. It does not empty the download folder.

Completed files go to `directories.downloads` in the engine YAML. Partials go to `directories.incomplete`. New setup creates these folders; existing configurations may use different locations. Album destinations are relative subfolders beneath the completed-downloads root.

## Collection

The recommended source imports the engine's complete shared-library cache. Rescan shared library refreshes the engine first, then imports the resulting metadata. Stable snapshots with retained-file warnings remain usable; a faulted, cancelled or incomplete scan does not replace the last good collection.

Selected-folder mode can include unshared music. Every configured root must be available; a multi-root enumeration failure retains the last coherent snapshot. Removing a configured root removes its tracks after a successful scan. Temporary tag-read failures retain the last known tags and are retried later. Scans never move or edit music files.

Search the collection and use Previous/Next to reach every matching page. Album totals distinguish identical titles by different artists. Collection matching indexes are rebuilt only when the stored library revision changes.

## Browse users

Enter a Soulseek username or use Browse from a result, upload or conversation. Use folders, artist/album/track views, sorting and within-user search. Views and folder scroll positions are retained per user. Album counts reflect enabled filters. Folder-derived artist/album names are hints; open the full album preview before queuing.

## Uploads and sharing

Review outgoing files and recipients. Stop individual transfers or block a user. Shared folder edits affect everyone; per-user genre or filetype sharing rules are not implied.

Folder entries support absolute paths, `[Alias]path` aliases, and `!path` or `-path` exclusions supported by the engine. Keep exclusions when editing an existing configuration. Pause preserves a resume list, then clears active shares; Resume restores it. The app waits for the engine to confirm folder changes before requesting a scan. Read any pending-confirmation warning: saving YAML does not mean the engine has already applied it.

YAML comments are preserved. A private change journal and private configuration backups allow recovery if the file and database updates are interrupted. If the file was changed externally during recovery, inspect the warning and compare the private backup before making further changes. Never post these files to an issue.

## Chat

Open a conversation from a user link or enter a username. Messages are sent only when you press Send. Refreshes do not overlap and drafts are retained locally in the current browser session. A failed or blocked send remains an error; an API connection does not guarantee the peer is online.

## For you

Related discovery uses the indexed collection. Country new releases are independent of the collection. Use genre, date, release type, search and score filters; choose saved discoveries when returning to earlier finds. UK listings use the existing weekly archive; international picks have explicitly unverified local availability.

Explore a release for publisher previews, review scores, release features, tracklists and original links. Scores use their original scales. Features and listings are not labelled as critic reviews. No match in a recent index is not proof that no review exists. Full articles remain at the source; the application does not invent opinions or a synthesized review.

Missing artwork is searched as cards approach the viewport, with limited concurrent requests and shared caches. Exact artist/album/edition matching is conservative. A broken image can try the next supplier. A temporary missing result expires; source failures do not block browsing. Some covers will remain unavailable.

Online discovery sends the selected query or catalogue identifiers to the displayed providers and fetches images from known supplier hosts. It does not upload audio, local paths or a complete library. Turning it off prevents newly dispatched catalogue lookups; cached metadata remains readable, and remote artwork is hidden.

## Diagnostics, backup and troubleshooting

Diagnostics retains errors after notifications disappear. Download a report after reproducing a problem. Reports redact known credentials and exclude the database, configuration, library and message bodies, but inspect them before sharing. Give the action, visible message and candidate version when reporting an issue.

Back up `data/` and your actual engine YAML only while the applications are stopped, or use an appropriate SQLite backup. Keep backups private. To restore a pre-upgrade database, stop Resonance, keep the current store as a private backup, copy the chosen database back as `data/resonance.db`, and remove only the matching stale SQLite WAL/SHM sidecars after shutdown. Restore its compatible application version or retry a tested migration. Never overwrite the music itself.

- **Port already in use:** stop the duplicate process, or deliberately configure another port; do not expose the server on all interfaces.
- **Engine not ready:** read its console for the actual configuration/port/login/scan error. Reinstalling Python will not fix an engine failure.
- **Version mismatch:** stop the interface, copy the complete matched package, restart and hard-refresh the browser. Version metadata is generated from one source.
- **Unavailable drive or scan failure:** reconnect the drive and retry; the prior coherent collection remains available.
- **Provider unavailable:** use cached material and retry after the reported cooldown. No review, artwork or worldwide release completeness is guaranteed.
