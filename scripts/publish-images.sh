#!/usr/bin/env bash
# Build once and publish runtime-specific tags to two existing private repositories.
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:?Provide a new immutable version, for example v3}"
[[ "$version" =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid image version'; exit 1; }
region="${AWS_DEFAULT_REGION:-us-east-1}"
account_id="$(aws sts get-caller-identity --query Account --output text)"
registry="$account_id.dkr.ecr.$region.amazonaws.com"
for service in catalog reservation; do
  aws ecr describe-repositories --region "$region" --repository-names "kostcycle-$service" >/dev/null
  if aws ecr describe-images --region "$region" --repository-name "kostcycle-$service" --image-ids "imageTag=$version" >/dev/null 2>&1; then
    echo "Version $version already exists for $service; choose a new version."
    exit 1
  fi
done
sudo docker build -t "kostcycle-base:$version" .
aws ecr get-login-password --region "$region" | sudo docker login --username AWS --password-stdin "$registry"
trap 'sudo docker logout "$registry" >/dev/null 2>&1 || true' EXIT
for service in catalog reservation; do
  sudo docker tag "kostcycle-base:$version" "$registry/kostcycle-$service:$version"
  sudo docker push "$registry/kostcycle-$service:$version"
done
