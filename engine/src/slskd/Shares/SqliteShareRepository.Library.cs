// <copyright file="SqliteShareRepository.Library.cs" company="Resonance contributors">
//           ▄▄▄▄     ▄▄▄▄     ▄▄▄▄
//     ▄▄▄▄▄▄█  █▄▄▄▄▄█  █▄▄▄▄▄█  █
//     █__ --█  █__ --█    ◄█  -  █
//     █▄▄▄▄▄█▄▄█▄▄▄▄▄█▄▄█▄▄█▄▄▄▄▄█
//   ┍━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ━━━━ ━  ━┉   ┉     ┉
//   │ Copyright (c) 2026 Resonance contributors.
//   │ Copyright (c) 2026 Resonance contributors.
//   │ Modified 2026-10-30: Preserve known tags on failed reads and retry failed parser entries.
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
    using System;
    using System.Collections.Generic;
    using Microsoft.Data.Sqlite;

    public partial class SqliteShareRepository
    {
        private static void EnsureLibrarySchema(SqliteConnection connection)
        {
            using var command = connection.CreateCommand();
            command.CommandText = "CREATE TABLE IF NOT EXISTS library_metadata (maskedFilename TEXT PRIMARY KEY, originalFilename TEXT NOT NULL, size INTEGER NOT NULL, modifiedTicks INTEGER NOT NULL, parserVersion INTEGER NOT NULL, payload TEXT NOT NULL);";
            command.ExecuteNonQuery();
            command.CommandText = "CREATE INDEX IF NOT EXISTS idx_library_original ON library_metadata(originalFilename)";
            command.ExecuteNonQuery();
        }

        public SharedLibraryFile FindCachedLibraryFile(string originalFilename, long size, long modifiedTicks)
        {
            using var connection = GetConnection();
            using var command = connection.CreateCommand();
            command.CommandText = "SELECT payload FROM library_metadata WHERE originalFilename = @path AND size = @size AND modifiedTicks = @ticks AND parserVersion = @version LIMIT 1";
            command.Parameters.AddWithValue("path", originalFilename);
            command.Parameters.AddWithValue("size", size);
            command.Parameters.AddWithValue("ticks", modifiedTicks);
            command.Parameters.AddWithValue("version", SharedLibraryFile.CurrentParserVersion);
            var payload = command.ExecuteScalar() as string;
            return payload?.FromJson<SharedLibraryFile>();
        }

        public void InsertLibraryFile(string originalFilename, long modifiedTicks, SharedLibraryFile file)
        {
            using var connection = GetConnection();
            using var command = connection.CreateCommand();
            if (!file.MetadataRead)
            {
                using var previousCommand = connection.CreateCommand();
                previousCommand.CommandText = "SELECT payload FROM library_metadata WHERE originalFilename = @path LIMIT 1";
                previousCommand.Parameters.AddWithValue("path", originalFilename);
                var previousPayload = previousCommand.ExecuteScalar() as string;
                if (previousPayload is not null)
                {
                    var previous = previousPayload.FromJson<SharedLibraryFile>();
                    file = file with { Artist = previous.Artist, AlbumArtist = previous.AlbumArtist,
                        Album = previous.Album, Title = previous.Title, Track = previous.Track,
                        Disc = previous.Disc, Duration = previous.Duration };
                }
            }
            command.CommandText = "INSERT OR REPLACE INTO library_metadata VALUES (@masked, @path, @size, @ticks, @version, @payload)";
            command.Parameters.AddWithValue("masked", file.File.Filename);
            command.Parameters.AddWithValue("path", originalFilename);
            command.Parameters.AddWithValue("size", file.File.Size);
            command.Parameters.AddWithValue("ticks", modifiedTicks);
            // Failed metadata reads are retained for display but retried on the next scan.
            command.Parameters.AddWithValue("version", file.MetadataRead ? SharedLibraryFile.CurrentParserVersion : 0);
            command.Parameters.AddWithValue("payload", file.ToJson());
            command.ExecuteNonQuery();
        }

        public SharedLibraryPage ReadLibraryPage(string after, int limit)
        {
            using var connection = GetConnection();
            EnsureLibrarySchema(connection);
            using var command = connection.CreateCommand();
            command.CommandText = "SELECT m.maskedFilename, m.payload FROM library_metadata m INNER JOIN files f ON f.maskedFilename = m.maskedFilename WHERE m.maskedFilename > @after ORDER BY m.maskedFilename COLLATE BINARY LIMIT @limit";
            command.Parameters.AddWithValue("after", after ?? string.Empty);
            command.Parameters.AddWithValue("limit", Math.Clamp(limit, 1, 2000) + 1);
            using var transaction = connection.BeginTransaction();
            command.Transaction = transaction;
            // The revision, coverage and page are from the same SQLite read snapshot.
            using var revisionCommand = connection.CreateCommand();
            revisionCommand.Transaction = transaction;
            revisionCommand.CommandText = "SELECT COALESCE(MAX(timestamp), 0) FROM scans";
            var revision = Convert.ToInt64(revisionCommand.ExecuteScalar());
            using var coverageCommand = connection.CreateCommand();
            coverageCommand.Transaction = transaction;
            coverageCommand.CommandText = "SELECT (SELECT COUNT(*) FROM library_metadata m INNER JOIN files f ON f.maskedFilename = m.maskedFilename) = (SELECT COUNT(*) FROM files)";
            var complete = Convert.ToInt64(coverageCommand.ExecuteScalar()) == 1;
            using var reader = command.ExecuteReader();
            var items = new List<SharedLibraryFile>();
            var cursor = after;
            var hasMore = false;
            while (reader.Read())
            {
                if (items.Count == Math.Clamp(limit, 1, 2000)) { hasMore = true; break; }
                cursor = reader.GetString(0);
                items.Add(reader.GetString(1).FromJson<SharedLibraryFile>());
            }
            return new SharedLibraryPage(revision, cursor, hasMore, complete, items);
        }

        public void PreserveEntries(string maskedPath, long timestamp, bool recursive)
        {
            using var connection = GetConnection();
            using var command = connection.CreateCommand();
            command.CommandText = "UPDATE files SET timestamp = @timestamp WHERE maskedFilename = @path OR (@recursive = 1 AND substr(maskedFilename, 1, length(@prefix)) = @prefix); UPDATE directories SET timestamp = @timestamp WHERE name = @path OR (@recursive = 1 AND substr(name, 1, length(@prefix)) = @prefix);";
            command.Parameters.AddWithValue("timestamp", timestamp);
            command.Parameters.AddWithValue("path", maskedPath);
            command.Parameters.AddWithValue("prefix", maskedPath.TrimEnd('\\') + "\\");
            command.Parameters.AddWithValue("recursive", recursive ? 1 : 0);
            command.ExecuteNonQuery();
        }
    }
}
