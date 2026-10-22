# Two private buckets. Writing thumbnails to a different bucket from the one that
# triggers the Lambda makes a recursive invocation loop impossible.

resource "aws_s3_bucket" "source" {
  bucket        = local.source_bucket
  force_destroy = true
}

resource "aws_s3_bucket" "output" {
  bucket        = local.output_bucket
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = { source = aws_s3_bucket.source.id, output = aws_s3_bucket.output.id }

  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = { source = aws_s3_bucket.source.id, output = aws_s3_bucket.output.id }

  bucket = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = { source = aws_s3_bucket.source.id, output = aws_s3_bucket.output.id }

  bucket = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = { source = aws_s3_bucket.source.id, output = aws_s3_bucket.output.id }

  bucket = each.value
  rule {
    id     = "expire-test-data"
    status = "Enabled"
    filter {}
    expiration {
      days = var.object_expiry_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Browsers upload directly to the source bucket with a presigned POST.
resource "aws_s3_bucket_cors_configuration" "source" {
  bucket = aws_s3_bucket.source.id

  cors_rule {
    allowed_methods = ["POST", "GET"]
    allowed_origins = concat([aws_apigatewayv2_api.web.api_endpoint], var.extra_cors_origins)
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_notification" "source" {
  bucket = aws_s3_bucket.source.id

  # No suffix filter on purpose: unsupported files are still delivered so the
  # processor can reject and log them (FR7) instead of silently ignoring them.
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}
