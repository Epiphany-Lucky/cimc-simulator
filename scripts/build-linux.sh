#!/usr/bin/env bash
# Build on Ubuntu 22.04 x86_64 for Ubuntu 22.04+ / Debian 12+.
# PYTHON=/path/to/build-venv/bin/python bash scripts/build-linux.sh [version]
set -euo pipefail

version=${1:-0.4.0}
if [[ $# -gt 1 || ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'Usage: build-linux.sh [MAJOR.MINOR.PATCH]' >&2
    exit 2
fi
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    echo 'Build this package on Linux x86_64 (Ubuntu 22.04 is the release baseline).' >&2
    exit 2
fi

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$project_root"
python=${PYTHON:-python3}
for command_name in dpkg-deb tar install sha256sum; do
    command -v "$command_name" >/dev/null || { echo "Missing build tool: $command_name" >&2; exit 2; }
done
"$python" -c 'import PyInstaller, unicorn; assert unicorn.__version__ == "2.1.4", "Use engine/requirements.txt"'
"$python" -m unittest discover -s tests -v

mkdir -p -- artifacts
artifact_root=$(cd -- artifacts && pwd -P)
stage=$(mktemp -d "$artifact_root/.cimc-linux-stage.XXXXXXXX")
cleanup() {
    # Only remove the freshly allocated, resolved staging directory owned by this run.
    case "$stage" in "$artifact_root"/.cimc-linux-stage.*)
        [[ -d "$stage" && ! -L "$stage" ]] && rm -rf -- "$stage" ;;
    esac
}
trap cleanup EXIT

"$python" -m PyInstaller --clean --noconfirm --onedir --name CIMC-Engine \
    --collect-all unicorn --distpath "$stage/dist" --workpath "$stage/work" \
    --specpath "$stage" engine/server.py

bundle_name="CIMC-Studio-$version-linux-x64"
bundle="$stage/$bundle_name"
mkdir -- "$bundle"
cp -a -- "$stage/dist/CIMC-Engine/." "$bundle/"
for folder in web docs licenses; do
    cp -a -- "$folder" "$bundle/"
done
mkdir -- "$bundle/firmware"
find firmware -maxdepth 1 -type f ! -name '*.o' -exec cp -a -t "$bundle/firmware" -- {} +
cp -a -- README.md THIRD_PARTY_NOTICES.md CHANGELOG.md "$bundle/"
install -m 0755 packaging/linux/portable-launcher.sh "$bundle/cimc-studio"

# Corresponding project and Unicorn sources accompany both binary distributions.
source_root="$bundle/source"
mkdir -p -- "$source_root"
for folder in engine tests scripts desktop; do
    mkdir -- "$source_root/$folder"
    find "$folder" -maxdepth 1 -type f -exec cp -a -t "$source_root/$folder" -- {} +
done
for folder in web assets docs licenses packaging .github .ai-governance; do
    cp -a -- "$folder" "$source_root/"
done
cp -a -- "$bundle/firmware" "$source_root/"
cp -a -- README.md THIRD_PARTY_NOTICES.md CHANGELOG.md AGENTS.md requirements-dev.txt .gitignore "$source_root/"

unicorn_source="$artifact_root/third-party-source/unicorn-2.1.4.tar.gz"
if [[ ! -f "$unicorn_source" ]]; then
    command -v curl >/dev/null || { echo 'curl is required to retrieve the pinned Unicorn source.' >&2; exit 2; }
    mkdir -p -- "$(dirname -- "$unicorn_source")"
    curl --fail --location --retry 3 --output "$stage/unicorn-2.1.4.tar.gz" \
        https://github.com/unicorn-engine/unicorn/archive/refs/tags/2.1.4.tar.gz
    printf '%s  %s\n' ea8863f095a0136388694e5a6063afd9bb7650e30243dd6251af59c5ce5601f4 \
        "$stage/unicorn-2.1.4.tar.gz" | sha256sum --check --status
    mv -- "$stage/unicorn-2.1.4.tar.gz" "$unicorn_source"
fi
printf '%s  %s\n' ea8863f095a0136388694e5a6063afd9bb7650e30243dd6251af59c5ce5601f4 \
    "$unicorn_source" | sha256sum --check --status
mkdir -- "$bundle/third-party-source"
cp -a -- "$unicorn_source" "$bundle/third-party-source/"

deb_root="$stage/deb"
mkdir -p -- "$deb_root/DEBIAN" "$deb_root/opt/cimc-studio" "$deb_root/usr/bin" \
    "$deb_root/usr/share/applications" "$deb_root/usr/share/icons/hicolor/scalable/apps" \
    "$deb_root/usr/share/doc/cimc-studio"
cp -a -- "$bundle/." "$deb_root/opt/cimc-studio/"
install -m 0755 packaging/linux/system-launcher.sh "$deb_root/usr/bin/cimc-studio"
install -m 0644 packaging/linux/cimc-studio.desktop "$deb_root/usr/share/applications/cimc-studio.desktop"
install -m 0644 packaging/linux/cimc-studio.svg "$deb_root/usr/share/icons/hicolor/scalable/apps/cimc-studio.svg"
install -m 0644 THIRD_PARTY_NOTICES.md "$deb_root/usr/share/doc/cimc-studio/copyright"
installed_size=$(du -sk "$deb_root/opt" "$deb_root/usr" | awk '{sum += $1} END {print sum}')
sed -e "s/@VERSION@/$version/g" -e "s/@INSTALLED_SIZE@/$installed_size/g" \
    packaging/linux/control.in > "$deb_root/DEBIAN/control"
chmod 0755 "$deb_root/DEBIAN"
chmod 0644 "$deb_root/DEBIAN/control"

deb_name="cimc-studio_${version}_amd64.deb"
dpkg-deb --root-owner-group --build "$deb_root" "$stage/$deb_name"
# tar preserves PyInstaller's shared-library symlinks. Do not replace it with ZIP.
tar -czf "$stage/$bundle_name.tar.gz" -C "$stage" "$bundle_name"

release_root="$artifact_root/$bundle_name"
if [[ -e "$release_root" || -L "$release_root" ]]; then
    if [[ -L "$release_root" || $(realpath -- "$release_root") != "$release_root" || ! -d "$release_root" ]]; then
        echo "Refusing to replace unexpected release path: $release_root" >&2
        exit 2
    fi
    # The version has been restricted to digits/dots; this is the named build output.
    rm -rf -- "$release_root"
fi
mv -- "$bundle" "$release_root"
mv -- "$stage/$deb_name" "$artifact_root/$deb_name"
mv -- "$stage/$bundle_name.tar.gz" "$artifact_root/$bundle_name.tar.gz"
printf 'DEB: %s\nPortable: %s\n' "$artifact_root/$deb_name" "$artifact_root/$bundle_name.tar.gz"
