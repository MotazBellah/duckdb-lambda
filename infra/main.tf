resource "aws_s3_bucket" "layer" {
  for_each      = var.layers
  bucket        = "${var.project}-${each.key}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "layer" {
  for_each = aws_s3_bucket.layer
  bucket   = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}
