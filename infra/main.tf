data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

resource "random_password" "team_code" {
  length  = 10
  special = false
}

locals {
  suffix         = random_id.suffix.hex
  account_id     = data.aws_caller_identity.current.account_id
  source_bucket  = "${var.name}-source-${local.suffix}"
  output_bucket  = "${var.name}-output-${local.suffix}"
  processor_name = "${var.name}-processor"
  api_name       = "${var.name}-api"
  team_code      = var.team_code != "" ? var.team_code : random_password.team_code.result
  dashboard_url  = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${var.name}"
}
