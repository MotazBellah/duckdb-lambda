# Stores handler: landing/stores.csv -> staging/stores/*.parquet
# Invoked manually (no S3 trigger), like the other handlers.

locals {
  # Read by DuckDBResource to create the S3 secret.
  s3_env = {
    S3_KEY_ID = var.s3_key_id
    S3_SECRET = var.s3_secret
    S3_REGION = var.s3_region
  }

  landing_bucket = aws_s3_bucket.layer["landing"]
  staging_bucket = aws_s3_bucket.layer["staging"]
}

# --- Code package -----------------------------------------------------------
# Zips src/ so the archive contains the `duckdb_lambda_s3/` package at its root.
# Dependencies (duckdb) come from the layer; boto3 is in the Lambda runtime.
data "archive_file" "stores_handler" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/../build/stores_handler.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

# --- IAM --------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "stores_handler" {
  name               = "${var.project}-stores-handler"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "stores_handler" {
  statement {
    sid       = "ReadLanding"
    actions   = ["s3:GetObject"]
    resources = ["${local.landing_bucket.arn}/*"]
  }

  statement {
    sid       = "ListStaging" # DuckDB lists the target folder before writing
    actions   = ["s3:ListBucket"]
    resources = [local.staging_bucket.arn]
  }

  statement {
    sid       = "WriteStaging"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"] # DuckDB uploads in parts
    resources = ["${local.staging_bucket.arn}/*"]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:*"]
  }
}

resource "aws_iam_role_policy" "stores_handler" {
  name   = "stores-handler"
  role   = aws_iam_role.stores_handler.id
  policy = data.aws_iam_policy_document.stores_handler.json
}

# --- Function ---------------------------------------------------------------
resource "aws_lambda_function" "stores_handler" {
  function_name = "${var.project}-stores-handler"
  role          = aws_iam_role.stores_handler.arn

  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  handler       = "duckdb_lambda_s3.stores.stores_hanlder.handler" # sic: matches the filename

  filename         = data.archive_file.stores_handler.output_path
  source_code_hash = data.archive_file.stores_handler.output_base64sha256
  layers           = [aws_lambda_layer_version.duckdb.arn]

  # DuckDB is configured with memory_limit=1GB, so leave headroom above that.
  memory_size = 2048
  timeout     = 60

  environment {
    variables = merge(
      local.s3_env,
      {
        LANDING_BUCKET = local.landing_bucket.bucket
        STORES_KEY     = "stores.csv"
        STAGING_BUCKET = local.staging_bucket.bucket
        STAGING_PREFIX = "stores/"
      },
      # boto3 reads AWS_ENDPOINT_URL itself. Leave the variable null on real AWS.
      var.lambda_aws_endpoint_url == null ? {} : { AWS_ENDPOINT_URL = var.lambda_aws_endpoint_url },
    )
  }
}

output "stores_handler_arn" {
  value = aws_lambda_function.stores_handler.arn
}
