data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------- processor: read originals, write thumbs/meta, optional Rekognition ----------
resource "aws_iam_role" "processor" {
  name               = "${local.processor_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "processor" {
  statement {
    sid       = "ReadUploads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.source.arn}/uploads/*"]
  }

  statement {
    sid     = "WriteResults"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.output.arn}/thumbs/*",
      "${aws_s3_bucket.output.arn}/meta/*",
    ]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }

  dynamic "statement" {
    for_each = var.enable_labels ? [1] : []
    content {
      sid       = "DetectLabels"
      actions   = ["rekognition:DetectLabels"]
      resources = ["*"] # DetectLabels does not support resource-level permissions
    }
  }
}

resource "aws_iam_role_policy" "processor" {
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}

# ---------- api: presign uploads/downloads, list results, record votes, read logs ----------
resource "aws_iam_role" "api" {
  name               = "${local.api_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "PresignUploadAndViewOriginals"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.source.arn}/uploads/*"]
  }

  statement {
    sid       = "ReadResults"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.output.arn}/thumbs/*", "${aws_s3_bucket.output.arn}/meta/*"]
  }

  statement {
    sid       = "RecordVotes"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.output.arn}/meta/*"]
  }

  statement {
    sid       = "ListResults"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.output.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["meta/", "meta/*"]
    }
  }

  statement {
    sid     = "ReadPipelineLogs"
    actions = ["logs:FilterLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.processor.arn}:*",
      "${aws_cloudwatch_log_group.api.arn}:*",
    ]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}
