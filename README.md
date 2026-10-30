# Resonance

A local Soulseek workspace with album-oriented search, recoverable downloads, collection matching and music discovery.

**Release candidate:** the version in [VERSION](VERSION). This is prerelease software; keep a private backup before upgrading.

## Start here

1. Read [requirements](docs/REQUIREMENTS.md).
2. Follow [first-time setup](docs/SETUP.md), including the private engine configuration.
3. Use the [manual](docs/MANUAL.md) for everyday operation and recovery.
4. See the single [features guide](docs/FEATURES.md) for the current scope.

The application runs on `http://127.0.0.1:8765`; its engine normally uses `http://127.0.0.1:5030`. Both are local-only. No account, API key, database, configuration backup or user library is included in the public source or release package. First-time setup generates private keys locally. Never commit the `data/` folder.

## Download or build

Use a Windows prerelease ZIP built by the repository workflow, or build from source:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_release.py --build-engine
```

The engine build requires the .NET SDK specified in `global.json`. The resulting ZIP includes the matching engine source and notices. The application itself does not need Node.js. Node is used for development checks only.

## Development

```sh
python -m unittest discover -s tests -v
npm ci
npm test
npm run test:browser
# Engine unit tests:
dotnet test engine/tests/slskd.Tests.Unit/slskd.Tests.Unit.csproj -p:RunAnalyzers=false
```

Tests use synthetic temporary data and mocked peer operations. Browser tests launch an isolated local service. They must not point at a personal installation. CI runs Python/Node checks and browser tests on Windows and Linux, plus an engine build. Native peer-transfer testing and accessibility checks remain part of release-candidate evaluation.

The Python modules separate storage, identity, library indexing, transfers and supplier transport. The browser has explicit modules for shared state, API access, rendering, collection/search controls and transfers. See [CONTRIBUTING.md](CONTRIBUTING.md) for the release rules.

## Support Resonance

If you enjoy using Resonance and would like to support its development, you can [buy me a coffee](https://buymeacoffee.com/tapeshack). Support is completely optional and always appreciated.

## Licensing and provenance

The first-party Python interface and web client are MIT licensed; see [LICENSE](LICENSE). The separately maintained engine is a modified slskd fork, licensed under AGPL-3.0-only with Additional Terms. Its complete licence is in [engine/LICENSE](engine/LICENSE), with attribution in [engine/NOTICE](engine/NOTICE) and current provenance in [engine/UPSTREAM.json](engine/UPSTREAM.json). Preserve these files and the corresponding source when distributing the engine. This fork is not maintained by, endorsed by or affiliated with the slskd project or its authors.

Music metadata, artwork and articles belong to their respective rights holders. Source attribution and original links remain visible. Publisher access and catalogue coverage can change.

Security reports: use the repository's private security reporting when available; do not post keys, configuration files, databases or diagnostic archives publicly. See [SECURITY.md](SECURITY.md).
