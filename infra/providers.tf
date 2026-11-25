provider "aws" {
  region     = var.region
  access_key = "test"
  secret_key = "test"

  # Point everything at Floci
  endpoints {
    s3     = var.floci_endpoint
    lambda = var.floci_endpoint
    iam    = var.floci_endpoint
    sts    = var.floci_endpoint
    logs   = var.floci_endpoint
  }

  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}
