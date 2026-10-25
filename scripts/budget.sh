#!/usr/bin/env bash
# Account-level monthly cost alert, kept outside Terraform on purpose so it survives
# scripts/teardown.sh and still catches anything left running. Safe to re-run.
#   scripts/budget.sh you@example.com [limit-usd]
set -euo pipefail

EMAIL="${1:?usage: $0 <email> [limit-usd]}"
LIMIT="${2:-${BUDGET_USD:-5}}"
NAME="smartthumb-monthly"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

notify() { # $1 = ACTUAL|FORECASTED, $2 = percent
  printf '{"Notification":{"NotificationType":"%s","ComparisonOperator":"GREATER_THAN","Threshold":%s,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"%s"}]}' \
    "$1" "$2" "$EMAIL"
}

# Recreate rather than diff the notifications: there is no history worth keeping.
aws budgets delete-budget --account-id "$ACCOUNT_ID" --budget-name "$NAME" >/dev/null 2>&1 || true
aws budgets create-budget --account-id "$ACCOUNT_ID" \
  --budget "{\"BudgetName\":\"$NAME\",\"BudgetType\":\"COST\",\"TimeUnit\":\"MONTHLY\",\"BudgetLimit\":{\"Amount\":\"$LIMIT\",\"Unit\":\"USD\"}}" \
  --notifications-with-subscribers "[$(notify ACTUAL 80),$(notify FORECASTED 100)]"

echo "Budget $NAME: \$$LIMIT/month, emails $EMAIL at 80% actual and 100% forecast"
