#!/usr/bin/env bash
# Free space on GitHub-hosted ubuntu-latest by removing preinstalled toolchains we do not use.
set -euo pipefail
df -h
sudo rm -rf \
  /usr/share/dotnet \
  /usr/local/lib/android \
  /opt/ghc \
  /opt/hostedtoolcache/CodeQL \
  /usr/local/share/powershell \
  /usr/share/swift \
  /usr/local/share/chromium \
  /usr/share/miniconda \
  /usr/local/.ghcup \
  /opt/az \
  /opt/microsoft \
  /usr/share/gradle-*.zip \
  /opt/hostedtoolcache/go \
  /opt/hostedtoolcache/PyPy \
  /opt/hostedtoolcache/Ruby \
  || true
echo "---- after cleanup ----"
df -h
