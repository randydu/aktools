#!/usr/bin/env bash
# Build the AKTools Docker image (pre-build docs first)
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-aktools}"
IMAGE_TAG="${IMAGE_TAG:-$(git describe --tags --abbrev=0 2>/dev/null || echo latest)}"

echo "Building docs site ..."
python -m mkdocs build

echo "Building ${IMAGE_NAME}:${IMAGE_TAG} ..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -t "${IMAGE_NAME}:latest" .

echo "Done. Run with: docker compose up"
