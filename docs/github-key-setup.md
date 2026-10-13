# One-time signing setup entirely on GitHub

This optional owner-approved workflow creates the initial repository key on an
ephemeral GitHub-hosted Ubuntu runner. Nothing is generated or downloaded on the
owner's computer. Routine publication reuses the stored key; it never generates
or rotates keys. A new key on every release would break existing clients' trust.

## Required approval and temporary access

Review and merge the setup PR before using it. The default `GITHUB_TOKEN` cannot
manage environment secrets. An administrator must explicitly authorize a
short-lived fine-grained personal access token restricted to
`stealth-factory/apt-repo`, with **Environments: read and write** (plus GitHub's
mandatory Metadata read). This permission can manage the repository's environments;
it is not scoped to one secret. Do not broaden the existing release bot token.

Choose the shortest practical token expiry, obtain organization approval if
required, and add it directly through GitHub as environment secret
`APT_BOOTSTRAP_TOKEN` in `apt-publishing`. Do not paste the token into chat, source,
a workflow input, or logs. The token is needed only for setup and can be revoked
afterward. No access grant or token is created by this PR.

Ensure `apt-publishing` permits only branch `main`. Keep the owner's chosen
reviewer policy: required reviewers pause both setup and routine publications.
Fully unattended publication requires the owner to explicitly choose an
appropriate environment policy; this workflow does not change protection rules.

## Run once

1. In Actions, select **Set up APT signing key once**, choose branch `main`, and
   enter `GENERATE_INITIAL_APT_KEY` as confirmation. Approve the environment if
   prompted. This explicitly approves a dedicated RSA-4096 signing key with a
   one-year expiry and no passphrase, held in GitHub environment secrets.
2. The workflow refuses to proceed if either signing/revocation secret or the
   fingerprint variable already exists. It verifies a test signature before
   saving anything. It shares the publication concurrency group so a publication
   cannot run while the configuration is being written.
3. On success the environment contains `APT_SIGNING_KEY`,
   `APT_SIGNING_REVOCATION`, and public variable `APT_SIGNING_FINGERPRINT`.
   Record and independently announce the public fingerprint shown in the log.
   No private key or revocation certificate is printed, committed, or uploaded as
   an artifact. The temporary runner keyring and agent are cleaned up.
4. Revoke the temporary token in GitHub and delete `APT_BOOTSTRAP_TOKEN` from
   the environment. Do not retain an unnecessary environment-write credential.
5. Configure Pages with GitHub Actions as its source, then manually run
   `Publish signed APT repository` on `main` for `opscope` and the desired exact
   stable tag. Setup does not automatically publish a package.

## Custody, expiry, and partial failures

This is deliberately GitHub-only custody, not an offline backup. GitHub secret
values cannot be read back through its settings or API. Loss/deletion of the
signing secret requires a separately approved recovery or key rotation, and may
require users to replace their trusted public key. The revocation certificate is
also sensitive and stored as a secret, not a public artifact. Its use requires a
separately reviewed recovery workflow. A compromise of this GitHub environment
can compromise both signing and revocation material.

The one-year key expiry is distinct from the repository's 90-day metadata
validity. Arrange renewal before key expiry. This workflow intentionally refuses
replacement and is not a rotation or renewal tool.

Secret and variable writes are not atomic. If setup fails after any write, do
not delete settings and rerun blindly: that could replace a key already trusted
by clients. The public fingerprint is logged before the writes; inspect secret
names and this fingerprint with an administrator and repair the incomplete state
through a separately reviewed action. Reruns refuse any partial configuration.
Do not concurrently edit signing settings while setup runs. If no write occurred,
a retry can generate a fresh key because none was persisted or published.

References: [environment secrets API](https://docs.github.com/en/rest/actions/secrets#create-or-update-an-environment-secret)
and [GITHUB_TOKEN permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).
