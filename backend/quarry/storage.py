from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from quarry.config import settings


@lru_cache
def client():
    cfg = settings()
    return boto3.client(
        "s3",
        endpoint_url=cfg.s3_endpoint,
        aws_access_key_id=cfg.s3_access_key,
        aws_secret_access_key=cfg.s3_secret_key,
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=15,
            retries={"max_attempts": 2},
        ),
    )


def init_storage():
    try:
        client().head_bucket(Bucket=settings().s3_bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
            raise
        client().create_bucket(Bucket=settings().s3_bucket)


def put(key: str, content: bytes, media_type: str):
    client().put_object(
        Bucket=settings().s3_bucket,
        Key=key,
        Body=content,
        ContentType=media_type,
    )


def get(key: str) -> bytes:
    response = client().get_object(Bucket=settings().s3_bucket, Key=key)
    try:
        return response["Body"].read(settings().max_upload_bytes + 1)
    finally:
        response["Body"].close()


def remove(key: str):
    client().delete_object(Bucket=settings().s3_bucket, Key=key)
