#!/usr/bin/env bash
# Removes everything scripts/setup.sh created: the app stack (buckets and their contents,
# Lambdas, CloudFront, API, logs), every Pillow layer version, the GitHub Actions role and
# repo variable, and the Terraform state bucket. The budget alert is left in place.
#
#   scripts/teardown.sh [--no-backup] [--yes]
#
#   --no-backup  don't download both buckets into results/backup-<date>/ first
#   --yes        don't ask for confirmation
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP=1 YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-backup) BACKUP=0; shift ;;
    --yes) YES=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

creds="$(aws configure export-credentials --format env 2>/dev/null)" \
  || { echo "Not logged in to AWS. Run: aws login" >&2; exit 1; }
eval "$creds"
export AWS_REGION="${AWS_REGION:-eu-west-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STATE_BUCKET="smartthumb-tfstate-${ACCOUNT_ID}-${AWS_REGION}"
CI_ROLE="${ROLE:-github-deploy-smartthumb}"
TF=(terraform -chdir=infra)

if [ "$YES" != 1 ]; then
  read -r -p "Permanently delete RekogNail from AWS account $ACCOUNT_ID? Type 'delete' to continue: " answer
  [ "$answer" = delete ] || { echo "Aborted."; exit 1; }
fi

if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  "${TF[@]}" init -input=false -reconfigure -backend-config=backend.hcl >/dev/null

  if [ "$BACKUP" = 1 ]; then
    dest="results/backup-$(date +%F)"
    for b in source_bucket output_bucket; do
      name="$("${TF[@]}" output -raw "$b" 2>/dev/null)" || continue
      echo "==> Backing up s3://$name -> $dest/$b"
      aws s3 sync --only-show-errors "s3://$name" "$dest/$b"
    done
  fi

  echo "==> Terraform destroy"
  [ -d build/layer ] || ./scripts/build_layer.sh   # the plan zips the layer dir even when destroying
  "${TF[@]}" plan -destroy -input=false -out=tfplan
  "${TF[@]}" apply -input=false tfplan
else
  echo "==> No state bucket $STATE_BUCKET, skipping terraform destroy"
fi

echo "==> Lambda layer versions"
for v in $(aws lambda list-layer-versions --layer-name smartthumb-pillow \
             --query 'LayerVersions[].Version' --output text); do
  aws lambda delete-layer-version --layer-name smartthumb-pillow --version-number "$v"
done

echo "==> GitHub Actions role"
if aws iam get-role --role-name "$CI_ROLE" >/dev/null 2>&1; then
  for p in $(aws iam list-attached-role-policies --role-name "$CI_ROLE" --query 'AttachedPolicies[].PolicyArn' --output text); do
    aws iam detach-role-policy --role-name "$CI_ROLE" --policy-arn "$p"
  done
  for p in $(aws iam list-role-policies --role-name "$CI_ROLE" --query 'PolicyNames[]' --output text); do
    aws iam delete-role-policy --role-name "$CI_ROLE" --policy-name "$p"
  done
  aws iam delete-role --role-name "$CI_ROLE"
fi
# The OIDC provider is account-wide; only remove it if no other role still trusts it.
PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  if aws iam list-roles --output json | grep -q 'oidc-provider/token.actions.githubusercontent.com'; then
    echo "    keeping GitHub OIDC provider: other roles use it"
  else
    aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN"
  fi
fi
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh variable delete AWS_DEPLOY_ROLE_ARN 2>/dev/null || true
fi

echo "==> Terraform state bucket"
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  # Versioned bucket: every version and delete marker has to go before the bucket can.
  while :; do
    batch="$(aws s3api list-object-versions --bucket "$STATE_BUCKET" --max-items 1000 --output json \
      --query '{Objects: [Versions, DeleteMarkers][].{Key: Key, VersionId: VersionId}, Quiet: `true`}')"
    [[ "$batch" == *'"Key"'* ]] || break
    aws s3api delete-objects --bucket "$STATE_BUCKET" --delete "$batch" >/dev/null
  done
  aws s3api delete-bucket --bucket "$STATE_BUCKET"
fi
rm -f infra/tfplan

echo
echo "Done. Everything is deleted except the budget alert (aws budgets describe-budgets --account-id $ACCOUNT_ID)."
echo "Run scripts/setup.sh to bring it all back."
