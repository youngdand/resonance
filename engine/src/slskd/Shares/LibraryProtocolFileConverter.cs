// <copyright file="LibraryProtocolFileConverter.cs" company="Resonance contributors">
//           ▄▄▄▄     ▄▄▄▄     ▄▄▄▄
//     ▄▄▄▄▄▄█  █▄▄▄▄▄█  █▄▄▄▄▄█  █
//     █__ --█  █__ --█    ◄█  -  █
//     █▄▄▄▄▄█▄▄█▄▄▄▄▄█▄▄█▄▄█▄▄▄▄▄█
//   ┍━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ━━━━ ━  ━┉   ┉     ┉
//   │ Copyright (c) 2026 Resonance contributors.
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
    using System.Collections.Generic;
    using System.Linq;
    using System.Text.Json;
    using System.Text.Json.Serialization;

    // Soulseek.File's constructor collections do not bind to its public collection types
    // in System.Text.Json. Persist a small, explicit DTO rather than relying on that constructor.
    public sealed class LibraryProtocolFileConverter : JsonConverter<Soulseek.File>
    {
        public override Soulseek.File Read(ref Utf8JsonReader reader, System.Type typeToConvert, JsonSerializerOptions options)
        {
            var data = JsonSerializer.Deserialize<ProtocolFile>(ref reader, options);
            return new Soulseek.File(data.Code, data.Filename, data.Size, data.Extension,
                data.Attributes.Select(a => new Soulseek.FileAttribute((Soulseek.FileAttributeType)a.Type, a.Value)));
        }
        public override void Write(Utf8JsonWriter writer, Soulseek.File value, JsonSerializerOptions options)
        {
            JsonSerializer.Serialize(writer, new ProtocolFile
            {
                Code = value.Code, Filename = value.Filename, Size = value.Size, Extension = value.Extension,
                Attributes = value.Attributes.Select(a => new ProtocolAttribute { Type = (int)a.Type, Value = a.Value }).ToList(),
            }, options);
        }
        public sealed record ProtocolFile
        {
            public int Code { get; init; }
            public string Filename { get; init; }
            public long Size { get; init; }
            public string Extension { get; init; }
            public List<ProtocolAttribute> Attributes { get; init; } = [];
        }
        public sealed record ProtocolAttribute
        {
            public int Type { get; init; }
            public int Value { get; init; }
        }
    }
}
