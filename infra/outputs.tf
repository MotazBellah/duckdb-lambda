output "buckets" {
  value = { for k, b in aws_s3_bucket.layer : k => b.bucket }
}
