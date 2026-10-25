variable "region" {
  description = "AWS region. eu-west-1 has Rekognition; af-south-1 does not."
  type        = string
  default     = "eu-west-1"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "smartthumb"
}

variable "enable_labels" {
  description = "Call Amazon Rekognition DetectLabels for each valid image (the AI extension)."
  type        = bool
  default     = true
}

variable "team_code" {
  description = "Shared code testers type into the web app. Leave empty to generate one (see `terraform output -raw team_code`)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "object_expiry_days" {
  description = "Uploaded originals, thumbnails and meta files are deleted after this many days."
  type        = number
  default     = 14
}

variable "extra_cors_origins" {
  description = "Extra browser origins allowed to upload to S3, e.g. [\"http://localhost:8000\"] for local UI work."
  type        = list(string)
  default     = []
}
