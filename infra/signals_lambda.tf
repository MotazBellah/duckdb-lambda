# Signals handler: landing/signal_data/*.csv.gz -> staging/signals/*.parquet
# Invoked manually (no S3 trigger): a trigger would run it once per uploaded part.
#
# Reuses from stores_lambda.tf: local.landing_bucket, local.staging_bucket,
# data.archive_file.stores_handler (the zip holds the whole `duckdb_lambda_s3` package)
# and data.aws_iam_policy_document.lambda_assume.

# --- IAM --------------------------------------------------------------------
resource "aws_iam_role" "signals_handler" {
  name               = "${var.project}-signals-handler"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "signals_handler" {
  statement {
    sid       = "ListLanding" # list_objects_v2 needs the bucket ARN, not /*
    actions   = ["s3:ListBucket"]
    resources = [local.landing_bucket.arn]
  }

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

resource "aws_iam_role_policy" "signals_handler" {
  name   = "signals-handler"
  role   = aws_iam_role.signals_handler.id
  policy = data.aws_iam_policy_document.signals_handler.json
}

# --- Function ---------------------------------------------------------------
resource "aws_lambda_function" "signals_handler" {
  function_name = "${var.project}-signals-handler"
  role          = aws_iam_role.signals_handler.arn

  runtime       = var.lambda_runtime
  architectures = var.lambda_architectures
  handler       = "duckdb_lambda_s3.signals.signals_handler.handler"

  filename         = data.archive_file.stores_handler.output_path
  source_code_hash = data.archive_file.stores_handler.output_base64sha256
  layers           = [aws_lambda_layer_version.duckdb.arn]

  # Keep var.signals_duckdb_memory_limit below this, with headroom for the runtime.
  memory_size = var.signals_memory_size
  timeout     = 900 # 15 min is the Lambda maximum; measure and lower it later

  # Nothing is downloaded: DuckDB reads and writes S3 directly. /tmp is only spill space.
  ephemeral_storage {
    size = 2048
  }

  environment {
    variables = merge(
      local.s3_env,
      {
        LANDING_BUCKET = local.landing_bucket.bucket
        SIGNALS_PREFIX = "signal_data/"
        STAGING_BUCKET = local.staging_bucket.bucket
        STAGING_PREFIX = "signals/"

        DUCKDB_MEMORY_LIMIT = var.signals_duckdb_memory_limit
        ROW_GROUP_SIZE      = tostring(var.signals_row_group_size)
      },
      var.lambda_aws_endpoint_url == null ? {} : { AWS_ENDPOINT_URL = var.lambda_aws_endpoint_url },
    )
  }
}

output "signals_handler_arn" {
  value = aws_lambda_function.signals_handler.arn
}
