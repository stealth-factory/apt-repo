#!/usr/bin/env python3
"""Import allowlisted release packages and build an immutable APT snapshot."""
import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def version(value):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError(f'Expected stable X.Y.Z version: {value!r}')
    return tuple(map(int, value.split('.')))


def checksum(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def checked_checksum(file):
    recorded = Path(str(file) + '.sha256').read_text()
    expected = f'{checksum(file)}  {file.name}\n'
    if recorded != expected:
        raise ValueError(f'Checksum mismatch: {file.name}')
    return expected


def registry():
    return json.loads((ROOT / 'packages.json').read_text())


def inspect(file, name, release, config):
    for field, expected in [('Package', name), ('Version', release),
                            ('Architecture', config['architecture']),
                            ('Depends', config['depends'])]:
        if run('dpkg-deb', '-f', str(file), field) != expected:
            raise ValueError(f'Unexpected {field} in {file.name}')
    # These applications need no package hooks or global config modifications.
    # Reject an upstream asset that unexpectedly adds privileged install code.
    control = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(file)])
    with tarfile.open(fileobj=io.BytesIO(control)) as archive:
        for member in archive:
            member_name = member.name.removeprefix('./')
            if member.isdir() and member_name in ('', '.'):
                continue
            if not member.isfile() or member_name not in ('control', 'md5sums'):
                raise ValueError(f'Unexpected control member: {member.name}')
    data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(file)])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive:
            member_name = member.name.removeprefix('./').rstrip('/')
            if member_name.startswith('/') or '..' in member_name.split('/'):
                raise ValueError('Unsafe package path')
            roots = [config['private_directory'], f'usr/share/doc/{name}']
            allowed = member_name == f'usr/bin/{name}' or any(
                member_name.startswith(root + '/') for root in roots)
            directory = member.isdir() and (member_name in ('', '.', 'usr', 'usr/bin', 'usr/libexec', 'usr/share', 'usr/share/doc') or
                                           any(member_name == root or member_name.startswith(root + '/') for root in roots))
            if not directory and not (member.isfile() and allowed and not member.mode & 0o6000):
                raise ValueError(f'Unexpected data member: {member.name}')


def inventory(site):
    entries = {}
    for file in sorted((site / 'pool').glob('**/*.deb')):
        match = re.fullmatch(r'([a-z0-9-]+)_([0-9.]+)_([a-z0-9]+)\.deb', file.name)
        if not match:
            raise ValueError(f'Invalid package filename: {file}')
        name, release, arch = match.groups()
        config = registry().get(name)
        if not config or arch != config['architecture']:
            raise ValueError(f'Package not allowlisted: {file}')
        version(release)
        if file != site / 'pool/main' / name / file.name:
            raise ValueError(f'Unexpected pool location: {file}')
        checked_checksum(file)
        inspect(file, name, release, config)
        entries.setdefault(name, []).append(release)
    return entries


def import_package(site, incoming, name, release):
    version(release)
    config = registry()[name]
    previous = inventory(site)
    if any(version(old) > version(release) for old in previous.get(name, [])):
        raise ValueError(f'Refusing downgrade of {name} to {release}')
    file = incoming / f'{name}_{release}_{config["architecture"]}.deb'
    checked_checksum(file)
    inspect(file, name, release, config)
    target = site / 'pool/main' / name / file.name
    if target.exists():
        if checksum(target) != checksum(file):
            raise ValueError(f'Immutable package changed: {file.name}')
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(file, target)
    shutil.copyfile(str(file) + '.sha256', str(target) + '.sha256')
    return True


def fetch_latest(site, incoming):
    for name, config in registry().items():
        repo = config['repository']
        release = json.loads(run('gh', 'api', f'repos/{repo}/releases/latest'))
        if release['draft'] or release['prerelease']:
            raise ValueError('Latest release is not stable and published')
        tag = release['tag_name']
        if not tag.startswith('v'):
            raise ValueError('Expected v-prefixed release tag')
        value = tag[1:]
        version(value)
        filename = f'{name}_{value}_{config["architecture"]}.deb'
        assets = {asset['name'] for asset in release['assets']}
        if filename not in assets or filename + '.sha256' not in assets:
            # The first packaging release may not exist yet. An incomplete
            # newer release must never silently displace a published package.
            raise ValueError(f'{repo} {tag} has no complete Debian asset pair')
        folder = incoming / name
        folder.mkdir(parents=True)
        subprocess.check_call(['gh', 'release', 'download', tag, '--repo', repo,
                               '--pattern', filename, '--pattern', filename + '.sha256',
                               '--dir', str(folder)])
        import_package(site, folder, name, value)


