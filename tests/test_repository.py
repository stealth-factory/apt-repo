import hashlib
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

    def hash(self, file):
        Path(str(file) + '.sha256').write_text(f'{r.checksum(file)}  {file.name}\n')

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

    @unittest.skipUnless(shutil.which('apt-ftparchive'), 'Linux apt-utils required')
    def test_indexes_cover_immutable_pool_and_retain_by_hash(self):
        self.package('1.2.3')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.3')
        r.indexes(self.site)
        binary = self.site / 'dists/stable/main/binary-amd64'
        old_hash = r.checksum(binary / 'Packages')
        self.package('1.2.4')
        r.import_package(self.site, self.incoming, 'opscope', '1.2.4')
        r.indexes(self.site)
        content = (binary / 'Packages').read_text()
        self.assertIn('Version: 1.2.3', content)
        self.assertIn('Version: 1.2.4', content)
        self.assertIn('Filename: pool/main/opscope/opscope_1.2.4_amd64.deb', content)
        self.assertTrue((binary / 'by-hash/SHA256' / old_hash).exists())
        release = (self.site / 'dists/stable/Release').read_text()
        self.assertIn('Acquire-By-Hash: yes', release)
        self.assertIn('Valid-Until:', release)
        self.assertIn(r.checksum(binary / 'Packages'), release)
        self.assertFalse((self.site / 'dists/stable/InRelease').exists())


if __name__ == '__main__':
    unittest.main()
