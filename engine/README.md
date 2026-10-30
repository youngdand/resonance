# Resonance Engine

This is a modified version of slskd.  It is not maintained by, endorsed by,
or affiliated with the slskd project or its author(s).

Modified 2026-10-25 by Resonance contributors, based on upstream commit
99171c6577f53b28e1e2238a205c04243c6256d5.

The full upstream AGPL-3.0 licence and Additional Terms are in LICENSE.
Original copyright notices are retained in source files. The independent
Resonance Python frontend has its own licence in its distribution folder.

Changes: preserve Windows drive and UNC roots, await/cancel scan workers together,
retain unreadable-file index entries and expose warning counts, redact startup
configuration and remove configuration value-change logging, initialise shares
without blocking connection startup, cache local music tags and technical metadata
for unchanged files, export local metadata in revision-checked pages, and return
structured browse errors with deadlines and cancellation.

The engine uses Soulseek.NET major 170, minor 1782934051. The published reserved
minor range and protocol documentation were checked on 2026-10-25; this number
is outside the upstream reserved range and no conflict was found. It is not a
claim of official registration or endorsement. Recheck before a public release.

The main user interface is the separate Resonance app. The engine serves a small
status/licence/source landing page instead of the upstream branded web interface.
The HTTP API, protocol library, rooms, messages and transfer services remain.

Build: install .NET SDK 10, then run `dotnet test tests/slskd.Tests.Unit` and
`dotnet publish src/slskd -c Release -r win-x64 --self-contained true
-p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true`.
Run `python build_engine.py` to build, test and package the engine, copying
the source archive and LICENSE into wwwroot. The script accepts --dotnet and
--output paths. The source includes GPL/LGPL dependency source under dependencies. The configuration format and SLSKD_ environment-variable
prefix remain compatible. Follow the migration instructions supplied with the
Resonance bundle to preserve existing configuration and data.
