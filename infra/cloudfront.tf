# CloudFront in front of everything:
#   /thumbs/*  -> private output bucket via Origin Access Control, cached for a year (thumbnails never change)
#   /api/*     -> API Gateway, never cached, but served over warm edge-to-origin connections
#   /* (page)  -> API Gateway, cached briefly (the Lambda sends Cache-Control: max-age=60 + ETag)
# Viewers in South Africa connect to the Johannesburg/Cape Town edge instead of Ireland.

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_origin_access_control" "output" {
  name                              = "${var.name}-output"
  description                       = "CloudFront reads thumbnails from the private output bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  api_domain = replace(aws_apigatewayv2_api.web.api_endpoint, "https://", "")
}

resource "aws_cloudfront_distribution" "web" {
  enabled         = true
  comment         = "${var.name}: web app, API and thumbnails"
  http_version    = "http2and3"
  is_ipv6_enabled = true
  price_class     = "PriceClass_All" # includes the African edge locations

  origin {
    origin_id   = "api"
    domain_name = local.api_domain
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  origin {
    origin_id                = "thumbs"
    domain_name              = aws_s3_bucket.output.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.output.id
  }

  # The page: cached for the max-age the Lambda sends (60 s), compressed at the edge.
  default_cache_behavior {
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true
  }

  ordered_cache_behavior {
    path_pattern           = "/thumbs/*"
    target_origin_id       = "thumbs"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Only this distribution may read, and only thumbnails. Originals and meta files stay private.
data "aws_iam_policy_document" "output_cloudfront" {
  statement {
    sid       = "CloudFrontReadsThumbnails"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.output.arn}/thumbs/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "output" {
  bucket     = aws_s3_bucket.output.id
  policy     = data.aws_iam_policy_document.output_cloudfront.json
  depends_on = [aws_s3_bucket_public_access_block.this]
}
