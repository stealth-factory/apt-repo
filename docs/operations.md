# Activation and operations

Tracked by [OPS-67](https://linear.app/stealth-company/issue/OPS-67), with
[Opscope packaging PR #392](https://github.com/stealth-factory/opscope/pull/392)
and [repository PR #1](https://github.com/stealth-factory/apt-repo/pull/1).

## Approval boundary and exact setup

The repository was created by its owner as public. Push access was verified.
Read-only inspection found no repository secrets, variables, environments, or
Pages site at implementation time. No permissions or credentials were changed.

These are separate owner-approved activation actions, not implemented setup:

1. Review and merge both PRs through the normal review process. No merge is
   performed by this task. Release a new Opscope tag carrying the Debian packer;
   older releases do not contain the required `.deb` assets.
2. Create or select a dedicated OpenPGP repository signing key under the owner's
   custody, with an offline backup and revocation certificate. Set its expiry
   and renewal policy. The code never generates a key. The current unattended
   signing interface expects an export usable by batch GnuPG without a
   passphrase prompt (for example a dedicated exported signing subkey). Approve
   this custody model before supplying it; hardware/remote signing would need
   a separately reviewed adapter.
3. Configure an `apt-publishing` environment with required reviewers and a
   deployment branch restriction to `main`. Store the private ASCII-armored
   export only as environment secret `APT_SIGNING_KEY`. Store its full primary
   fingerprint as environment variable `APT_SIGNING_FINGERPRINT` (40 uppercase
   hexadecimal digits). Publish the fingerprint through a trusted maintainer
   announcement. Never paste private material in an issue, PR, log or source.
4. Enable GitHub Pages with GitHub Actions as the source. Approve this workflow's
   job-scoped `contents: write` (only used to persist `apt-state`), `pages: write`
   and `id-token: write` (Pages deployment) permissions. Restrict `apt-state`
   writes appropriately; do not grant new long-lived tokens or deploy keys.
   If organization policy blocks the built-in token, stop for approval rather
   than introducing a more privileged credential.
5. After completing the approved setup, dispatch `publish.yml` on `main` with
   package `opscope` and its exact released `vX.Y.Z` tag, and approve the protected
   environment. This performs the first **public package publication**. Future
   successful tagged Opscope releases notify this repository automatically.

Required reviewers may mean each release or scheduled metadata refresh needs approval. The
owner decides whether to approve each run or authorize unattended publication;
changing that protection is another access decision. There is no enable-variable
switch: release dispatches, scheduled refreshes and manual recovery run on `main`.
Missing setup fails visibly instead of silently skipping the job. PR tests have
read-only permissions. To pause publication during an incident, disable the
`Publish signed APT repository` workflow in GitHub Actions, then cancel all runs
that are running, queued, or waiting for approval. Confirm none can still deploy
before treating publication as paused. This does not change stored credentials
or their permissions.

Disabled workflows do not retain release dispatches for later replay. Record
releases published during the pause and any interrupted imports. After recovery,
re-enable the workflow and manually dispatch `publish.yml` on `main` for each
missed package/tag in ascending version order, waiting for each publication to
succeed before the next. Check the retained `apt-state` history first: an already
imported identical version is retryable; if a newer version has already landed,
report any missing older package for reviewed recovery rather than bypassing the
downgrade check. Scheduled refreshes only re-sign existing packages and cannot
recover missed releases. Coordinate recovery with upstream release publishing
so a new dispatch does not overtake the versions being replayed.

## Publication contract

Opscope's `apt-repository` job depends on successful release asset publication
and uses the same `secrets.GH_TOKEN || secrets.RELEASE_TOKEN` pattern as Homebrew.
Read-only inspection verified an existing `GH_TOKEN` secret name; secret values
were neither read nor changed. The owner reports its bot already has access to
both repositories. Its actual dispatch capability will be exercised only in an
approved release run; this task does not retrieve the secret or send a live event.

The [repository_dispatch endpoint](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event)
requires Contents write for fine-grained tokens (classic tokens require repo
scope), avoiding a new Actions-write grant. Do not mint a new token or broaden
access if a dispatch fails; report the API error and verify the existing bot's
configured access with the owner. Only source/tag/commit travel in the payload;
signing material stays in the apt-publishing environment.

The workflow only imports the exact stable public release requested by a
validated dispatch or explicit manual recovery, from `packages.json`. The tag
must resolve to the dispatched commit. For schedule testing, the refresh temporarily runs daily at 19:30 Asia/Taipei
(11:30 UTC, `30 11 * * *`) and only refreshes retained metadata. Restore the
monthly schedule (`23 5 1 * *`) through a reviewed change after testing; no
automatic end date is configured. Metadata still expires after 90 days. Missed runs still need recovery before expiry; the validity window does not
replace monitoring or recovery. It never queries latest releases. Empty initial state fails
closed on a refresh; bootstrap by importing an explicit approved release. Incoming
checksums must name exactly the expected package; control metadata must match
the approved name, architecture, version and dependencies. Unexpected relationships, non-root ownership, writable/special file or directory
modes, maintainer scripts, symlinks, setuid files and files outside the application's private
layout are refused. A checksum alongside a release detects corruption; it does
not independently authenticate a compromised upstream maintainer account.

All retained packages are revalidated before indexing. Neither packages nor
by-hash indexes are deleted automatically. Packages and metadata are signed in
a temporary GnuPG home outside `site`, then the exported public key verifies
both signatures. No private keyring enters `apt-state` or Pages artifacts.
The payload and its embedded inventory must match the repository-owned approved
binary list; an artifact cannot define its own expected coverage.
The signed snapshot is tested in clean Ubuntu 22.04 and Debian 12 containers,
including rejection of tampered signed metadata. If multiple versions exist,
APT installs the previous version and upgrades to the latest. The first release
can prove clean install only; upgrade evidence needs a second release.

The workflow persists the complete verified snapshot before deployment. If
Pages fails, the next scheduled/manual run restores that same package history,
regenerates and resigns metadata, and retries the full deployment. The public
site remains at its last deployed snapshot until Pages succeeds. Never force
push `apt-state`: an unexpected concurrent write should fail and be reconciled.

Immutable package URLs and retained by-hash indexes let clients finish downloads
using older cached indexes across deployments. The workflow has one shared
concurrency group and does not cancel a running publication. An older upstream
release cannot replace a newer retained version. A same-version retry must have
identical bytes. Release metadata expires after 90 days; monitor failed runs and
restore signing/publication before then. APT should fail closed on expired data.

## Metadata freshness and signing-key expiry

`Valid-Until` is an APT metadata policy, not a requirement to replace or renew a
signing key every ninety days. The owner approved a 90-day window to bound how
long an attacker or stale mirror can replay an old signed package index while
leaving recovery time for missed runs. The intended monthly refresh normally
leaves at least 59 days of margin; the temporary daily schedule test does not
change the 90-day validity policy. This is a configurable design choice, not
an APT mandate; this implementation retains it unless the owner explicitly
approves a different freshness/security policy. Without it, an old correctly
signed index could remain acceptable indefinitely while the key is trusted.

The repository signs central Release metadata covering all package indexes,
which in turn hash the package bytes. Applications do not each require a new
signing key. The repository's OpenPGP key has its own owner-selected expiry and
renewal policy. Refreshing Release metadata does not extend the key's expiry;
a valid key is needed for every refresh, and key rotation remains separate.

## Recovery and key rotation

For a failed download or invalid package, fix upstream and publish a new version.
Do not replace a published version's bytes or suppress signature validation.
For a failed Pages deployment, retry the workflow on main after correcting the
approved hosting configuration. An old source release without Debian assets
cannot be imported; release the packaging implementation first.

For planned key rotation, get approval for the new key and custody model first.
Announce the new fingerprint independently and publish a reviewed key bundle
containing exactly the old and new public keys while metadata is still signed by the
old key. Announce the complete approved primary-fingerprint set independently;
users must reject a downloaded bundle containing any extra or missing primary
key. Existing users must refresh their scoped key file during this overlap;
there is no automatic keyring-package rotation yet. After the migration window,
update the protected signing secret and fingerprint, test the signed snapshot,
and switch signatures. Retain the old public key and its revocation statement
for audit. The exporter currently writes the active key alone, so preserving an
overlap bundle requires a reviewed implementation change before rotating.

If a key is compromised, disable publishing immediately, revoke it, notify users
through a trusted channel, and replace it only after approval. Users must verify
the new fingerprint and replace their scoped key file manually. A signature by
the compromised key cannot establish trust in its replacement. Do not tell users
to disable APT checks while recovering.

`apt-state` retains binary history and will grow. Monitor GitHub repository,
file-size and Pages storage limits before onboarding more packages. Moving to
object storage or pruning history is a separately reviewed hosting/retention
change; never delete package URLs still referenced by supported client indexes.

## Validation

Run `python3 -m unittest discover -s tests -v` on Ubuntu with `apt-utils` and
`dpkg` installed. It verifies version handling, exact checksum filenames,
immutable retries, stale rejection, malicious layouts/hooks, corrupted retained
packages, indexes, and retained by-hash objects. macOS skips tests needing Linux
tools. No tests generate signing credentials.

`tests/lifecycle.sh` consumes an **already signed** snapshot at `/repo` in a
clean root container. It is run by the publish workflow before deployment.
Actual signature verification, signed install/upgrade and Pages reachability
remain unverified until an approved key and hosting setup are available. A tag
producing and uploading the new `.deb` remains a release acceptance check; PR
builds cannot prove a public release occurred.

References: [Debian apt-secure](https://manpages.debian.org/bookworm/apt/apt-secure.8.en.html)
and [dpkg-deb](https://manpages.debian.org/bookworm/dpkg/dpkg-deb.1.en.html).
