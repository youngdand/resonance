// <copyright file="ShareScanner.cs" company="JP Dillingham">
//           ▄▄▄▄     ▄▄▄▄     ▄▄▄▄
//     ▄▄▄▄▄▄█  █▄▄▄▄▄█  █▄▄▄▄▄█  █
//     █__ --█  █__ --█    ◄█  -  █
//     █▄▄▄▄▄█▄▄█▄▄▄▄▄█▄▄█▄▄█▄▄▄▄▄█
//   ┍━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ━━━━ ━  ━┉   ┉     ┉
//   │ Copyright (c) JP Dillingham.
//   │ Copyright (c) 2026 Resonance contributors.
//   │ Modified 2026-10-25: Await cancellable workers, retain unreadable entries, and reuse cached metadata.
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

using System.IO;

namespace slskd.Shares
{
    using System;
    using System.Collections.Generic;
    using System.Data;
    using System.Diagnostics;
    using System.Linq;
    using System.Text.RegularExpressions;
    using System.Threading;
    using System.Threading.Tasks;
    using Serilog;
    using slskd.Files;

    /// <summary>
    ///     Shared file cache.
    /// </summary>
    public interface IShareScanner
    {
        /// <summary>
        ///     Gets the cache state monitor.
        /// </summary>
        IStateMonitor<SharedFileCacheState> StateMonitor { get; }

        /// <summary>
        ///     Scans the configured shares and fills the cache.
        /// </summary>
        /// <param name="shares">The list of shares from which to fill the cache.</param>
        /// <param name="options">The current options snapshot.</param>
        /// <param name="repository">The repository to update.</param>
        /// <returns>The operation context.</returns>
        Task ScanAsync(IEnumerable<Share> shares, Options.SharesOptions options, IShareRepository repository);

        /// <summary>
        ///     Cancels the currently running fill operation, if one is running.
        /// </summary>
        /// <returns>A value indicating whether a fill operation was cancelled.</returns>
        bool TryCancelScan();
    }

    /// <summary>
    ///     Shared file cache.
    /// </summary>
    public class ShareScanner : IShareScanner
    {
        /// <summary>
        ///     Initializes a new instance of the <see cref="ShareScanner"/> class.
        /// </summary>
        /// <param name="workerCount"></param>
        /// <param name="fileService"></param>
        /// <param name="soulseekFileFactory"></param>
        public ShareScanner(
            int workerCount,
            FileService fileService,
            ISoulseekFileFactory soulseekFileFactory = null)
        {
            WorkerCount = workerCount;
            Files = fileService;
            SoulseekFileFactory = soulseekFileFactory ?? new SoulseekFileFactory(fileService: Files);

            Flags = Program.Flags ?? new Options.FlagsOptions();
        }

        /// <summary>
        ///     Gets the cache state monitor.
        /// </summary>
        public IStateMonitor<SharedFileCacheState> StateMonitor => State;

        private FileService Files { get; }
        private int WorkerCount { get; }
        private ILogger Log { get; } = Serilog.Log.ForContext<ShareScanner>();
        private IReadOnlyList<Share> Shares { get; set; }
        private ISoulseekFileFactory SoulseekFileFactory { get; }
        private IManagedState<SharedFileCacheState> State { get; } = new ManagedState<SharedFileCacheState>();
        private SemaphoreSlim SyncRoot { get; } = new SemaphoreSlim(1);
        private CancellationTokenSource CancellationTokenSource { get; set; }
        private Options.FlagsOptions Flags { get; set; }

