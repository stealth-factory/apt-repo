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
# Minimal images may exclude installed documentation. Read the packaged list.
dpkg-deb --fsys-tarfile "/repo/pool/main/opscope/opscope_${latest}_amd64.deb" \
  | tar -xOf - ./usr/share/doc/opscope/binaries > /tmp/binaries
diff -u /tests/opscope-binaries /tmp/binaries
while read -r binary; do
  test "$(/usr/libexec/opscope/"$binary" --version)" = "$binary ${stamp#opscope }"
done < /tests/opscope-binaries
opscope clocks --help | grep -qi clocks
test "$(sha256sum /usr/bin/link)" = "$before"
dpkg -V opscope
dpkg -r opscope
test ! -e /usr/bin/opscope
test ! -e /usr/libexec/opscope
test "$(sha256sum /usr/bin/link)" = "$before"
# Test authentication independently of distro mirror availability.
bash /tests/authentication.sh /repo /etc/apt/keyrings/stealth-factory.asc
