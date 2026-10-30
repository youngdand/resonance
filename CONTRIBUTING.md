# Contributing

Keep changes focused on the documented behaviour. Run the Python, Node, real-browser and engine tests before proposing a change. Use synthetic fixtures; never upload a working installation, personal configuration, diagnostic archive, database or music.

The canonical version is VERSION. The service generates browser build metadata and the engine reads the same file. Do not insert separate version literals into browser assets.

Use `python scripts/build_release.py` to create distributables from the explicit release manifest. The builder rejects private runtime files and secret-shaped content. Do not package with a recursive ZIP of a live installation. Corresponding engine source and upstream licences must accompany the executable. Keep the engine delta small and document its current provenance in engine/UPSTREAM.json.

Python uses Black; web assets use Prettier. Tests should cover observable outcomes, concurrent actions, lost replies, restart recovery, partial scans and stale asynchronous responses. Changing a contract requires updating its callers and regression tests together.

Before promoting a candidate, verify a clean Windows installation, an upgrade retaining private data, drive roots/UNC/Unicode paths, successful/denied/resumed transfers with dedicated test accounts, sharing changes and rollback, chat, keyboard use, zoom and a long session. Do not describe mocked tests as live peer-transfer validation.