        /// <summary>
        ///     Scans the configured shares and fills the cache.
        /// </summary>
        /// <param name="shares">The list of shares from which to fill the cache.</param>
        /// <param name="options">The current options snapshot.</param>
        /// <param name="repository">The repository to update.</param>
        /// <returns>The operation context.</returns>
        public async Task ScanAsync(IEnumerable<Share> shares, Options.SharesOptions options, IShareRepository repository)
        {
            // obtain the semaphore, or fail if it can't be obtained immediately, indicating that a scan is running.
            if (!await SyncRoot.WaitAsync(millisecondsTimeout: 0))
            {
                Log.Warning("Shared file scan rejected; scan is already in progress.");
                throw new ShareScanInProgressException("Shared files are already being scanned.");
            }

            CancellationTokenSource = CancellationTokenSource.CreateLinkedTokenSource(Program.MasterCancellationTokenSource.Token);
            var cancellationToken = CancellationTokenSource.Token;

            // send control back to the calling context. if we don't do this, the caller will block until
            // directories have been enumerated.
            await Task.Yield();

            try
            {
                State.SetValue(state => state with
                {
                    Filling = true,
                    Filled = false,
                    Cancelled = false,
                    Faulted = false,
                    Errors = 0,
                    FillProgress = 0,
                    Directories = 0,
                    Files = 0,
                    ExcludedDirectories = 0,
                });

                // it's possible that the database was tampered with between the time it was checked at startup and now
                // validate the tables, and if there's an issue, drop and recreate everything.
                if (!repository.TryValidate())
                {
                    Log.Warning("Shared file cache missing or invalid. Re-creating prior to scan.");
                    repository.Create(discardExisting: true);
                    Log.Information("Shared file cache re-created and ready for scan.");
                }

                // Add optional metadata tables to older, valid share caches without discarding them.
                repository.Create();
                var errors = 0;
                var directoryErrors = 0;
                var regexOptions = RegexOptions.Compiled;

                if (!Flags.CaseSensitiveRegEx)
                {
                    regexOptions |= RegexOptions.IgnoreCase;
                }

                var filters = options.Filters
                    .Select(filter => new Regex(filter, regexOptions))
                    .ToList();

                Log.Information("Starting shared file scan");

                var timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

                repository.InsertScan(timestamp, options);

                var sw = new Stopwatch();
                var swSnapshot = 0L;
                sw.Start();

                // note: this should be the only place where we are assigning Shares, so that this is 1) synchronized by SyncRoot
                // and 2) stable throughout the scan.  if this ever changes we'll have to snapshot the value and use it instead
                Shares = shares.ToList();

                if (!Shares.Any())
                {
                    Log.Warning("Aborting shared file scan; no shares configured.");
                }

                foreach (var share in Shares)
                {
                    Log.Debug(share.ToJson());
                }

                Shares.Where(s => !s.IsExcluded).ToList()
                    .ForEach(s => Log.Information("Sharing {Local} as {Remote}", s.LocalPath, s.RemotePath));

                Shares.Where(s => s.IsExcluded).ToList()
                    .ForEach(s => Log.Information("Excluding {Local}", s.LocalPath));

                Log.Information("Enumerating shared directories");
                swSnapshot = sw.ElapsedMilliseconds;

                // note: there's a safer version of this in the FileSafety class that checks for traversal and navigates
                // case sensitivity for different operating systems. this version is stripped down for speed, and because
                // we're not dealing with untrusted data
                static bool IsSubDirectoryOf(string subDirectory, string root, StringComparison stringComparison = StringComparison.OrdinalIgnoreCase)
                {
                    return subDirectory.TrimEnd('/', '\\').Equals(root.TrimEnd('/', '\\'), stringComparison) || // subdirectory literally is the root
                        subDirectory.StartsWith(root.TrimEnd('/', '\\') + Path.DirectorySeparatorChar, stringComparison);
                }

                /*
                    derive a list of all subdirectories to scan by enumerating the subdirectories within each configured
                    share recursively, omitting any directory that matches a filter or that exists within an excluded share

                    we don't enumerate excluded shares because 1) the exclusion is a subdirectory of another share and it
                    will be enumerated once already or 2) the exclusion is not a subdirectory of another share and we don't
                    want to enumerate its directories just to remove them all. this is probably obvious and kind of a worthless comment
                */
                var unmaskedDirectories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var excludedDirectories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

                var excludedPaths = Shares.Where(s => s.IsExcluded).Select(s => s.LocalPath).ToHashSet();

                foreach (var share in Shares)
                {
                    if (share.IsExcluded)
                    {
                        continue;
                    }

                    try
                    {
                        var directories = Directory.EnumerateDirectories(share.LocalPath, "*", new EnumerationOptions()
                        {
                            AttributesToSkip = FileAttributes.Hidden | FileAttributes.System | FileAttributes.ReparsePoint,
                            IgnoreInaccessible = false,
                            RecurseSubdirectories = true,
                        });

                        unmaskedDirectories.Add(share.LocalPath);

                        foreach (var directory in directories)
                        {
                            if (excludedPaths.Any(excludedPath => IsSubDirectoryOf(subDirectory: directory, root: excludedPath)))
                            {
                                excludedDirectories.Add(directory);
                                Log.Debug("Excluding directory {Directory} because it is a subdirectory of an excluded share", directory);
                                continue;
                            }

                            if (filters.Any(f => f.IsMatch(directory)))
                            {
                                excludedDirectories.Add(directory);
                                Log.Debug("Excluding directory {Directory} because it matches one or more share filters", directory);
                                continue;
                            }

                            unmaskedDirectories.Add(directory);
                        }
                    }
                    catch (Exception ex)
                    {
                        Interlocked.Increment(ref errors);
                        Interlocked.Increment(ref directoryErrors);
                        repository.PreserveEntries(share.RemotePath, timestamp, recursive: true);
                        Log.Warning(ex, "Failed to enumerate share {Directory}; keeping its previous entries", share.LocalPath);
                    }
                }

                State.SetValue(state => state with { Directories = unmaskedDirectories.Count, ExcludedDirectories = excludedDirectories.Count });
                Log.Information("Found {Directories} shared directories (and {Excluded} were excluded) in {Elapsed}ms.  Starting file scan.", unmaskedDirectories.Count, excludedDirectories.Count, sw.ElapsedMilliseconds - swSnapshot);
                swSnapshot = sw.ElapsedMilliseconds;

                var current = 0;
                var cached = 0;
                var filtered = 0;

                // set up a function to reliably resolve the Share given a directory; users can define nested shares,
                // so we need to sort to ensure the deepest-nested share is selected first
                var sortedShares = Shares
                    .Where(s => !s.IsExcluded)
                    .OrderByDescending(s => s.LocalPath.Length)
                    .ToList();

                Share ResolveShareFromDirectory(string directory)
                {
                    return sortedShares.First(share => IsSubDirectoryOf(subDirectory: directory, root: share.LocalPath));
                }

                // Parallel.ForEachAsync owns and awaits every worker. A worker fault cancels its siblings;
                // there is no bounded producer that can remain blocked after all readers have failed.
                string MaskPath(Share share, string path)
                {
                    var relative = Path.GetRelativePath(share.LocalPath, path);
                    return relative == "." ? share.RemotePath : share.RemotePath + "\\" + relative.NormalizePathForSoulseek();
                }

                try
                {
                    await Parallel.ForEachAsync(unmaskedDirectories, new ParallelOptions
                    {
                        MaxDegreeOfParallelism = Math.Max(1, WorkerCount),
                        CancellationToken = cancellationToken,
                    }, (directory, token) =>
                    {
                        token.ThrowIfCancellationRequested();
                        var share = ResolveShareFromDirectory(directory);
                        var maskedDirectory = MaskPath(share, directory);
                        repository.InsertDirectory(maskedDirectory, timestamp);
                        try
                        {
                            var infos = new DirectoryInfo(directory).EnumerateFiles("*", new EnumerationOptions
                            {
                                AttributesToSkip = FileAttributes.Hidden | FileAttributes.System | FileAttributes.ReparsePoint,
                                IgnoreInaccessible = false,
                                RecurseSubdirectories = false,
                            });
                            foreach (var info in infos)
                            {
                                token.ThrowIfCancellationRequested();
                                if (filters.Any(filter => filter.IsMatch(info.FullName)))
                                {
                                    Interlocked.Increment(ref filtered);
                                    continue;
                                }
                                var maskedFilename = MaskPath(share, info.FullName);
                                try
                                {
                                    var metadata = repository.FindCachedLibraryFile(info.FullName, info.Length, info.LastWriteTimeUtc.Ticks);
                                    if (metadata == null)
                                    {
                                        metadata = SoulseekFileFactory is SoulseekFileFactory factory
                                            ? factory.Read(info.FullName, maskedFilename)
                                            : new SharedLibraryFile { File = SoulseekFileFactory.Create(info.FullName, maskedFilename) };
                                    }
                                    // Aliases may change even though the physical file is unchanged.
                                    var file = new Soulseek.File(metadata.File.Code, maskedFilename, metadata.File.Size, metadata.File.Extension, metadata.File.Attributes);
                                    metadata = metadata with { File = file };
                                    repository.InsertFile(maskedFilename, info.FullName, info.LastWriteTimeUtc, file, timestamp);
                                    repository.InsertLibraryFile(info.FullName, info.LastWriteTimeUtc.Ticks, metadata);
                                    Interlocked.Increment(ref cached);
                                }
                                catch (OperationCanceledException) { throw; }
                                catch (Exception ex)
                                {
                                    Interlocked.Increment(ref errors);
                                    repository.PreserveEntries(maskedFilename, timestamp, recursive: false);
                                    Log.Warning(ex, "Failed to scan file {Filename}; keeping its previous entry", info.FullName);
                                }
                            }
                        }
                        catch (OperationCanceledException) { throw; }
                        catch (Exception ex)
                        {
                            Interlocked.Increment(ref errors);
                            Interlocked.Increment(ref directoryErrors);
                            repository.PreserveEntries(maskedDirectory, timestamp, recursive: true);
                            Log.Warning(ex, "Failed to scan directory {Directory}; keeping its previous entries", directory);
                        }
                        var completed = Interlocked.Increment(ref current);
                        State.SetValue(state => state with { FillProgress = completed / (double)unmaskedDirectories.Count, Files = cached, Errors = errors });
                        return ValueTask.CompletedTask;
                    });
                    cancellationToken.ThrowIfCancellationRequested();
                    if (directoryErrors > 0)
                    {
                        // An unreadable subtree may now contain an excluded path. Do not serve a
                        // partially reconciled index or prune unseen entries after incomplete enumeration.
                        State.SetValue(state => state with { Errors = errors });
                        throw new IOException($"Could not enumerate {directoryErrors} directories. Previous entries retained; sharing remains unavailable until a successful scan.");
                    }
                    Log.Information("Scan found {Files} files, cached {Cached}, and filtered {Filtered} in {Elapsed}ms", cached + filtered, cached, filtered, sw.ElapsedMilliseconds - swSnapshot);
                    swSnapshot = sw.ElapsedMilliseconds;

                    var deletedFiles = repository.PruneFiles(olderThanTimestamp: timestamp);
                    var deletedDirectories = repository.PruneDirectories(olderThanTimestamp: timestamp);

                    Log.Information("Removed or renamed {Files} files and {Directories} directories in {Elapsed}ms", deletedFiles, deletedDirectories, sw.ElapsedMilliseconds - swSnapshot);

                    Log.Information("Rebuilding filename index...");
                    repository.RebuildFilenameIndex();
                    Log.Information("Filename index rebuild complete");

                    Log.Debug("Vacuuming...");
                    repository.Vacuum();
                    Log.Debug("Vacuumed successfully");

                    Log.Debug("Checkpointing...");
                    repository.Checkpoint();
                    Log.Debug("Checkpointed successfully");
                }
                catch (OperationCanceledException)
                {
                    // important! don't try to delete stale files in this case; unscanned records will have a stale timestamp
                    Log.Warning("Shared file scan cancelled successfully");

                    State.SetValue(state => state with { Filling = false, Cancelled = true, Filled = false });
                    repository.FlagLatestScanAsSuspect();
                    return;
                }

                repository.UpdateScan(timestamp, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                if (errors > 0)
                {
                    repository.FlagLatestScanAsSuspect();
                    Log.Warning("Share scan completed with {Errors} errors; previous entries for unreadable paths were retained", errors);
                }

                var directoryCount = repository.CountDirectories();
                var fileCount = repository.CountFiles();

                State.SetValue(state => state with
                {
                    Filling = false,
                    Faulted = false,
                    Filled = true,
                    FillProgress = 1,
                    Directories = directoryCount,
                    Files = fileCount,
                    Errors = errors,
                });

                Log.Debug($"Shared file cache created or updated in {sw.ElapsedMilliseconds}ms.  Directories: {directoryCount}, Files: {fileCount}");
            }
            catch (Exception ex)
            {
                State.SetValue(state => state with { Filling = false, Faulted = true, Filled = false, FillProgress = 0 });
                Log.Warning(ex, "Encountered error during scan of shared files: {Message}", ex.Message);
                throw;
            }
            finally
            {
                var cts = CancellationTokenSource;
                CancellationTokenSource = null;
                cts?.Dispose();

                SyncRoot.Release();
            }
        }

        /// <summary>
        ///     Cancels the currently running fill operation, if one is running.
        /// </summary>
        /// <returns>A value indicating whether a fill operation was cancelled.</returns>
        public bool TryCancelScan()
        {
            if (CancellationTokenSource != null)
            {
                CancellationTokenSource.Cancel();
                return true;
            }

            return false;
        }
    }
}