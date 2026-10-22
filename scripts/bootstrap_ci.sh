#!/usr/bin/env bash
# One-time setup for GitHub Actions deploys (run with admin AWS credentials):
#  1. registers GitHub's OIDC identity provider in the AWS account
#  2. creates an IAM role that only <repo>'s main branch can assume
#  3. stores the role ARN as the AWS_DEPLOY_ROLE_ARN GitHub Actions variable
# No long-lived AWS keys are stored in GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
ROLE="${ROLE:-github-deploy-smartthumb}"   # deliberately outside the smartthumb-* pattern it may manage
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
# Repos may use GitHub's immutable subject ("repo:owner@<id>/name@<id>"), so ask GitHub for the
# exact prefix its tokens will carry instead of assuming "repo:owner/name".
SUB_PREFIX="$(gh api "repos/${REPO}/actions/oidc/customization/sub" -q .sub_claim_prefix 2>/dev/null || true)"
SUB_PREFIX="${SUB_PREFIX:-repo:${REPO}}"

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
  echo "Created GitHub OIDC provider"
fi

TRUST=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "$PROVIDER_ARN" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "${SUB_PREFIX}:ref:refs/heads/main"
      }
    }
  }]
}
JSON
)

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
    --description "GitHub Actions deploys for ${REPO}" --max-session-duration 3600 >/dev/null
  echo "Created role $ROLE"
fi

# Everything except IAM/Organizations; IAM is limited to the project's own roles below.
aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/PowerUserAccess

aws iam put-role-policy --role-name "$ROLE" --policy-name smartthumb-iam --policy-document "$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageProjectRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
        "iam:UpdateRole", "iam:UpdateAssumeRolePolicy", "iam:PassRole",
        "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/smartthumb-*"
    }
  ]
}
JSON
)"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE}"
gh variable set AWS_DEPLOY_ROLE_ARN --repo "$REPO" --body "$ROLE_ARN"
echo "Done. $REPO main branch (${SUB_PREFIX}) can deploy as $ROLE_ARN"
