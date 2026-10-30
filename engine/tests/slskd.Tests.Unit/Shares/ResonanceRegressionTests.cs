// <copyright file="ResonanceRegressionTests.cs" company="Resonance contributors">
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

namespace slskd.Tests.Unit.Shares;

using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Moq;
using slskd.Shares;
using Xunit;

public sealed class ResonanceRegressionTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "slskd-regression-" + Guid.NewGuid());

    public ResonanceRegressionTests() => Directory.CreateDirectory(root);
    public void Dispose() => Directory.Delete(root, recursive: true);
    private SqliteShareRepository Repository()
    {
        var repository = new SqliteShareRepository($"Data Source={Guid.NewGuid()};Mode=Memory;Cache=Shared");
        repository.Create();
        return repository;
    }
    private static Soulseek.File File(string name, long size = 1) => new(1, name, size, "flac", []);

    [Fact]
    public void RootSeparatorIsPreserved()
    {
        var driveRoot = Path.GetPathRoot(root);
        var share = new Share("[Music]" + driveRoot);
        Assert.Equal(driveRoot, share.LocalPath);
        if (OperatingSystem.IsWindows())
        {
            Assert.Equal(@"E:\", new Share(@"[Music]E:\").LocalPath);
            Assert.Equal(@"\\server\music\", new Share(@"[Music]\\server\music\").LocalPath);
        }
    }

    [Fact]
    public void BracketsInPathDoNotBecomePartOfAlias()
    {
        var share = new Share("[Music]" + Path.Combine(root, "[Album]"));
        Assert.Equal("Music", share.Alias);
        Assert.EndsWith("[Album]", share.LocalPath);
    }

    [Fact]
    public async Task WorkerFaultWithMoreThanQueueCapacityTerminates()
    {
        for (var i = 0; i < 1100; i++) Directory.CreateDirectory(Path.Combine(root, i.ToString()));
        var repository = new Mock<IShareRepository>();
        repository.Setup(r => r.TryValidate()).Returns(true);
        repository.Setup(r => r.InsertDirectory(It.IsAny<string>(), It.IsAny<long>())).Throws(new IOException("database unavailable"));
        var scanner = new ShareScanner(4, null, Mock.Of<ISoulseekFileFactory>());
        await Assert.ThrowsAsync<IOException>(() => scanner.ScanAsync([new Share("[Music]" + root)], new Options.SharesOptions(), repository.Object).WaitAsync(TimeSpan.FromSeconds(10)));
        Assert.True(scanner.StateMonitor.CurrentValue.Faulted);
        Assert.False(scanner.StateMonitor.CurrentValue.Filling);
    }

    [Fact]
    public async Task UnreadableFileDoesNotSkipItsSiblingsOrPruneItsPreviousEntry()
    {
        System.IO.File.WriteAllText(Path.Combine(root, "bad.flac"), "x");
        System.IO.File.WriteAllText(Path.Combine(root, "good.flac"), "x");
        using var repository = Repository();
        repository.InsertDirectory("Music", 1);
        repository.InsertFile(@"Music\bad.flac", Path.Combine(root, "bad.flac"), DateTime.UtcNow, File(@"Music\bad.flac"), 1);
        repository.InsertFile(@"Music\deleted.flac", "deleted", DateTime.UtcNow, File(@"Music\deleted.flac"), 1);
        var factory = new Mock<ISoulseekFileFactory>();
        factory.Setup(f => f.Create(It.IsAny<string>(), It.IsAny<string>())).Returns((string local, string masked) => local.EndsWith("bad.flac") ? throw new IOException("locked") : File(masked));
        var scanner = new ShareScanner(1, null, factory.Object);
        await scanner.ScanAsync([new Share("[Music]" + root)], new Options.SharesOptions(), repository);
        Assert.Equal(2, repository.CountFiles());
        Assert.Contains(repository.ListFiles(includeFullPath: true), f => f.Filename == @"Music\good.flac");
        Assert.True(repository.FindLatestScan().Suspect);
        Assert.Equal(1, scanner.StateMonitor.CurrentValue.Errors);
    }

    [Fact]
    public async Task UnchangedFileReusesMetadataButChangedFileIsReadAgain()
    {
        var path = Path.Combine(root, "track.flac");
        System.IO.File.WriteAllText(path, "x");
        var info = new FileInfo(path);
        using var repository = Repository();
        repository.InsertLibraryFile(path, info.LastWriteTimeUtc.Ticks, new SharedLibraryFile { File = File(@"Music\track.flac"), Artist = "Artist", Album = "Album", MetadataRead = true });
        var factory = new Mock<ISoulseekFileFactory>(MockBehavior.Strict);
        factory.Setup(f => f.Create(path, @"Music\track.flac")).Returns(File(@"Music\track.flac", 2));
        var scanner = new ShareScanner(1, null, factory.Object);
        await scanner.ScanAsync([new Share("[Music]" + root)], new Options.SharesOptions(), repository);
        factory.Verify(f => f.Create(It.IsAny<string>(), It.IsAny<string>()), Times.Never);
        Assert.Equal("Artist", repository.ReadLibraryPage("", 10).Items.Single().Artist);
        System.IO.File.WriteAllText(path, "xx");
        await Task.Delay(2);
        await scanner.ScanAsync([new Share("[Music]" + root)], new Options.SharesOptions(), repository);
        factory.Verify(f => f.Create(path, @"Music\track.flac"), Times.Once);
    }

    [Fact]
    public void FailedTagReadRetainsGoodMetadataAndIsRetried()
    {
        using var repository = Repository();
        var file = File(@"Music\track.flac");
        repository.InsertFile(file.Filename, "track", DateTime.UtcNow, file, 1);
        repository.InsertLibraryFile("track", 10, new SharedLibraryFile { File = file, Artist = "Known artist", Album = "Known album", Title = "Known title", MetadataRead = true });
        repository.InsertLibraryFile("track", 20, new SharedLibraryFile { File = file, MetadataRead = false });
        var retained = repository.ReadLibraryPage("", 10).Items.Single();
        Assert.Equal("Known artist", retained.Artist);
        Assert.Equal("Known album", retained.Album);
        Assert.Equal("Known title", retained.Title);
        Assert.Null(repository.FindCachedLibraryFile("track", file.Size, 20));
    }

    [Fact]
    public void LibraryPagesAreStableAndPrunedFilesAreNotExported()
    {
        using var repository = Repository();
        repository.InsertScan(123, new Options.SharesOptions());
        foreach (var name in new[] { "a", "b", "c" })
        {
            var masked = "Music\\" + name + ".flac";
            repository.InsertFile(masked, name, DateTime.UtcNow, File(masked), name == "c" ? 1 : 2);
            repository.InsertLibraryFile(name, 0, new SharedLibraryFile { File = File(masked), MetadataRead = true });
        }
        repository.PruneFiles(2);
        var first = repository.ReadLibraryPage("", 1);
        var second = repository.ReadLibraryPage(first.After, 1);
        Assert.Equal(123, first.Revision);
        Assert.True(first.HasMore);
        Assert.False(second.HasMore);
        Assert.True(first.Complete);
        Assert.Equal(@"Music\b.flac", second.Items.Single().File.Filename);
        Assert.True(repository.TryValidate());
    }

    [Fact]
    public async Task IncompleteDirectoryEnumerationDoesNotPruneOrPublishTheIndex()
    {
        using var repository = Repository();
        repository.InsertFile(@"Music\previous.flac", "previous", DateTime.UtcNow, File(@"Music\previous.flac"), 1);
        var scanner = new ShareScanner(1, null, Mock.Of<ISoulseekFileFactory>());
        var missing = Path.Combine(root, "missing-directory");
        await Assert.ThrowsAsync<IOException>(() => scanner.ScanAsync([new Share("[Music]" + missing)], new Options.SharesOptions(), repository));
        Assert.Equal(1, repository.CountFiles());
        Assert.True(scanner.StateMonitor.CurrentValue.Faulted);
        Assert.False(scanner.StateMonitor.CurrentValue.Filled);
        Assert.Null(repository.FindLatestScan().EndedAt);
    }

    [Fact]
    public async Task CancellationDoesNotMarkTheScanCompleteOrPruneOldEntries()
    {
        var path = Path.Combine(root, "track.flac");
        System.IO.File.WriteAllText(path, "x");
        using var repository = Repository();
        repository.InsertFile(@"Music\previous.flac", "previous", DateTime.UtcNow, File(@"Music\previous.flac"), 1);
        var factory = new Mock<ISoulseekFileFactory>();
        var scanner = new ShareScanner(1, null, factory.Object);
        factory.Setup(f => f.Create(It.IsAny<string>(), It.IsAny<string>())).Returns((string local, string masked) => { scanner.TryCancelScan(); return File(masked); });
        await scanner.ScanAsync([new Share("[Music]" + root)], new Options.SharesOptions(), repository);
        Assert.True(scanner.StateMonitor.CurrentValue.Cancelled);
        Assert.False(scanner.StateMonitor.CurrentValue.Filled);
        Assert.Null(repository.FindLatestScan().EndedAt);
        Assert.Contains(repository.ListFiles(includeFullPath: true), f => f.Filename == @"Music\previous.flac");
    }

    [Fact]
    public void RedactedOptionsDoNotChangeOriginalSecrets()
    {
        var options = new Options { Soulseek = new Options.SoulseekOptions { Password = "do-not-log-this" } };
        Assert.DoesNotContain("do-not-log-this", options.Redact().ToJson());
        Assert.Equal("do-not-log-this", options.Soulseek.Password);
    }
}
