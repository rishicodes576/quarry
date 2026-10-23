#!/bin/sh
# Native architecture: retain exactly the binary's linked libraries and package notices.
set -eu
mkdir -p /runtime/var/lib/dpkg /runtime/usr/share/doc /runtime/etc/ssl/certs /runtime/tmp /runtime/qdrant/storage /runtime/qdrant/snapshots
chmod 1777 /runtime/tmp
chown -R 10001:10001 /runtime/qdrant
ldd /qdrant/qdrant | awk '$2 == "=>" && $3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' | sort -u > /tmp/quarry-libraries
: > /tmp/quarry-packages
while IFS= read -r library; do
    cp --parents "$library" /runtime/
    (dpkg-query -S "$library" 2>/dev/null || dpkg-query -S "$(readlink -f "$library")") | awk -F': /' '$1 ~ /^[a-z0-9][a-z0-9+.:_-]*$/ {print $1}' >> /tmp/quarry-packages
done < /tmp/quarry-libraries
echo ca-certificates >> /tmp/quarry-packages
sort -u /tmp/quarry-packages > /tmp/quarry-packages-sorted
while IFS= read -r package; do
    dpkg-query -s "$package" >> /runtime/var/lib/dpkg/status
    echo >> /runtime/var/lib/dpkg/status
    notice="/usr/share/doc/${package%%:*}"
    if [ -d "$notice" ]; then cp -r "$notice" /runtime/usr/share/doc/; fi
done < /tmp/quarry-packages-sorted
cp /etc/os-release /runtime/etc/
cp /etc/ssl/certs/ca-certificates.crt /runtime/etc/ssl/certs/
