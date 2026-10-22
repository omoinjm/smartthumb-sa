#!/usr/bin/env bash
# Builds the Pillow Lambda layer for python3.12 / x86_64 without Docker by
# downloading the manylinux wheel that matches the Lambda runtime.
set -euo pipefail
cd "$(dirname "$0")/.."

PILLOW_VERSION="${PILLOW_VERSION:-11.3.0}"
rm -rf build/layer
mkdir -p build/layer/python

python3 -m pip install \
  --quiet \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target build/layer/python \
  "pillow==${PILLOW_VERSION}"

echo "Pillow ${PILLOW_VERSION} layer ready in build/layer ($(du -sh build/layer | cut -f1))"
