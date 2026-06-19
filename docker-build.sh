#!/usr/bin/env bash
# Build the AKTools Docker image
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-aktools}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "Building ${IMAGE_NAME}:${IMAGE_TAG} ..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo "Done. Run with: docker compose up"
