# Built by `make layer` from the `lambda` dependency group in pyproject.toml.
locals {
  layer_zip = "${path.module}/../layer/dist/duckdb-layer.zip"
}

resource "aws_lambda_layer_version" "duckdb" {
  layer_name               = "${var.project}-duckdb"
  description              = "DuckDB dependencies for the data lake lambdas"
  filename                 = local.layer_zip
  source_code_hash         = filebase64sha256(local.layer_zip)
  compatible_runtimes      = [var.lambda_runtime]
  compatible_architectures = var.lambda_architectures
}

output "duckdb_layer_arn" {
  value = aws_lambda_layer_version.duckdb.arn
}
