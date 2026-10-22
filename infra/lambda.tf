# Pillow layer: built by scripts/build_layer.sh into ../build/layer (python/ subdir).
data "archive_file" "pillow_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../build/layer"
  output_path = "${path.module}/../build/pillow-layer.zip"
}

resource "aws_lambda_layer_version" "pillow" {
  layer_name               = "${var.name}-pillow"
  filename                 = data.archive_file.pillow_layer.output_path
  source_code_hash         = data.archive_file.pillow_layer.output_base64sha256
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]
}

data "archive_file" "processor" {
  type        = "zip"
  source_file = "${path.module}/../src/processor/handler.py"
  output_path = "${path.module}/../build/processor.zip"
}

data "archive_file" "api" {
  type        = "zip"
  output_path = "${path.module}/../build/api.zip"

  source {
    content  = file("${path.module}/../src/api/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../web/index.html")
    filename = "index.html"
  }
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.processor_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.api_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "processor" {
  function_name    = local.processor_name
  description      = "S3 upload -> 300x300 thumbnail (+ optional Rekognition labels)"
  role             = aws_iam_role.processor.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256
  layers           = [aws_lambda_layer_version.pillow.arn]
  memory_size      = 1024
  timeout          = 30

  # No reserved concurrency: new accounts have a 10-execution limit, which already
  # caps parallel processing; API throttling limits upload volume.

  environment {
    variables = {
      OUTPUT_BUCKET  = aws_s3_bucket.output.id
      ENABLE_LABELS  = tostring(var.enable_labels)
      MAX_LABELS     = "10"
      MIN_CONFIDENCE = "70"
    }
  }

  depends_on = [aws_cloudwatch_log_group.processor, aws_iam_role_policy.processor]
}

resource "aws_lambda_permission" "s3_invoke" {
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.processor.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.source.arn
  source_account = local.account_id
}

resource "aws_lambda_function" "api" {
  function_name    = local.api_name
  description      = "SmartThumb web app + API (presigned uploads, results, logs)"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 20

  environment {
    variables = {
      SOURCE_BUCKET       = aws_s3_bucket.source.id
      OUTPUT_BUCKET       = aws_s3_bucket.output.id
      TEAM_CODE           = local.team_code
      ENABLE_LABELS       = tostring(var.enable_labels)
      PROCESSOR_LOG_GROUP = aws_cloudwatch_log_group.processor.name
      API_LOG_GROUP       = aws_cloudwatch_log_group.api.name
      DASHBOARD_URL       = local.dashboard_url
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}
