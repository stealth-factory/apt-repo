from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bootstrap_signing as setup


class BootstrapTests(unittest.TestCase):
    environment = {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': setup.REPOSITORY,
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'RUNNER_ENVIRONMENT': 'github-hosted',
        'APT_BOOTSTRAP_CONFIRMATION': 'GENERATE_INITIAL_APT_KEY',
        'APT_BOOTSTRAP_TOKEN': 'test-token',
    }
    fingerprint = 'A' * 40

    def fake(self, calls, existing=b'', existing_variables=b'', fail_write=None):
        def execute(args, *, env, data=None):
            calls.append((args, env, data))
            if args[0] == 'gh':
                if args[-1] == '.secrets[].name':
                    return existing
                if args[-1] == '.variables[].name':
                    return existing_variables
                write = args[3] if args[:3] == ['gh', 'secret', 'set'] else (setup.FINGERPRINT if 'POST' in args else None)
                if fail_write is not None and write == fail_write:
                    raise RuntimeError('simulated write failure')
                return b''
            if '--quick-generate-key' in args:
                directory = Path(env['GNUPGHOME']) / 'openpgp-revocs.d'
                directory.mkdir()
                (directory / f'{self.fingerprint}.rev').write_bytes(b'fake-revocation-material')
            if '--list-secret-keys' in args:
                return f'fpr:::::::::{self.fingerprint}:\n'.encode()
            if '--export-secret-keys' in args:
                return b'fake-private-material'
            return b''
        return execute

    def test_only_explicit_hosted_main_run_can_generate(self):
        for field, wrong in [('GITHUB_ACTIONS', ''), ('GITHUB_REF', 'refs/heads/test'),
                             ('GITHUB_REPOSITORY', 'other/repo'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                             ('GITHUB_EVENT_NAME', 'schedule'), ('APT_BOOTSTRAP_CONFIRMATION', ''),
                             ('APT_BOOTSTRAP_TOKEN', '')]:
            with self.subTest(field=field), patch.dict(os.environ, {**self.environment, field: wrong}, clear=True), patch.object(setup, 'execute') as run:
                with self.assertRaises(ValueError):
                    setup.bootstrap()
                run.assert_not_called()

    def test_existing_or_partial_key_configuration_blocks_generation(self):
        for name in sorted(setup.SECRETS) + [setup.FINGERPRINT]:
            calls = []
            existing = {'existing_variables' if name == setup.FINGERPRINT else 'existing': name.encode()}
            with self.subTest(name=name), patch.dict(os.environ, self.environment, clear=True), patch.object(setup, 'execute', side_effect=self.fake(calls, **existing)), patch.object(setup.tempfile, 'TemporaryDirectory') as directory:
                with self.assertRaisesRegex(ValueError, 'refusing replacement'):
                    setup.bootstrap()
                directory.assert_not_called()
                self.assertEqual([args[:3] for args, _, _ in calls], [['gh', 'api', '--paginate']] * 2)

    def test_stores_secrets_via_stdin_without_logging_or_token_in_gpg(self):
        calls, output = [], io.StringIO()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(setup, 'execute', side_effect=self.fake(calls)), patch.object(setup.subprocess, 'run') as cleanup, redirect_stdout(output):
            setup.bootstrap()
        writes = [(args, data) for args, _, data in calls if args[:3] == ['gh', 'secret', 'set']]
        self.assertEqual([(args[3], data) for args, data in writes], [
            ('APT_SIGNING_KEY', b'fake-private-material'),
            ('APT_SIGNING_REVOCATION', b'fake-revocation-material')])
        for args, env, data in calls:
            self.assertNotIn('fake-private-material', ' '.join(args))
            if args[0] == 'gpg':
                self.assertNotIn('GH_TOKEN', env)
                self.assertNotIn('APT_BOOTSTRAP_TOKEN', env)
                self.assertFalse(Path(env['GNUPGHOME']).exists())
        self.assertIn(self.fingerprint, output.getvalue())
        self.assertNotIn('fake-private-material', output.getvalue())
        self.assertNotIn('fake-revocation-material', output.getvalue())
        cleanup.assert_called_once()

    def test_partial_write_failure_keeps_public_fingerprint_and_cleans_runner(self):
        order = ['APT_SIGNING_KEY', 'APT_SIGNING_REVOCATION', setup.FINGERPRINT]
        for index, failed_write in enumerate(order):
            calls, output = [], io.StringIO()
            with self.subTest(write=failed_write), patch.dict(os.environ, self.environment, clear=True), patch.object(setup, 'execute', side_effect=self.fake(calls, fail_write=failed_write)), patch.object(setup.subprocess, 'run') as cleanup, redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, 'simulated'):
                    setup.bootstrap()
                attempted = [args[3] if args[:3] == ['gh', 'secret', 'set'] else setup.FINGERPRINT
                             for args, _, _ in calls
                             if args[:3] == ['gh', 'secret', 'set'] or 'POST' in args]
                self.assertEqual(attempted, order[:index + 1])
                self.assertIn(self.fingerprint, output.getvalue())
                self.assertNotIn('Signing configuration stored', output.getvalue())
                self.assertNotIn('fake-private-material', output.getvalue())
                self.assertNotIn('fake-revocation-material', output.getvalue())
                cleanup.assert_called_once()
                self.assertEqual(cleanup.call_args.args[0], ['gpgconf', '--kill', 'gpg-agent'])
                homes = {env['GNUPGHOME'] for args, env, _ in calls if args[0] == 'gpg'}
                self.assertEqual(len(homes), 1)
                self.assertEqual(cleanup.call_args.kwargs['env']['GNUPGHOME'], next(iter(homes)))
                self.assertTrue(all(not Path(home).exists() for home in homes))


if __name__ == '__main__':
    unittest.main()