def indexes(site):
    entries = inventory(site)
    if not entries:
        raise ValueError('Refusing an empty repository')
    dist = site / 'dists/stable'
    binary = dist / 'main/binary-amd64'
    binary.mkdir(parents=True, exist_ok=True)
    packages = subprocess.check_output(['apt-ftparchive', 'packages', 'pool'], cwd=site)
    (binary / 'Packages').write_bytes(packages)
    (binary / 'Packages.gz').write_bytes(gzip.compress(packages, mtime=0))
    # Keep old by-hash objects so cached metadata can still fetch its exact
    # index while a new snapshot propagates. Pool objects are immutable too.
    for file in (binary / 'Packages', binary / 'Packages.gz'):
        dest = binary / 'by-hash/SHA256' / checksum(file)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, dest)
    for name in ['Release', 'InRelease', 'Release.gpg']:
        (dist / name).unlink(missing_ok=True)
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=14)).strftime('%a, %d %b %Y %H:%M:%S UTC')
    options = {
        'Origin': 'Stealth Factory', 'Label': 'Stealth Factory',
        'Suite': 'stable', 'Codename': 'stable', 'Architectures': 'amd64',
        'Components': 'main', 'Description': 'Stealth Factory application packages',
        'Acquire-By-Hash': 'yes', 'Valid-Until': expires,
    }
    command = ['apt-ftparchive']
    for key, value in options.items():
        command += ['-o', f'APT::FTPArchive::Release::{key}={value}']
    # Exclude by-hash retention files from the Release checksum inventory.
    command += ['-o', 'APT::FTPArchive::Release::Patterns::=main/binary-amd64/Packages*',
                'release', 'dists/stable']
    (dist / 'Release').write_bytes(subprocess.check_output(command, cwd=site))
    (site / '.nojekyll').touch()


def sign(site):
    fingerprint = os.environ.get('APT_SIGNING_FINGERPRINT', '')
    if not re.fullmatch(r'[A-F0-9]{40}', fingerprint):
        raise ValueError('Set the approved primary APT_SIGNING_FINGERPRINT (40 uppercase hex digits)')
    key = os.environ.get('APT_SIGNING_KEY', '')
    if not key:
        raise ValueError('The approved APT_SIGNING_KEY is not configured')
    # No generation or persistent keyring. Private material only enters gpg
    # through stdin; the home is outside the site and is always removed.
    with tempfile.TemporaryDirectory(prefix='apt-sign-') as home:
        os.chmod(home, 0o700)
        env = {k: v for k, v in os.environ.items() if k != 'APT_SIGNING_KEY'}
        env['GNUPGHOME'] = home
        def gpg(*args, **kwargs):
            return subprocess.check_output(['gpg', '--batch', *args], env=env, **kwargs)
        try:
            gpg('--import', input=key.encode(), stderr=subprocess.DEVNULL)
            records = gpg('--with-colons', '--list-secret-keys').decode().splitlines()
            primary = []
            for i, line in enumerate(records):
                if line.startswith('sec:') and i + 1 < len(records):
                    primary.append(records[i + 1].split(':')[9])
            if primary != [fingerprint]:
                raise ValueError('Imported key does not match the approved primary fingerprint')
            public = gpg('--armor', '--export', fingerprint)
            (site / 'stealth-factory.asc').write_bytes(public)
            dist = site / 'dists/stable'
            gpg('--yes', '--local-user', fingerprint, '--digest-algo', 'SHA256',
                '--clearsign', '--output', str(dist / 'InRelease'), str(dist / 'Release'))
            gpg('--yes', '--local-user', fingerprint, '--digest-algo', 'SHA256',
                '--armor', '--detach-sign', '--output', str(dist / 'Release.gpg'), str(dist / 'Release'))
            # Verification uses only the exported public key, not the signing
            # keyring, proving the distributed key is sufficient.
            keyring = Path(home) / 'public.gpg'
            keyring.write_bytes(gpg('--export', fingerprint))
            subprocess.check_call(['gpgv', '--keyring', str(keyring), str(dist / 'InRelease')], env=env)
            subprocess.check_call(['gpgv', '--keyring', str(keyring), str(dist / 'Release.gpg'), str(dist / 'Release')], env=env)
        finally:
            subprocess.run(['gpgconf', '--kill', 'gpg-agent'], env=env, check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['fetch', 'index', 'sign', 'import'])
    parser.add_argument('--site', type=Path, default=Path('site'))
    parser.add_argument('--incoming', type=Path, default=Path('incoming'))
    parser.add_argument('--package', choices=list(registry()))
    parser.add_argument('--version')
    args = parser.parse_args()
    site = args.site.resolve()
    site.mkdir(parents=True, exist_ok=True)
    if args.command == 'fetch':
        fetch_latest(site, args.incoming.resolve())
    elif args.command == 'import':
        if not args.package or not args.version:
            parser.error('import requires --package and --version')
        import_package(site, args.incoming.resolve(), args.package, args.version)
    elif args.command == 'index':
        indexes(site)
    else:
        sign(site)


if __name__ == '__main__':
    main()
