import boto3

AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"  # TODO: rotar
client = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY_ID)
