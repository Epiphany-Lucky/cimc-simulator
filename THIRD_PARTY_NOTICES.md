# Third-party components and sources

- Unicorn Engine: CPU emulation framework, GPL-2.0. https://www.unicorn-engine.org/ and https://github.com/unicorn-engine/unicorn . The exact installed package version is pinned in engine/requirements.txt. Upstream license copies are in licenses/. Unmodified Unicorn 2.1.4 corresponding source is bundled in third-party-source/unicorn-2.1.4.tar.gz; this application source is included in source/, firmware/ and web/.
- Microsoft .NET runtime and WPF: MIT and third-party notices, https://github.com/dotnet/runtime and https://github.com/dotnet/wpf . Windows release contains the self-contained runtime and its license files.
- Microsoft Edge WebView2 SDK: Microsoft license terms supplied by NuGet package; Edge WebView2 Runtime is a separate installed Microsoft component. https://learn.microsoft.com/microsoft-edge/webview2/
- PyInstaller: GPL with bootloader distribution exception, https://pyinstaller.org/ . Used only for packaging.
- V1 schematic: Lingyu Meng / CIMC-IHD-Project; original copyright retained. Development-board reference images: source attribution is recorded in docs/reference/v2-research.md. Images identify the target hardware; they do not imply endorsement or certification.

CIMC Studio is an independent development tool, not an official competition judging application or an Apple product. No Apple logo, proprietary font file, or website artwork is bundled. Hardware documentation and images retain their original authorship.

Release use and redistribution must preserve applicable upstream terms. The repository and release are published at the project owner's request. Public availability does not remove upstream copyright or grant rights to third-party trademarks and hardware documents.

- Python 3.13: Python Software Foundation license, bundled as licenses/Python-LICENSE.txt.
- PyInstaller bootloader terms: licenses/PyInstaller-COPYING.txt.
- Inno Setup 6.7.4: Windows installer build tool and installer engine, https://jrsoftware.org/ . Official Simplified Chinese translation is pinned by the setup script; compiler and translation downloads are hash-verified. Inno Setup is not required to run the installed application.
- Linux desktop integration uses the system xdg-utils opener and an installed graphical browser. They are operating-system dependencies, not bundled browser engines.

- User-supplied CIMC V2 firmware includes GigaDevice peripheral-library and ARM CMSIS code. Corresponding license notices are retained in licenses/V2-GigaDevice-LICENSE.txt and licenses/V2-ARM-CMSIS-LICENSE.txt. Binary provenance and SHA-256 hashes are recorded in firmware/v2-manifest.json.
