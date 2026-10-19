# Stealth Factory APT repository

Shared tooling for signed Debian packages for
[Opscope](https://github.com/stealth-factory/opscope) and
[gh-pr-manager](https://github.com/stealth-factory/gh-pr-manager). This is our
own package repository; it is not inclusion in Debian or Ubuntu's official
archives.

**Not live yet.** Merging this implementation does not activate publishing.
See [activation and recovery](docs/operations.md) for the exact approval and
configuration requirements. For a key generated and held entirely on GitHub,
see [one-time signing setup](docs/github-key-setup.md). No signing credentials
are stored in this tree.

## Install after activation

Both packages support **Linux amd64 with glibc 2.35 or newer**. The lifecycle
checks target Ubuntu 22.04 and Debian 12. There is no Linux arm64 package.
Node and Rust are not required; npm/npx remains each application's default
install route.

Once the site and its independently announced signing fingerprint are available:

```sh
sudo apt install ca-certificates curl gnupg
curl --fail --show-error --silent --location \
  https://stealth-factory.github.io/apt-repo/stealth-factory.asc \
  --output /tmp/stealth-factory.asc
gpg --show-keys --with-fingerprint /tmp/stealth-factory.asc
# List primary fingerprints only (one line per trusted primary key):
gpg --show-keys --with-colons /tmp/stealth-factory.asc \
  | awk -F: '$1 == "pub" { primary=1; next } primary && $1 == "fpr" { print $10; primary=0 }'
# Compare the COMPLETE SET of primary fingerprints with the independently
# announced approved set. Reject missing OR additional/unannounced primary keys.
# No production fingerprint exists yet. Do not continue until one is announced.
sudo install -d -m 0755 /etc/apt/keyrings
sudo install -m 0644 /tmp/stealth-factory.asc /etc/apt/keyrings/stealth-factory.asc
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/stealth-factory.asc] https://stealth-factory.github.io/apt-repo stable main' \
  | sudo tee /etc/apt/sources.list.d/stealth-factory.list
sudo apt update
sudo apt install opscope          # and/or
sudo apt install gh-pr-manager
opscope clocks
gh-pr-manager --version
```

`Signed-By` scopes this key to this source. Do not use `apt-key`,
`trusted=yes`, or disable signature checks. Every primary key in that file is trusted by APT unless further restricted.
Inspect all primary fingerprints, not merely whether the announced one appears.
Trusting the key authorizes its
holder to supply packages installed as root. HTTPS protects key transport;
checking the announced fingerprint establishes which key you intended to trust.

Upgrade with `sudo apt update && sudo apt upgrade`. All seventeen Opscope
binaries live together in `/usr/libexec/opscope`; only an exec wrapper named
`opscope` is installed in `/usr/bin`. Coreutils' `link` stays untouched.
User settings in `~/.config/opscope` are not owned or removed by the package.

gh-pr-manager is a single binary installed as `/usr/bin/gh-pr-manager`, with
its README, changelog and licence in `/usr/share/doc/gh-pr-manager`. It reads
`GH_TOKEN`/`GITHUB_TOKEN` or the GitHub CLI's login at run time; `gh` is not a
package dependency. Its
settings in `~/.config/gh-pr-manager` are not owned or removed by the package.

Remove a package with `sudo apt remove opscope` or
`sudo apt remove gh-pr-manager`. To stop using this source:

```sh
sudo rm /etc/apt/sources.list.d/stealth-factory.list
sudo rm /etc/apt/keyrings/stealth-factory.asc
sudo apt update
```

Remove the source/key only when you no longer want updates for any application
from this shared repository. Package removal does not remove personal settings.

## How releases arrive

Each application's successful tagged release job sends a `repository_dispatch`
to this repository using its existing Homebrew bot token (`GH_TOKEN`, falling
back to `RELEASE_TOKEN`). Each package has its own event type, listed as
`dispatch` in `packages.json`: `opscope-release` from `stealth-factory/opscope`
and `gh-pr-manager-release` from `stealth-factory/gh-pr-manager`. A type is
accepted only with its own package's source repository. The event carries only the allowlisted source, exact
stable tag, and release commit. No secret is transmitted. The importer resolves
that tag, verifies its commit and public release, and downloads only that
version's `.deb` and checksum. A missing asset pair fails without changing the
live site. Manual recovery on `main` requires an explicit package and tag.
No enable flag is required. Signing and hosting must still be configured before
publication can succeed; missing setup fails the run rather than skipping it.

A separate refresh runs on the **1st of each month at 19:30 Asia/Taipei
(11:30 UTC, `30 11 1 * *`)** and re-signs the already imported package indexes
before their 90-day expiry. It never discovers or imports new releases. No new
credential or expanded account permission is configured by this implementation.

`packages.json` defines the explicitly supported applications. Adding another
application is a reviewed change to this allowlist (including its dispatch
type), the `publish.yml` dispatch types and manual package choices, dependency
policy, package layout checks, and lifecycle tests. A package with a
`private_directory` ships a reviewed binary inventory there (Opscope); one
without ships exactly one executable at `/usr/bin/<package>` plus its
`/usr/share/doc/<package>` files (gh-pr-manager). Unrelated organization content is never
copied or published.

Packages and old by-hash indexes are retained on `apt-state`. Package bytes
are immutable per version; a same-version change or downgrade fails. The
workflow serializes all applications' updates, verifies checksums and package
metadata, signs both `InRelease` and `Release.gpg`, tests the exported public
key through APT, then deploys a complete Pages snapshot. Indexes expire after
90 days and are refreshed by successful scheduled runs.

See [operations](docs/operations.md) for permissions, signing, failure handling,
key rotation, storage limits, and validation gaps.
