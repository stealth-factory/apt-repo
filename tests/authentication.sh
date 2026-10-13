#!/bin/bash
# Verify an existing signed snapshot without consulting any distro mirror.
set -euo pipefail
repository=$1
keyring=$2
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
chmod 755 "$work"
cp -r "$repository" "$work/repository"
mkdir -p "$work/empty-sources" "$work/lists/partial"
printf 'deb [arch=amd64 signed-by=%s] file:%s stable main\n' "$keyring" "$work/repository" > "$work/source.list"
options=(-o "Dir::Etc::sourcelist=$work/source.list"
  -o "Dir::Etc::sourceparts=$work/empty-sources" -o "Dir::State::lists=$work/lists"
  -o APT::Update::Error-Mode=any)
# An inaccessible key/file or a broken baseline is a test failure.
LC_ALL=C apt-get update "${options[@]}"
release="$work/repository/dists/stable/InRelease"
grep -q '^Origin: Stealth Factory$' "$release"
sed 's/^Origin: Stealth Factory$/Origin: Tampered/' "$release" > "$work/changed"
mv "$work/changed" "$release"
rm -rf "$work/lists"
mkdir -p "$work/lists/partial"
if LC_ALL=C apt-get update "${options[@]}" > "$work/tamper.log" 2>&1; then
  echo 'ERROR: APT accepted tampered signed metadata' >&2
  exit 1
fi
# A network, path, parse or missing-key error does not prove signature rejection.
grep -Eq 'BADSIG|At least one invalid signature was encountered' "$work/tamper.log"
