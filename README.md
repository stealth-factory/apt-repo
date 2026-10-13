# Stealth Factory APT repository

Shared tooling for signed Debian packages, beginning with
[Opscope](https://github.com/stealth-factory/opscope). This is our own package
repository; it is not inclusion in Debian or Ubuntu's official archives.

**Not live yet.** Merging this implementation does not activate publishing.
See [activation and recovery](docs/operations.md) for the exact approval and
configuration requirements. No signing credentials are stored in this tree.

## Install after activation

Opscope packages support **Linux amd64 with glibc 2.35 or newer**. The lifecycle
checks target Ubuntu 22.04 and Debian 12. There is no Linux arm64 package.
Node and Rust are not required; npm/npx remains Opscope's default install route.

Once the site and its independently announced signing fingerprint are available:

```sh
sudo apt install ca-certificates curl gnupg
curl --fail --show-error --silent --location \
  https://stealth-factory.github.io/apt-repo/stealth-factory.asc \
  --output /tmp/stealth-factory.asc
gpg --show-keys --with-fingerprint /tmp/stealth-factory.asc
# Compare the full primary fingerprint with the maintainer's approved
# announcement BEFORE continuing. No production fingerprint exists yet.
sudo install -d -m 0755 /etc/apt/keyrings
sudo install -m 0644 /tmp/stealth-factory.asc /etc/apt/keyrings/stealth-factory.asc
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/stealth-factory.asc] https://stealth-factory.github.io/apt-repo stable main' \
  | sudo tee /etc/apt/sources.list.d/stealth-factory.list
sudo apt update
sudo apt install opscope
opscope clocks
```

`Signed-By` scopes this key to this source. Do not use `apt-key`,
`trusted=yes`, or disable signature checks. Trusting the key authorizes its
holder to supply packages installed as root. HTTPS protects key transport;
checking the announced fingerprint establishes which key you intended to trust.

Upgrade with `sudo apt update && sudo apt upgrade`. All seventeen Opscope
binaries live together in `/usr/libexec/opscope`; only an exec wrapper named
`opscope` is installed in `/usr/bin`. Coreutils' `link` stays untouched.
User settings in `~/.config/opscope` are not owned or removed by the package.

Remove the package with `sudo apt remove opscope`. To stop using this source:

```sh
sudo rm /etc/apt/sources.list.d/stealth-factory.list
sudo rm /etc/apt/keyrings/stealth-factory.asc
sudo apt update
```

Remove the source/key only when you no longer want updates for any application
from this shared repository. Package removal does not remove personal settings.

## How releases arrive

The gated publishing workflow checks allowlisted upstream GitHub releases every
hour and supports manual retry on `main`. A new stable release with a `.deb`
and matching SHA-256 file is imported automatically after activation. No
cross-repository token, webhook credential, or upstream workflow dispatch is
needed. A missing asset pair fails clearly and leaves the live site unchanged.

`packages.json` defines the explicitly supported applications. Adding another
application is a reviewed change to this allowlist, dependency policy, package
layout checks, and lifecycle tests. Unrelated organization content is never
copied or published.

Packages and old by-hash indexes are retained on `apt-state`. Package bytes
are immutable per version; a same-version change or downgrade fails. The
workflow serializes all applications' updates, verifies checksums and package
metadata, signs both `InRelease` and `Release.gpg`, tests the exported public
key through APT, then deploys a complete Pages snapshot. Indexes expire after
14 days and are refreshed by successful scheduled runs.

See [operations](docs/operations.md) for permissions, signing, failure handling,
key rotation, storage limits, and validation gaps.
