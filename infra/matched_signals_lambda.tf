# Matched signals handler: staging/{stores,signals}/*.parquet -> curated/matched_signals/
# Invoked manually (no S3 trigger). Run the stores and signals handlers first.
#
# Reuses from stores_lambda.tf: local.staging_bucket, data.archive_file.stores_handler
# and data.aws_iam_policy_document.lambda_assume.

locals {
  curated_bucket = aws_s3_bucket.layer["curated"]
}

# --- IAM --------------------------------------------------------------------
resource "aws_iam_role" "matched_signals_handler" {
  name               = "${var.project}-matched-signals-handler"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "matched_signals_handler" {
  statement {
    sid       = "ListStaging" # list_objects_v2 needs the bucket ARN, not /*
    actions   = ["s3:ListBucket"]
    resources = [local.staging_bucket.arn]
  }

  statement {
    sid       = "ReadStaging"
    actions   = ["s3:GetObject"]
    resources = ["${local.staging_bucket.arn}/*"]
  }

  statement {
    sid       = "WriteCurated"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"] # DuckDB uploads in parts
    resources = ["${local.curated_bucket.arn}/*"]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:*"]
  }
}

resource "aws_iam_role_policy" "matched_signals_handler" {
  name   = "matched-signals-handler"
  role   = aws_iam_role.matched_signals_handler.id
  policy = data.aws_iam_policy_document.matched_signals_handler.json
}

# --- Function ---------------------------------------------------------------
resource "aws_lambda_function" "matched_signals_handler" {
  function_name = "${var.project}-matched-signals-handler"
  role          = aws_iam_role.matched_signals_handler.arn

  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  handler       = "duckdb_lambda_s3.matched_signals.matched_signals_handler.handler"

  filename         = data.archive_file.stores_handler.output_path
  source_code_hash = data.archive_file.stores_handler.output_base64sha256
  layers           = [aws_lambda_layer_version.duckdb.arn]

  # DuckDB memory_limit is 3GB; leave headroom above it.
  memory_size = 4096
  timeout     = 900

  # Nothing is downloaded: DuckDB reads and writes S3 directly. /tmp is only spill space.
  ephemeral_storage {
    size = 2048
  }

  environment {
    variables = merge(
      local.s3_env,
      {
        STAGING_BUCKET = local.staging_bucket.bucket
        STORES_PREFIX  = "stores/"
        SIGNALS_PREFIX = "signals/"
        CURATED_BUCKET = local.curated_bucket.bucket
        CURATED_KEY    = "matched_signals/matched_signals.parquet"
      },
      var.lambda_aws_endpoint_url == null ? {} : { AWS_ENDPOINT_URL = var.lambda_aws_endpoint_url },
    )
  }
}

output "matched_signals_handler_arn" {
  value = aws_lambda_function.matched_signals_handler.arn
}
