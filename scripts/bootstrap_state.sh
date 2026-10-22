#!/usr/bin/env bash
# One-time setup: creates the S3 bucket that holds the shared Terraform state and
# writes infra/backend.hcl. Run once per AWS account, then commit backend.hcl so
# teammates run `make init` and deploy to the same live stack.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${REGION:-eu-west-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="smartthumb-tfstate-${ACCOUNT_ID}-${REGION}"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "State bucket $BUCKET already exists"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  echo "Created $BUCKET"
fi
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

cat > infra/backend.hcl <<HCL
bucket       = "$BUCKET"
key          = "smartthumb/terraform.tfstate"
region       = "$REGION"
encrypt      = true
use_lockfile = true
HCL
echo "Wrote infra/backend.hcl"
