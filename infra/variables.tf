variable "region" {
  type    = string
  default = "us-east-1"
}

variable "floci_endpoint" {
  type    = string
  default = "http://localhost:4566"
}

variable "lambda_aws_endpoint_url" {
  description = "AWS_ENDPOINT_URL inside the Lambda container (Floci address as seen from that container, not localhost). Null on real AWS."
  type        = string
  default     = "http://host.docker.internal:4566"
}

variable "s3_key_id" {
  description = "S3_KEY_ID env var of the lambdas (DuckDB S3 secret)"
  type        = string
  default     = "test"
}

variable "s3_secret" {
  description = "S3_SECRET env var of the lambdas (DuckDB S3 secret)"
  type        = string
  default     = "test"
}

variable "s3_region" {
  description = "S3_REGION env var of the lambdas (DuckDB S3 secret)"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Prefix for bucket names"
  type        = string
  default     = "duckdb-demo"
}

variable "lambda_runtime" {
  description = "Must match PYTHON_VERSION in the Makefile"
  type        = string
  default     = "python3.13"
}

variable "lambda_architectures" {
  description = "Must match ARCH in the Makefile (arm64 or x86_64)"
  type        = list(string)
  default     = ["arm64"]
}

variable "layers" {
  description = "Data lake layers, one bucket each"
  type        = set(string)
  default     = ["landing", "staging", "curated"]
}

# --- signals memory scenario ------------------------------------------------
variable "signals_memory_size" {
  description = "Lambda memory (MB) of the signals function"
  type        = number
  default     = 4096
}

variable "signals_duckdb_memory_limit" {
  description = "DuckDB memory_limit inside the signals function (keep below signals_memory_size)"
  type        = string
  default     = "3GB"
}

variable "signals_row_group_size" {
  description = "Parquet ROW_GROUP_SIZE used by the signals COPY (DuckDB default is 122880)"
  type        = number
  default     = 100000
}
