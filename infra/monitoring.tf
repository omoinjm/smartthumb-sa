resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title  = "Processor invocations / errors / throttles"
          region = var.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", local.processor_name],
            [".", "Errors", ".", "."],
            [".", "Throttles", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title  = "Processor duration (ms)"
          region = var.region
          period = 60
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", local.processor_name, { stat = "p50", label = "p50" }],
            ["...", { stat = "p95", label = "p95" }],
            ["...", { stat = "Maximum", label = "max" }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title  = "Web API requests / 4xx / 5xx"
          region = var.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.web.id],
            [".", "4xx", ".", "."],
            [".", "5xx", ".", "."],
          ]
        }
      },
      {
        type = "log", x = 0, y = 6, width = 12, height = 8
        properties = {
          title  = "Processing outcomes (last results)"
          region = var.region
          query  = "SOURCE '${aws_cloudwatch_log_group.processor.name}' | filter event = 'processed' | fields @timestamp, status, key, tester, duration_ms, reduction_pct, thumb, reason | sort @timestamp desc | limit 50"
          view   = "table"
        }
      },
      {
        type = "log", x = 12, y = 6, width = 12, height = 8
        properties = {
          title  = "Status counts and average duration"
          region = var.region
          query  = "SOURCE '${aws_cloudwatch_log_group.processor.name}' | filter event = 'processed' | stats count(*) as files, avg(duration_ms) as avg_ms, avg(reduction_pct) as avg_reduction by status"
          view   = "table"
        }
      },
      {
        type = "log", x = 0, y = 14, width = 24, height = 6
        properties = {
          title  = "Warnings and errors (both functions)"
          region = var.region
          query  = "SOURCE '${aws_cloudwatch_log_group.processor.name}' | SOURCE '${aws_cloudwatch_log_group.api.name}' | filter level in ['WARN', 'ERROR'] or @message like /(?i)(error|exception|timed out)/ | fields @timestamp, @log, event, key, reason, error, @message | sort @timestamp desc | limit 50"
          view   = "table"
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "processor_errors" {
  alarm_name          = "${local.processor_name}-errors"
  alarm_description   = "Processor Lambda threw unhandled errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = local.processor_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_budgets_budget" "monthly" {
  count = var.budget_email != "" ? 1 : 0

  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
