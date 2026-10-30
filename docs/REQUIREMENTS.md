# Requirements

## Windows release

- Windows 10/11, 64-bit.
- Python 3.10 or later, including the Python launcher or Python on PATH.
- A current Firefox, Chrome or Edge browser with JavaScript enabled.
- Internet access and a Soulseek account for peer searches, transfers and chat.
- Disk space for the application, private metadata/cache, temporary downloads and completed music.
- Read access to shared/scanned music; write access to the private application data and download folders.

The release includes a self-contained Windows x64 engine; a separate .NET runtime is not required to run that packaged executable. Building the engine requires the .NET SDK in `global.json`. Python dependencies are pinned in `requirements.txt`; the installer creates `.venv` rather than changing global packages.

Local ports are normally 8765 for Resonance and 5030 for the engine. Keep these HTTP ports on loopback. Do not expose the interface to the Internet or forward these ports. The engine's Soulseek listening port is separate; configure it according to your network and Soulseek requirements.

A music library is optional for country release listings. Related discovery and library-artist matching need indexed artist metadata. Online catalogue lookups need no shipped shared key; the engine API key is generated locally during setup. Some providers may be unavailable or rate limited.

## Source development

- Python and dependencies above.
- Node.js 20+ and `npm ci` for JavaScript and browser tests; not needed for normal application use.
- The pinned .NET SDK for engine tests and builds.
- Git for contributing and release-source verification.

Linux/macOS source execution is possible using Python and a compatible engine build. The supplied `.cmd` launchers and packaged executable target Windows. Cross-platform tests do not constitute a native Windows peer-transfer or accessibility certification.
