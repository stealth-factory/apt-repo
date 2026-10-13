#!/bin/bash
# Disposable clean amd64 Debian/Ubuntu container. Requires a signed /repo.
set -euo pipefail
mkdir -p /etc/apt/keyrings
cp /repo/stealth-factory.asc /etc/apt/keyrings/stealth-factory.asc
chmod 644 /etc/apt/keyrings/stealth-factory.asc
printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/stealth-factory.asc] file:/repo stable main\n' > /etc/apt/sources.list.d/stealth-factory.list
apt-get update
before=$(sha256sum /usr/bin/link)
mapfile -t versions < <(apt-cache madison opscope | awk '{print $3}' | sort -Vu)
test "${#versions[@]}" -gt 0
latest=${versions[${#versions[@]}-1]}
if [ "${#versions[@]}" -gt 1 ]; then
  previous=${versions[${#versions[@]}-2]}
  apt-get install -y "opscope=$previous"
  find /usr/libexec/opscope -type f > /tmp/previous-files
  apt-get install --only-upgrade -y opscope
  test "$(dpkg-query -W -f='${Version}' opscope)" = "$latest"
  while read -r old; do
    if ! dpkg -L opscope | grep -Fxq "$old"; then test ! -e "$old"; fi
  done < /tmp/previous-files
else
  echo 'First package: clean install tested; cross-release upgrade awaits a second version.'
  apt-get install -y opscope
fi
stamp=$(opscope --version)
case "$stamp" in "opscope $latest ("*) ;; *) exit 1;; esac
while read -r binary; do
  test "$(/usr/libexec/opscope/"$binary" --version)" = "$binary ${stamp#opscope }"
done < /usr/share/doc/opscope/binaries
opscope clocks --help | grep -qi clocks
test "$(sha256sum /usr/bin/link)" = "$before"
dpkg -V opscope
dpkg -r opscope
test ! -e /usr/bin/opscope
test ! -e /usr/libexec/opscope
test "$(sha256sum /usr/bin/link)" = "$before"
# Authentication must fail if the advertised repository loses its signature.
# This is tested with a copied snapshot; the input remains read-only.
cp -r /repo /tmp/tampered
sed -i 's/^Origin:.*/Origin: Tampered/' /tmp/tampered/dists/stable/InRelease
sed -i 's|file:/repo|file:/tmp/tampered|' /etc/apt/sources.list.d/stealth-factory.list
rm -rf /var/lib/apt/lists/*
if apt-get update -o APT::Update::Error-Mode=any; then
  echo 'ERROR: APT accepted tampered signed metadata' >&2
  exit 1
fi
