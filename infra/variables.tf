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
