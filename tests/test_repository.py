import io
import hashlib
import datetime
from email.utils import parsedate_to_datetime
import json
import tarfile
from unittest.mock import patch
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('repository', Path(__file__).resolve().parents[1] / 'scripts/repository.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.incoming = self.root / 'incoming'
        self.incoming.mkdir()

    def package(self, release, extra=None, script=False):
        tree = self.root / ('tree-' + release)
        tree.mkdir()
        (tree / 'DEBIAN').mkdir()
        (tree / 'DEBIAN/control').write_text(
            f'Package: opscope\nVersion: {release}\nArchitecture: amd64\n'
            'Maintainer: Test <test@example.invalid>\n'
            'Depends: libc6 (>= 2.35), libgcc-s1\nDescription: Test fixture\n')
        launcher = tree / 'usr/bin/opscope'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/sh\necho fixture\n')
        launcher.chmod(0o755)
        private = tree / 'usr/libexec/opscope'
        private.mkdir(parents=True)
        for binary in r.registry()['opscope']['binaries']:
            file = private / binary
            file.write_text('#!/bin/sh\necho fixture\n')
            file.chmod(0o755)
        docs = tree / 'usr/share/doc/opscope'
        docs.mkdir(parents=True)
        (docs / 'binaries').write_text('\n'.join(r.registry()['opscope']['binaries']) + '\n')
        if extra:
            file = tree / extra
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('unexpected')
        if script:
            file = tree / 'DEBIAN/postinst'
            file.write_text('#!/bin/sh\nexit 0\n')
            file.chmod(0o755)
        file = self.incoming / f'opscope_{release}_amd64.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(file)], check=True, stdout=subprocess.DEVNULL)
        self.hash(file)
        return file

    def single(self, release, extra=None, launcher=True, mode=0o755):
        # Mirrors gh-pr-manager's debian/package.js: one /usr/bin executable
        # plus documentation, with no private directory or binary manifest.
        tree = self.root / ('single-' + release)
        (tree / 'DEBIAN').mkdir(parents=True)
        (tree / 'DEBIAN/control').write_text(
            f'Package: gh-pr-manager\nVersion: {release}\nArchitecture: amd64\n'
            'Maintainer: Test <test@example.invalid>\n'
            'Depends: libc6 (>= 2.35), libgcc-s1\nDescription: Test fixture\n')
        (tree / 'usr/bin').mkdir(parents=True)
        if launcher:
            file = tree / 'usr/bin/gh-pr-manager'
            file.write_text('#!/bin/sh\necho fixture\n')
            file.chmod(mode)
        docs = tree / 'usr/share/doc/gh-pr-manager'
        docs.mkdir(parents=True)
        for name in ['README.md', 'CHANGELOG.md', 'copyright']:
            (docs / name).write_text('fixture\n')
        if extra:
            file = tree / extra
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('unexpected')
        file = self.incoming / f'gh-pr-manager_{release}_amd64.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(file)], check=True, stdout=subprocess.DEVNULL)
        self.hash(file)
        return file

    def hash(self, file):
        Path(str(file) + '.sha256').write_text(f'{r.checksum(file)}  {file.name}\n')

    def test_repository_owned_binary_lists_agree(self):
        expected = (r.ROOT / 'tests/opscope-binaries').read_text().splitlines()
        self.assertEqual(expected, r.registry()['opscope']['binaries'])
        self.assertEqual(len(expected), 17)

    def test_repeated_fetch_uses_clean_temporary_downloads(self):
        filename = 'opscope_1.2.3_amd64.deb'
        release = {'draft': False, 'prerelease': False, 'tag_name': 'v1.2.3',
                   'assets': [{'name': filename}, {'name': filename + '.sha256'}]}
        seen = []
        def download(command):
            folder = Path(command[-1])
            self.assertEqual(list(folder.iterdir()), [])
            seen.append(folder)
            (folder / filename).write_bytes(b'fresh fixture')
        (self.incoming / 'opscope').mkdir()
        with patch.object(r, 'run', side_effect=lambda *args: 'a' * 40 if '/commits/' in args[2] else json.dumps(release)), \
                patch.object(r.subprocess, 'check_call', side_effect=download), \
                patch.object(r, 'import_package') as importer:
            r.fetch_release(self.site, self.incoming, 'opscope', 'v1.2.3', 'a' * 40)
            r.fetch_release(self.site, self.incoming, 'opscope', 'v1.2.3', 'a' * 40)
            self.assertEqual(importer.call_count, 2)
        self.assertEqual(len(set(seen)), 2)
        self.assertTrue(all(not folder.exists() for folder in seen))

    def test_intake_rejects_unapproved_relationships(self):
        config = r.registry()['opscope']
        fields = {'Package': 'opscope', 'Version': '1.2.3', 'Architecture': 'amd64',
                  'Depends': config['depends']}
        for relationship in ['Pre-Depends', 'Recommends', 'Suggests', 'Enhances',
                             'Conflicts', 'Breaks', 'Replaces', 'Provides',
                             'Built-Using', 'Static-Built-Using']:
            with self.subTest(relationship=relationship), patch.object(
                    r, 'run', side_effect=lambda *args: fields.get(args[-1], 'surprise' if args[-1] == relationship else '')):
                with self.assertRaisesRegex(ValueError, 'Unapproved relationship'):
                    r.inspect(Path('fixture.deb'), 'opscope', '1.2.3', config)

    def test_intake_checks_ownership_modes_and_independent_inventory(self):
        config = r.registry()['opscope']
        fields = {'Package': 'opscope', 'Version': '1.2.3', 'Architecture': 'amd64',
                  'Depends': config['depends']}
        def archive(mutate=None, omitted=None):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w') as tar:
                names = ['./usr', './usr/bin', './usr/libexec', './usr/libexec/opscope']
                for name in names:
                    member = tarfile.TarInfo(name); member.type = tarfile.DIRTYPE; member.mode = 0o755
                    if mutate: mutate(member)
                    tar.addfile(member)
                binaries = [b for b in config['binaries'] if b != omitted]
                for name in ['usr/bin/opscope'] + ['usr/libexec/opscope/' + b for b in binaries] + ['usr/share/doc/opscope/binaries']:
                    content = ('\n'.join(binaries) + '\n').encode() if name.endswith('/binaries') else b'executable'
                    member = tarfile.TarInfo('./' + name); member.mode = 0o755; member.size = len(content)
                    if mutate: mutate(member)
                    tar.addfile(member, io.BytesIO(content))
            return output.getvalue()
        control = io.BytesIO()
        with tarfile.open(fileobj=control, mode='w') as tar:
            tar.addfile(tarfile.TarInfo('./control'), io.BytesIO(b''))
        def check(data):
            with patch.object(r, 'run', side_effect=lambda *args: fields.get(args[-1], '')), \
                    patch.object(r.subprocess, 'check_output', side_effect=lambda args: control.getvalue() if '--ctrl-tarfile' in args else data):
                r.inspect(Path('fixture.deb'), 'opscope', '1.2.3', config)
        check(archive())
        for target in ['./usr/bin/opscope', './usr/libexec/opscope']:
            for attribute, value in [('uid', 1000), ('gid', 1000), ('mode', 0o777), ('mode', 0o775), ('mode', 0o4755)]:
                with self.subTest(target=target, attribute=attribute, value=value):
                    def mutate(member):
                        if member.name == target: setattr(member, attribute, value)
                    with self.assertRaisesRegex(ValueError, 'ownership or mode'):
                        check(archive(mutate))
        # Removing both a widget and its self-reported inventory entry must fail.
        with self.assertRaisesRegex(ValueError, 'approved binary inventory'):
            check(archive(omitted='link'))

    def test_single_binary_packages_cannot_declare_a_binary_inventory(self):
        config = dict(r.registry()['gh-pr-manager'], binaries=['gh-pr-manager'])
        fields = {'Package': 'gh-pr-manager', 'Version': '0.1.0', 'Architecture': 'amd64',
                  'Depends': config['depends']}
        control = io.BytesIO()
        with tarfile.open(fileobj=control, mode='w') as tar:
            tar.addfile(tarfile.TarInfo('./control'), io.BytesIO(b''))
        with patch.object(r, 'run', side_effect=lambda *args: fields.get(args[-1], '')), \
                patch.object(r.subprocess, 'check_output', return_value=control.getvalue()):
            with self.assertRaisesRegex(ValueError, 'approved binary inventory'):
                r.inspect(Path('fixture.deb'), 'gh-pr-manager', '0.1.0', config)

    def test_fetch_uses_each_packages_own_source_and_asset_names(self):
        filename = 'gh-pr-manager_0.1.0_amd64.deb'
        release = {'draft': False, 'prerelease': False, 'tag_name': 'v0.1.0',
                   'assets': [{'name': filename}, {'name': filename + '.sha256'},
                              {'name': 'gh-pr-manager-x86_64-unknown-linux-gnu.tar.gz'}]}
        api, downloads = [], []
        def run(*args):
            api.append(args)
            return 'c' * 40 if '/commits/' in args[2] else json.dumps(release)
        with patch.object(r, 'run', side_effect=run), \
                patch.object(r.subprocess, 'check_call', side_effect=downloads.append), \
                patch.object(r, 'import_package') as importer:
            r.fetch_release(self.site, self.incoming, 'gh-pr-manager', 'v0.1.0', 'c' * 40)
        self.assertEqual([a[2] for a in api], ['repos/stealth-factory/gh-pr-manager/releases/tags/v0.1.0',
                                                'repos/stealth-factory/gh-pr-manager/commits/v0.1.0'])
        command = downloads[0]
        self.assertEqual(command[command.index('--repo') + 1], 'stealth-factory/gh-pr-manager')
        self.assertEqual([command[i + 1] for i, part in enumerate(command) if part == '--pattern'],
                         [filename, filename + '.sha256'])
        self.assertEqual(importer.call_args.args[2:], ('gh-pr-manager', '0.1.0'))

    def test_tamper_probe_requires_good_baseline_and_signature_error(self):
        tools = self.root / 'tools'; tools.mkdir()
        apt = tools / 'apt-get'
        apt.write_text("""#!/bin/bash
set -eu
count_file="$TEST_APT_COUNT"
if [ ! -f "$count_file" ]; then
  touch "$count_file"
  [ "$TEST_APT_SCENARIO" != baseline-failure ] || exit 42
  exit 0
fi
case "$TEST_APT_SCENARIO" in
  signature) echo 'BADSIG fixture' >&2; exit 100;;
  unrelated) echo 'Temporary failure resolving mirror' >&2; exit 100;;
  accepted) exit 0;;
esac
""")
        apt.chmod(0o755)
        dist = self.site / 'dists/stable'; dist.mkdir(parents=True)
        (dist / 'InRelease').write_text('Origin: Stealth Factory\n')
        for scenario, expected in [('baseline-failure', False), ('unrelated', False),
                                   ('accepted', False), ('signature', True)]:
            with self.subTest(scenario=scenario):
                count = self.root / ('count-' + scenario)
                result = subprocess.run(['bash', str(r.ROOT / 'tests/authentication.sh'),
                                         str(self.site), '/non-key-test-fixture'],
                                        env={**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                                             'TEST_APT_COUNT': str(count), 'TEST_APT_SCENARIO': scenario},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, expected, result.stderr)
        self.assertEqual((dist / 'InRelease').read_text(), 'Origin: Stealth Factory\n')

    def test_exact_release_fetch_refuses_mismatched_commit_or_tag(self):
        release = {'draft': False, 'prerelease': False, 'tag_name': 'v1.2.3', 'assets': []}
        with patch.object(r, 'run', side_effect=lambda *args: 'b' * 40 if '/commits/' in args[2] else json.dumps(release)):
            with self.assertRaisesRegex(ValueError, 'requested commit'):
                r.fetch_release(self.site, self.incoming, 'opscope', 'v1.2.3', 'a' * 40)
            with self.assertRaisesRegex(ValueError, 'requested tag'):
                r.fetch_release(self.site, self.incoming, 'opscope', 'v1.2.4', 'a' * 40)

    def test_versions_fail_closed(self):
        self.assertLess(r.version('1.9.0'), r.version('1.10.0'))
        for value in ['v1.2.3', 'dev', '../1.2.3', '1.2.3\n', '1.02.3', '1.2.3-rc.1']:
            with self.assertRaises(ValueError):
                r.version(value)

    def test_checksum_requires_exact_filename_and_hash(self):
        file = self.incoming / 'test.deb'
        file.write_bytes(b'package')
        self.hash(file)
        r.checked_checksum(file)
        Path(str(file) + '.sha256').write_text(r.checksum(file) + '  ../test.deb\n')
        with self.assertRaises(ValueError):
            r.checked_checksum(file)

    def test_signing_requires_explicit_approved_configuration(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'FINGERPRINT'):
                r.sign(self.site)
        with patch.dict(os.environ, {'APT_SIGNING_FINGERPRINT': 'A' * 40}, clear=True):
            with self.assertRaisesRegex(ValueError, 'KEY'):
                r.sign(self.site)

    def test_signing_removes_temporary_keyring_even_on_failure(self):
        from unittest.mock import patch
        fingerprint = 'A' * 40
        calls = []
        homes = []
        def fake_output(command, **kwargs):
            calls.append(command)
            env = kwargs['env']
            self.assertNotIn('APT_SIGNING_KEY', env)
            homes.append(Path(env['GNUPGHOME']))
            self.assertTrue(homes[-1].is_dir())
            self.assertFalse(homes[-1].is_relative_to(self.site))
            if '--list-secret-keys' in command:
                return ('sec:::::::::\nfpr:::::::::' + ('B' * 40) + ':\n').encode()
            return b''
        with patch.dict(os.environ, {'APT_SIGNING_FINGERPRINT': fingerprint,
                                     'APT_SIGNING_KEY': 'non-key test input'}, clear=True), \
                patch.object(r.subprocess, 'check_output', side_effect=fake_output), \
                patch.object(r.subprocess, 'run'):
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                r.sign(self.site)
        self.assertTrue(homes)
        self.assertTrue(all(not home.exists() for home in homes))
        self.assertFalse(any('--clearsign' in command for command in calls))
        self.assertEqual(list(self.site.iterdir()), [])

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux dpkg required')
    def test_import_retry_changed_bytes_and_downgrade(self):
        file = self.package('1.2.3')
        self.assertTrue(r.import_package(self.site, self.incoming, 'opscope', '1.2.3'))
        self.assertFalse(r.import_package(self.site, self.incoming, 'opscope', '1.2.3'))
        tree = self.root / 'tree-1.2.3'
        (tree / 'usr/bin/opscope').write_text('#!/bin/sh\necho changed\n')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(file)], check=True, stdout=subprocess.DEVNULL)
        self.hash(file)
        with self.assertRaisesRegex(ValueError, 'Immutable'):
            r.import_package(self.site, self.incoming, 'opscope', '1.2.3')
        self.package('1.2.2')
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            r.import_package(self.site, self.incoming, 'opscope', '1.2.2')

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux dpkg required')
    def test_rejects_hooks_public_widgets_and_corrupt_history(self):
        self.package('1.2.3', script=True)
        with self.assertRaisesRegex(ValueError, 'control member'):
            r.import_package(self.site, self.incoming, 'opscope', '1.2.3')
        self.package('1.2.4', extra='usr/bin/link')
        with self.assertRaisesRegex(ValueError, 'data member'):
            r.import_package(self.site, self.incoming, 'opscope', '1.2.4')
        self.package('1.2.5')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.5')
        stored = next((self.site / 'pool').rglob('*.deb'))
        stored.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            r.inventory(self.site)

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Linux dpkg required')
    def test_single_binary_package_layout(self):
        self.single('0.1.0')
        self.assertTrue(r.import_package(self.site, self.incoming, 'gh-pr-manager', '0.1.0'))
        for release, kwargs, error in [
                ('0.1.1', {'extra': 'usr/libexec/gh-pr-manager/helper'}, 'data member'),
                ('0.1.2', {'extra': 'usr/bin/link'}, 'data member'),
                ('0.1.3', {'extra': 'etc/gh-pr-manager.toml'}, 'data member'),
                ('0.1.4', {'launcher': False}, 'usr/bin/gh-pr-manager'),
                ('0.1.5', {'mode': 0o644}, 'Non-executable')]:
            with self.subTest(release=release):
                self.single(release, **kwargs)
                with self.assertRaisesRegex(ValueError, error):
                    r.import_package(self.site, self.incoming, 'gh-pr-manager', release)
        # Packages are independent: gh-pr-manager history does not block opscope.
        self.package('1.2.3')
        self.assertTrue(r.import_package(self.site, self.incoming, 'opscope', '1.2.3'))
        self.assertEqual(r.inventory(self.site), {'gh-pr-manager': ['0.1.0'], 'opscope': ['1.2.3']})
        self.single('0.0.9')
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            r.import_package(self.site, self.incoming, 'gh-pr-manager', '0.0.9')

    @unittest.skipUnless(shutil.which('apt-ftparchive'), 'Linux apt-utils required')
    def test_indexes_cover_immutable_pool_and_retain_by_hash(self):
        self.package('1.2.3')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.3')
        r.indexes(self.site)
        binary = self.site / 'dists/stable/main/binary-amd64'
        old_hash = r.checksum(binary / 'Packages')
        old_sha512 = hashlib.sha512((binary / 'Packages').read_bytes()).hexdigest()
        self.package('1.2.4')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.4')
        r.indexes(self.site)
        content = (binary / 'Packages').read_text()
        self.assertIn('Version: 1.2.3', content)
        self.assertIn('Version: 1.2.4', content)
        self.assertIn('Filename: pool/main/opscope/opscope_1.2.4_amd64.deb', content)
        self.assertTrue((binary / 'by-hash/SHA256' / old_hash).exists())
        self.assertTrue((binary / 'by-hash/SHA512' / old_sha512).exists())
        for algorithm in ['sha256', 'sha512']:
            for name in ['Packages', 'Packages.gz']:
                contents = (binary / name).read_bytes()
                digest = hashlib.new(algorithm, contents).hexdigest()
                self.assertEqual((binary / 'by-hash' / algorithm.upper() / digest).read_bytes(), contents)
        release = (self.site / 'dists/stable/Release').read_text()
        self.assertIn('Acquire-By-Hash: yes', release)
        expiry = next(line.removeprefix('Valid-Until: ') for line in release.splitlines() if line.startswith('Valid-Until: '))
        remaining = parsedate_to_datetime(expiry) - datetime.datetime.now(datetime.timezone.utc)
        self.assertGreater(remaining.total_seconds(), 90 * 86400 - 60)
        self.assertLessEqual(remaining.total_seconds(), 90 * 86400)
        self.assertIn(r.checksum(binary / 'Packages'), release)
        self.assertFalse((self.site / 'dists/stable/InRelease').exists())

    @unittest.skipUnless(shutil.which('apt-ftparchive'), 'Linux apt-utils required')
    def test_indexes_list_every_package(self):
        self.package('1.2.3')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.3')
        self.single('0.1.0')
        r.import_package(self.site, self.incoming, 'gh-pr-manager', '0.1.0')
        r.indexes(self.site)
        content = (self.site / 'dists/stable/main/binary-amd64/Packages').read_text()
        self.assertIn('Filename: pool/main/opscope/opscope_1.2.3_amd64.deb', content)
        self.assertIn('Filename: pool/main/gh-pr-manager/gh-pr-manager_0.1.0_amd64.deb', content)


if __name__ == '__main__':
    unittest.main()
