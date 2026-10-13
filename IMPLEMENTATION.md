# OPS-67 implementation scope

Prepare a shared signed APT repository for approved Stealth Factory packages,
starting with Opscope Linux amd64. Validate upstream checksums and metadata,
retain immutable package versions, generate indexes and signed Release files,
and prepare serialized publication with downgrade protection.

Implementation starts in a draft PR linked to
[OPS-67](https://linear.app/stealth-company/issue/OPS-67) and
[opscope #392](https://github.com/stealth-factory/opscope/pull/392).

The optional [GitHub-only setup](docs/github-key-setup.md) requires explicit
manual confirmation and a separately approved temporary environment-write token.
No private key is generated during implementation or tests. Credential grants,
owner-controlled access changes, live publication, and merges require approval.

The publishing workflow requests job-scoped token permissions. Those permissions
require the owner approval described in [operations](docs/operations.md) before
activation; no access settings have been changed by this implementation.
