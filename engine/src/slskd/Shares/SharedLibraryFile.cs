// <copyright file="SharedLibraryFile.cs" company="Resonance contributors">
//           ▄▄▄▄     ▄▄▄▄     ▄▄▄▄
//     ▄▄▄▄▄▄█  █▄▄▄▄▄█  █▄▄▄▄▄█  █
//     █__ --█  █__ --█    ◄█  -  █
//     █▄▄▄▄▄█▄▄█▄▄▄▄▄█▄▄█▄▄█▄▄▄▄▄█
//   ┍━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ━━━━ ━  ━┉   ┉     ┉
//   │ Copyright (c) 2026 Resonance contributors.
//   │ Copyright (c) 2026 Resonance contributors.
//   │ Modified 2026-10-30: Revisioned cached music metadata and parser retry contract.
//   │
//   │ This program is free software: you can redistribute it and/or modify
//   │ it under the terms of the GNU Affero General Public License as published
//   │ by the Free Software Foundation, version 3.
//   │
//   │ This program is distributed in the hope that it will be useful,
//   │ but WITHOUT ANY WARRANTY; without even the implied warranty of
//   │ MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//   │ GNU Affero General Public License for more details.
//   │
//   │ You should have received a copy of the GNU Affero General Public License
//   │ along with this program.  If not, see https://www.gnu.org/licenses/.
//   │
//   │ This program is distributed with Additional Terms pursuant to Section 7
//   │ of the AGPLv3.  See the LICENSE file in the root directory of this
//   │ project for the complete terms and conditions.
//   │
//   │ https://slskd.org
//   │
//   ├╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌ ╌ ╌╌╌╌ ╌
//   │ SPDX-FileCopyrightText: JP Dillingham
//   │ SPDX-License-Identifier: AGPL-3.0-only
//   ╰───────────────────────────────────────────╶──── ─ ─── ─  ── ──┈  ┈
// </copyright>

namespace slskd.Shares
{
    /// <summary>Local-only metadata; never added to Soulseek protocol responses.</summary>
    public record SharedLibraryFile
    {
        public const int CurrentParserVersion = 2;
        [System.Text.Json.Serialization.JsonConverter(typeof(LibraryProtocolFileConverter))]
        public Soulseek.File File { get; init; }
        public string Artist { get; init; } = string.Empty;
        public string AlbumArtist { get; init; } = string.Empty;
        public string Album { get; init; } = string.Empty;
        public string Title { get; init; } = string.Empty;
        public uint Track { get; init; }
        public uint Disc { get; init; }
        public double Duration { get; init; }
        public bool MetadataRead { get; init; }
    }

    public record SharedLibraryPage(long Revision, string After, bool HasMore, bool Complete, System.Collections.Generic.IReadOnlyList<SharedLibraryFile> Items);
}
