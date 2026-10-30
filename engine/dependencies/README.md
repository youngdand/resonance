# Third-party corresponding source

Soulseek.NET 10.0.2: original source at commit
94fba7d4056796af067e6d7b2a8628099723cd26, as recorded by its NuGet package.
https://github.com/jpdillingham/Soulseek.NET/tree/94fba7d4056796af067e6d7b2a8628099723cd26
The complete original source archive is included. GPL-3.0-only; see its LICENSE.

TagLibSharp 2.3.0: release TaglibSharp-2.3.0.0, commit
b5ae84f2e84087bf160bb0471420200dd2b5d809.
https://github.com/mono/taglib-sharp/tree/b5ae84f2e84087bf160bb0471420200dd2b5d809
Source/build files and original licence are included. Large binary sample media
under src/TaglibSharp.Tests/samples and raw-samples are omitted; no library source
is changed. The exact upstream archive, including those media fixtures, is at
https://codeload.github.com/mono/taglib-sharp/zip/b5ae84f2e84087bf160bb0471420200dd2b5d809
LGPL-2.1-only; see its COPYING. Extract and build src/TaglibSharp/TaglibSharp.csproj
to modify/rebuild the library. To relink the engine, replace its TagLibSharp NuGet
reference with a project reference to your modified library, then rebuild the
engine with the provided build script. No signing restriction prevents this.

Other dependency versions are locked by the project and NuGet restore assets.
Package attribution/licence files and a resolved package list are included.
The .NET runtime's licence/notices accompany the Windows executable.
