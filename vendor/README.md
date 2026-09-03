# PPTXGenJS distribution-only patch

H3-Slides uses PPTXGenJS 4.0.1-h3.1, derived from the official 4.0.1 npm
tarball. Both JavaScript entry points, the TypeScript declarations, README
and MIT license are copied **byte-for-byte**, not rewritten.

The package metadata removes the unused image-size dependency and its browser
mapping. The local package has a distinct version, is private, and omits upstream
development/build scripts and devDependencies. H3-Slides also no longer imports
image-size: image dimensions come from Chromium's already decoded image.

The root npm override makes Slidev and H3-Slides resolve the same local package;
it does not just suppress advisory IDs or override the vulnerable library's version.
The code contains no new parser for ICNS/HEIF/JXL.

provenance.json records the original tarball URL/integrity, the patch and hashes.
Run **node scripts/vendor-pptxgenjs.mjs** for an offline verification.
The maintainer-only **--import** option recreates the distribution from that
verified tarball, and refuses to overwrite an existing vendor folder.
No credentials, build toolchain, git clone, global installation or symlink
privileges are required by the end user's installer.

When updating upstream, review whether this patch is still needed. Update the
version/integrity intentionally, review metadata and run the dependency,
PPTX/PDF and Slidev tests plus npm audit. Never replace the override solely to
make an audit report green. Restore the official package when its dependency
tree no longer includes the affected library.
