#!/usr/bin/env bash
# One command from an empty AWS account to a live RekogNail URL. Safe to re-run.
#
#   scripts/setup.sh [--email you@example.com] [--with-ci] [--no-labels]
#
#   --email      also create the account-level $5/month budget alert (scripts/budget.sh)
#   --with-ci    also set up GitHub Actions deploys (OIDC role + repo variable) and
#                re-enable the workflow; needs `gh` logged in with admin on the repo
#   --no-labels  skip Amazon Rekognition (thumbnails only, no per-image cost)
#
# Needs: AWS CLI v2 logged in (`aws login`), Terraform >= 1.10, python3 with pip.
# TF_VAR_team_code=... picks the team code; otherwise one is generated.
set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="" WITH_CI=0 LABELS=true
while [ $# -gt 0 ]; do
  case "$1" in
    --email) EMAIL="${2:?--email needs an address}"; shift 2 ;;
    --with-ci) WITH_CI=1; shift ;;
    --no-labels) LABELS=false; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

need() { command -v "$1" >/dev/null || { echo "missing: $1 ($2)" >&2; exit 1; }; }
need aws "https://aws.amazon.com/cli/"
need terraform "https://developer.hashicorp.com/terraform/install"
need python3 "Python 3.12+"
[ "$WITH_CI" = 1 ] && need gh "https://cli.github.com/"

# Terraform can't read `aws login` / SSO sessions, so hand it plain env credentials.
creds="$(aws configure export-credentials --format env 2>/dev/null)" \
  || { echo "Not logged in to AWS. Run: aws login" >&2; exit 1; }
eval "$creds"
export AWS_REGION="${AWS_REGION:-eu-west-1}"
echo "==> AWS account $(aws sts get-caller-identity --query Account --output text), region $AWS_REGION"

echo "==> Terraform state bucket"
./scripts/bootstrap_state.sh

echo "==> Pillow layer"
./scripts/build_layer.sh

echo "==> Terraform apply"
terraform -chdir=infra init -input=false -reconfigure -backend-config=backend.hcl >/dev/null
terraform -chdir=infra plan -input=false -var "enable_labels=$LABELS" -out=tfplan
terraform -chdir=infra apply -input=false tfplan

if [ -n "$EMAIL" ]; then
  echo "==> Budget alert"
  ./scripts/budget.sh "$EMAIL"
fi

if [ "$WITH_CI" = 1 ]; then
  echo "==> GitHub Actions"
  ./scripts/bootstrap_ci.sh
  gh workflow enable deploy.yml
fi

echo
echo "Live URL:  $(terraform -chdir=infra output -raw web_url)"
echo "Team code: $(terraform -chdir=infra output -raw team_code)"
echo "(CloudFront can take a few minutes to start serving on a fresh deploy.)"
