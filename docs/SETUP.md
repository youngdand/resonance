# New user setup

## 1. Install privately

Download the Windows prerelease ZIP from this project's Releases page. Extract it into a normal folder you can write, such as a folder under your user profile. Avoid Program Files and cloud-sync folders for the live SQLite store. Do not run directly from inside the ZIP.

Install Python 3.10+ from python.org if needed, then run `Install-Resonance.cmd`. It creates a `.venv` folder and installs the pinned Python dependencies. An installation error remains visible in the console; fix the reported cause before continuing.

## 2. Configure a new account locally

Run `Setup-New-User.cmd`. Enter:

1. Your Soulseek username.
2. Your Soulseek password; typing is hidden.
3. An absolute completed-downloads folder, or accept the Music/Resonance default under your home folder.
4. An optional existing music folder to share. You can configure this later.

The wizard creates `data/engine.yml`, generates a private engine API key and web password, and links the interface to that engine. It prints neither password nor key. Online discovery starts off. Your private configuration, database and backups must remain outside Git and public uploads. OS user permissions protect these local files; this is not an encrypted credential vault.

If the wizard reports an existing configuration, it does not overwrite it. Edit settings in the application or make a private backup before changing the YAML yourself.

## 3. Start

Run `Start-Resonance-with-Engine.cmd`. It opens the engine console, checks that the API is ready, then starts Resonance and opens the browser at `http://127.0.0.1:8765`.

Keep both console windows open. The interface's connection indicator confirms API access; check the engine's Soulseek login status before expecting peer results. Sharing scans can continue after startup. Let the first scan finish before importing the collection.

Run `Start-Resonance.cmd` alone when your configured engine is already running. For normal shutdown press Ctrl+C in each console and allow the engine to finish writing its cache.

## 4. Existing installation or external engine

Back up your existing `data` folder and actual engine YAML privately. Stop both applications before copying an update. Preserve your live `data` folder; replace application files and the matched engine executable/source from the release. Run `Install-Resonance.cmd` once to install the current pinned dependencies.

Open Settings to set the local engine address, private API key, actual YAML path and collection source. The `Test saved connection` button tests saved values; save edits before using it. Existing external engine data is retained at its configured location. A schema upgrade makes a private pre-migration database backup. Legacy release identifiers are migrated conservatively and saved/dismissed feedback is preserved.

The matched Resonance engine is required for the full batch-recovery and cached-tag contract. Older slskd builds may use a local tag-reading fallback and may not support safe batch retries. Keep the engine and interface from the same candidate package.

## 5. First checks

- In My collection, refresh the shared library or scan configured folders.
- Search for a known album and inspect source, format and edition before queuing.
- Confirm your completed-downloads path in `data/engine.yml` under `directories.downloads`.
- Check Uploads & sharing before enabling folders you did not intend to share.
- Enable online discovery only if you want catalogue and artwork requests.

See the manual for recovery, logging and configuration details.
