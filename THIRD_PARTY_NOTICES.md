# Third-party components

The project's own modified source and attribution are described in `LICENSE`
and `NOTICE`. Dependencies keep their respective licenses; the project license
does not replace those terms. A portable build places complete, unmodified
license texts under `licenses/` and records their SHA-256 hashes and versions in
`licenses/manifest.json`.

The following descriptions are taken from the locked Python distributions and
their installed license files. See the original texts for copyright notices,
bundled components, conditions, and exceptions.

| Component | License or notice summary |
| --- | --- |
| Python 3.12 | Python Software Foundation license and historical/bundled notices in Python's complete `LICENSE.txt`. |
| cx_Freeze | PSF-2.0; used to generate the executable and bootstrap. |
| freeze-core | MIT; executable launcher support used by cx_Freeze. |
| opencv-python | Apache 2.0 metadata; both `LICENSE.txt` and `LICENSE-3RD-PARTY.txt` are included. |
| NumPy | BSD-3-Clause, 0BSD, MIT, Zlib, and CC0-1.0 metadata; the entire installed bundled license tree is included. |
| pymemuc | MIT. This Python wrapper is separate from the MEmu application. |
| psutil | BSD-3-Clause. |
| pypresence | MIT. |
| Pillow | MIT-CMU, including the original Python Imaging Library notices. |
| ttkbootstrap | MIT and Apache-2.0-or-BSD-2-Clause metadata; the installed original license is included. |
| requests | Apache-2.0; original LICENSE and NOTICE are included. |
| urllib3 | MIT. |
| certifi | MPL-2.0. |
| idna | BSD-3-Clause. |
| charset-normalizer | MIT. |
| PyYAML | MIT. |
| importlib_metadata and zipp | Original distribution license texts are collected when cx_Freeze includes the corresponding bundled copies. |
| packaging | Apache-2.0 or BSD-2-Clause; all three installed license files are collected if this package enters the frozen backend. |
| setuptools | Original MIT license and its bundled component notices are collected if setuptools enters the frozen backend. |
| .NET / Windows desktop runtime | The selected .NET SDK's complete `LICENSE.txt` and `ThirdPartyNotices.txt` are copied into `licenses/dotnet/`. |

The collector selects indirect Python packages from the actual frozen
`*.dist-info/METADATA` records, including distribution metadata supplied by
setuptools' bundled packages. It verifies that collected package versions match
the frozen metadata, copies full license trees without rewriting their content,
and fails if a selected component's original license text cannot be found.
The manifest identifies what was actually collected in a specific build.

The portable distribution does not include MEmu, Android platform-tools, the
Clash Royale application, or account data. Users configure paths to their own
existing MEmu and ADB installation. Game imagery and detector/reference fixtures
remain attributed to their respective owners; this repository is an unofficial
project and does not claim rights in those third-party assets.
