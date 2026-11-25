import os
from functools import cached_property

import boto3


class S3Resource:
    # Region and endpoint come from the environment (AWS_REGION, AWS_ENDPOINT_URL),
    # which boto3 reads on its own. Terraform sets them on the Lambda.
    @cached_property
    def client(self):
        return boto3.client("s3")

    def download(self, bucket: str, key: str, local_path: str) -> str:
        """Downloads s3://bucket/key to local_path and returns local_path."""
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        self.client.download_file(bucket, key, local_path)
        return local_path

    def upload(self, local_path: str, bucket: str, key: str) -> str:
        """Uploads local_path to s3://bucket/key and returns the s3 uri."""
        self.client.upload_file(local_path, bucket, key)
        return f"s3://{bucket}/{key}"
