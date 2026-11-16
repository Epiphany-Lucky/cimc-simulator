"""Remove superseded installer assets and GHCR versions after verified publication.

Defaults to a dry run. Called by the Packages workflow only after both platforms
were pushed, pulled and checksum-verified. Source tags, history and reports remain.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from updates import ASSET_NAMES, UpdateChecker, _version

REPO = 'Epiphany-Lucky/cimc-simulator'
OWNER = REPO.split('/')[0]


def installer_names(version):
    return {pattern.format(version=version) for pattern in ASSET_NAMES.values()} | {
        f'CIMC-Studio-{version}-win-x64.zip'}


def release_deletions(releases, current_version):
    current_key, _ = _version(current_version)
    result = []
    for release in releases:
        if release.get('draft'):
            continue
        try:
            key, version = _version(release.get('tag_name'), tag=True)
        except ValueError:
            continue
        if key >= current_key:
            continue
        names = installer_names(version) | {'SHA256SUMS.txt', f'SHA256SUMS-{version}.txt'}
        for asset in release.get('assets', []):
            identifier = asset.get('id')
            if type(identifier) is int and identifier > 0 and asset.get('name') in names:
                result.append({'tag': release['tag_name'], 'name': asset['name'], 'id': identifier})
    return result


def package_deletions(versions, current_version):
    current_key, _ = _version(current_version)
    result = []
    for version in versions:
        tags = version.get('metadata', {}).get('container', {}).get('tags', [])
        identifier = version.get('id')
        if not tags or type(identifier) is not int or identifier <= 0:
            continue
        try:
            # Unknown aliases and untagged images may belong to other workflows.
            keys = [_version(tag, tag=True)[0] for tag in tags]
        except ValueError:
            continue
        if all(key < current_key for key in keys):
            result.append({'id': identifier, 'tags': tags})
    return result


def api(path, method='GET', paginated=False):
    command = ['gh', 'api', '--method', method, path]
    if paginated:
        command += ['--paginate', '--slurp']
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE, encoding='utf-8')
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-version', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--report', type=Path, default=Path('cleanup-report.json'))
    args = parser.parse_args()
    _version(args.current_version)
    releases = [item for page in api(f'repos/{REPO}/releases?per_page=100', paginated=True) for item in page]
    current = next((r for r in releases if r.get('tag_name') == f'v{args.current_version}' and not r.get('draft')), None)
    if current is None:
        raise SystemExit('Current published release is missing; nothing deleted')
    assets = {asset['name']: asset for asset in current['assets']}
    for name in installer_names(args.current_version):
        asset = assets.get(name)
        if (not asset or asset.get('state') != 'uploaded' or asset.get('size', 0) <= 0
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest', ''))):
            raise SystemExit('Current installer/digest is missing; nothing deleted: ' + name)
    public = UpdateChecker('0.0.0').check()
    if public['status'] != 'ok' or public['latestVersion'] != args.current_version or not all(public['assets'].values()):
        raise SystemExit('Public update source does not identify the current version; nothing deleted')

    packages = {}
    # Inventory all permissions and current tags before performing any deletions.
    for platform in ('windows', 'linux'):
        name = 'cimc-studio-' + platform
        versions = [item for page in api(f'users/{OWNER}/packages/container/{name}/versions?per_page=100', paginated=True) for item in page]
        if not any(args.current_version in v.get('metadata', {}).get('container', {}).get('tags', []) for v in versions):
            raise SystemExit('Current GHCR version is missing; nothing deleted: ' + name)
        packages[name] = package_deletions(versions, args.current_version)
    report = {'currentVersion': args.current_version, 'executed': args.execute,
              'releaseAssets': release_deletions(releases, args.current_version), 'packageVersions': packages,
              'deleted': [], 'verified': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        print(json.dumps({key: report[key] for key in ('currentVersion', 'executed', 'releaseAssets', 'packageVersions')}, indent=2))
        if args.execute:
            for asset in report['releaseAssets']:
                api(f"repos/{REPO}/releases/assets/{asset['id']}", method='DELETE')
                report['deleted'].append({'kind': 'releaseAsset', **asset})
            for name, versions in packages.items():
                for version in versions:
                    api(f"users/{OWNER}/packages/container/{name}/versions/{version['id']}", method='DELETE')
                    report['deleted'].append({'kind': 'packageVersion', 'package': name, **version})
            remaining = [item for page in api(f'repos/{REPO}/releases?per_page=100', paginated=True) for item in page]
            assert not release_deletions(remaining, args.current_version), 'Old installer assets remain'
            preserved = next(r for r in remaining if r.get('id') == current.get('id')
                             and r.get('tag_name') == current['tag_name'])
            preserved_assets = {a['name']: a for a in preserved['assets']}
            for name in installer_names(args.current_version):
                assert preserved_assets[name]['id'] == assets[name]['id'], 'Current installer changed: ' + name
                assert preserved_assets[name]['digest'] == assets[name]['digest'], 'Current installer digest changed: ' + name
            for name in packages:
                versions = [item for page in api(f'users/{OWNER}/packages/container/{name}/versions?per_page=100', paginated=True) for item in page]
                assert not package_deletions(versions, args.current_version), 'Old package versions remain: ' + name
                assert any(args.current_version in v.get('metadata', {}).get('container', {}).get('tags', []) for v in versions)
            report['verified'] = True
    finally:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Cleanup completed and verified' if report['verified'] else 'Dry run; nothing deleted')


if __name__ == '__main__':
    main()
