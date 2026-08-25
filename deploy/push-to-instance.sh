#!/usr/bin/env bash
# Ship the locally built, locally verified image to the instance and start it.
#
#     ./deploy/push-to-instance.sh ubuntu@<public-ip>
#
# Sends the image rather than rebuilding on the box: the build needs Node and
# the whole npm tree, the instance does not, and this way what runs in
# production is the exact image that passed here.
set -euo pipefail

TARGET="${1:?usage: push-to-instance.sh user@host}"
IMAGE="${IMAGE:-shadeway:local}"

arch_local=$(docker image inspect "$IMAGE" --format '{{.Architecture}}')
arch_remote=$(ssh "$TARGET" 'uname -m')
case "$arch_remote" in
  aarch64|arm64) arch_remote=arm64 ;;
  x86_64|amd64)  arch_remote=amd64 ;;
esac
if [ "$arch_local" != "$arch_remote" ]; then
  echo "image is $arch_local but the instance is $arch_remote." >&2
  echo "rebuild with: docker build --platform linux/$arch_remote -t $IMAGE ." >&2
  exit 1
fi
echo "architecture matches ($arch_local)"

echo "shipping $IMAGE — this is a ~233 MB compressed transfer"
docker save "$IMAGE" | gzip -1 | ssh "$TARGET" 'gunzip | sudo docker load'

echo "starting"
ssh "$TARGET" 'sudo systemctl restart shadeway && sleep 20 && sudo systemctl is-active shadeway'
ssh "$TARGET" 'curl -fsS http://localhost/api/health' && echo
echo "done — http://${TARGET#*@}/"
