#!/bin/bash
# Disposable clean amd64 Debian/Ubuntu container. Requires a signed /repo.
set -euo pipefail
mkdir -p /etc/apt/keyrings
cp /repo/stealth-factory.asc /etc/apt/keyrings/stealth-factory.asc
chmod 644 /etc/apt/keyrings/stealth-factory.asc
printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/stealth-factory.asc] file:/repo stable main\n' > /etc/apt/sources.list.d/stealth-factory.list
apt-get update

opscope_lifecycle() {
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
}

# A single executable in /usr/bin; no private directory or binary manifest.
gh_pr_manager_lifecycle() {
  mapfile -t versions < <(apt-cache madison gh-pr-manager | awk '{print $3}' | sort -Vu)
  test "${#versions[@]}" -gt 0
  latest=${versions[${#versions[@]}-1]}
  if [ "${#versions[@]}" -gt 1 ]; then
    previous=${versions[${#versions[@]}-2]}
    apt-get install -y "gh-pr-manager=$previous"
    dpkg -L gh-pr-manager | while read -r file; do [ ! -f "$file" ] || echo "$file"; done > /tmp/previous-files
    apt-get install --only-upgrade -y gh-pr-manager
    test "$(dpkg-query -W -f='${Version}' gh-pr-manager)" = "$latest"
    while read -r old; do
      if ! dpkg -L gh-pr-manager | grep -Fxq "$old"; then test ! -e "$old"; fi
    done < /tmp/previous-files
  else
    echo 'First package: clean install tested; cross-release upgrade awaits a second version.'
    apt-get install -y gh-pr-manager
  fi
  # gh-pr-manager X.Y.Z (<sha>, <YYYY-MM-DD>)
  stamp=$(gh-pr-manager --version)
  pattern="^gh-pr-manager ${latest//./\\.} \\([0-9a-f]{7,}, [0-9]{4}-[0-9]{2}-[0-9]{2}\\)$"
  [[ "$stamp" =~ $pattern ]] || { echo "Unexpected version stamp: $stamp" >&2; exit 1; }
  help=$(gh-pr-manager --help)
  grep -qi 'pull requests' <<< "$help"
  dpkg -V gh-pr-manager
  dpkg -r gh-pr-manager
  test ! -e /usr/bin/gh-pr-manager
}

# Every package in the published pool must have lifecycle coverage here.
tested=0
for directory in /repo/pool/main/*/; do
  [ -d "$directory" ] || continue
  case "$(basename "$directory")" in
    opscope) opscope_lifecycle ;;
    gh-pr-manager) gh_pr_manager_lifecycle ;;
    *) echo "No lifecycle test for package: $(basename "$directory")" >&2; exit 1 ;;
  esac
  tested=$((tested + 1))
done
test "$tested" -gt 0
# Test authentication independently of distro mirror availability.
bash /tests/authentication.sh /repo /etc/apt/keyrings/stealth-factory.asc
