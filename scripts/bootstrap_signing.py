"""Explicit one-time GitHub-only key setup. Never run as part of publication."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPOSITORY = 'stealth-factory/apt-repo'
ENVIRONMENT = 'apt-publishing'
SECRETS = {'APT_SIGNING_KEY', 'APT_SIGNING_REVOCATION'}
FINGERPRINT = 'APT_SIGNING_FINGERPRINT'


def execute(args, *, env, data=None):
    # Neither private bytes nor subprocess diagnostics are allowed into logs.
    result = subprocess.run(args, input=data, env=env, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} operation failed; check setup permissions and partial state')
    return result.stdout


def bootstrap():
    expected = {
        'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': REPOSITORY,
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'RUNNER_ENVIRONMENT': 'github-hosted',
        'APT_BOOTSTRAP_CONFIRMATION': 'GENERATE_INITIAL_APT_KEY',
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ValueError('Only an explicitly confirmed manual run on the hosted main workflow is allowed')
    token = os.environ.get('APT_BOOTSTRAP_TOKEN')
    if not token:
        raise ValueError('Configure the approved temporary APT_BOOTSTRAP_TOKEN first')
    # Give the token only to gh, not to GnuPG or its agent.
    base_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
    gh_env = {**base_env, 'GH_TOKEN': token, 'GH_PROMPT_DISABLED': '1'}

    def gh(*args, data=None):
        return execute(['gh', *args], env=gh_env, data=data)

    endpoint = f'repos/{REPOSITORY}/environments/{ENVIRONMENT}'
    # Paginate metadata, never fetch secret values. Refuse even partial setup.
    existing = gh('api', '--paginate', f'{endpoint}/secrets', '--jq', '.secrets[].name').decode().splitlines()
    variables = gh('api', '--paginate', f'{endpoint}/variables', '--jq', '.variables[].name').decode().splitlines()
    if SECRETS.intersection(existing) or FINGERPRINT in variables:
        raise ValueError('Signing configuration already exists, possibly partially; refusing replacement')

    with tempfile.TemporaryDirectory(prefix='apt-bootstrap-', dir=os.environ.get('RUNNER_TEMP')) as home:
        os.chmod(home, 0o700)
        gpg_env = {**base_env, 'GNUPGHOME': home}

        def gpg(*args, data=None):
            return execute(['gpg', '--batch', *args], env=gpg_env, data=data)

        try:
            gpg('--pinentry-mode', 'loopback', '--passphrase', '', '--quick-generate-key',
                'Stealth Factory APT Repository', 'rsa4096', 'sign', '1y')
            records = gpg('--with-colons', '--list-secret-keys').decode().splitlines()
            fingerprints = [line.split(':')[9] for line in records if line.startswith('fpr:')]
            if len(fingerprints) != 1 or not re.fullmatch(r'[A-F0-9]{40}', fingerprints[0]):
                raise ValueError('Expected exactly one primary signing key')
            fingerprint = fingerprints[0]
            # Verify signing works noninteractively before persisting the key.
            probe = Path(home) / 'probe'
            probe.write_bytes(b'Stealth Factory APT signing setup verification\n')
            gpg('--local-user', fingerprint, '--detach-sign', str(probe))
            gpg('--verify', str(probe) + '.sig', str(probe))
            private = gpg('--armor', '--export-secret-keys', fingerprint)
            revocation = (Path(home) / 'openpgp-revocs.d' / f'{fingerprint}.rev').read_bytes()
            if not private or not revocation:
                raise ValueError('Missing generated signing or revocation material')
            # Public fingerprint is safe to record, and allows recovery if a later API write fails.
            print(f'Public primary fingerprint: {fingerprint}', flush=True)
            print('Key expiry: one year from generation. Private material is never logged.', flush=True)
            # Each API write is independent. Any partial state blocks reruns; never rotate silently.
            gh('secret', 'set', 'APT_SIGNING_KEY', '--repo', REPOSITORY, '--env', ENVIRONMENT, data=private)
            gh('secret', 'set', 'APT_SIGNING_REVOCATION', '--repo', REPOSITORY, '--env', ENVIRONMENT, data=revocation)
            gh('api', '--method', 'POST', f'{endpoint}/variables', '--input', '-',
               data=json.dumps({'name': FINGERPRINT, 'value': fingerprint}).encode())
            print('Signing configuration stored. Revoke the temporary token and remove APT_BOOTSTRAP_TOKEN.', flush=True)
        finally:
            subprocess.run(['gpgconf', '--kill', 'gpg-agent'], env=gpg_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    try:
        bootstrap()
    except (ValueError, RuntimeError, OSError) as error:
        # Avoid tracebacks containing command arguments or sensitive subprocess output.
        print(f'::error::{error}')
        raise SystemExit(1)
