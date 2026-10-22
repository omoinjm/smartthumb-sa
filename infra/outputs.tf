output "web_url" {
  description = "Live URL to share with the team (CloudFront, fastest)."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_url" {
  description = "Direct API Gateway URL (still works, slower from far away)."
  value       = aws_apigatewayv2_api.web.api_endpoint
}

output "team_code" {
  description = "Code testers enter in the web app."
  value       = local.team_code
  sensitive   = true
}

output "source_bucket" {
  value = aws_s3_bucket.source.id
}

output "output_bucket" {
  value = aws_s3_bucket.output.id
}

output "processor_function" {
  value = aws_lambda_function.processor.function_name
}

output "processor_log_group" {
  value = aws_cloudwatch_log_group.processor.name
}

output "api_log_group" {
  value = aws_cloudwatch_log_group.api.name
}

output "dashboard_url" {
  value = local.dashboard_url
}
