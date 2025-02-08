import json
import os
import uuid

import boto3
import requests
import ydb
from PIL import Image
import io

from botocore.config import Config

ACCESS_TOKEN = os.environ["ACCESS_TOKEN"]
SECRET_KEY = os.environ["SECRET_KEY"]
PHOTO_BUCKET_ID = os.environ["PHOTO_BUCKET_ID"]
FACES_BUCKET_ID = os.environ["FACES_BUCKET_ID"]

ENDPOINT = "https://storage.yandexcloud.net"

session = boto3.Session(
        aws_access_key_id=ACCESS_TOKEN,
        aws_secret_access_key=SECRET_KEY,
        region_name="ru-central1",
    )


def handler(event, context):

    access_token = context.token["access_token"]
    driver = ydb.Driver(
        endpoint=f"grpcs://{os.environ['ENDPOINT']}",
        database=os.environ["DATABASE"],
        credentials=ydb.AccessTokenCredentials(access_token)
    )

    driver.wait(fail_fast=True, timeout=5)

    pool = ydb.SessionPool(driver)

    s3 = session.client(
        "s3", endpoint_url=ENDPOINT, config=Config(signature_version="s3v4")
    )

    gson = json.loads(event["messages"][0]["details"]["message"]["body"])

    object_id = gson["key"]
    vertices = gson["vertices"]

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": PHOTO_BUCKET_ID, "Key": object_id},
        ExpiresIn=100,
    )
    r = requests.get(url=url)

    image = Image.open(io.BytesIO(r.content))

    cropped_image = image.crop(
        (int(vertices[0]["x"]), int(vertices[0]["y"]), int(vertices[2]["x"]), int(vertices[2]["y"])))

    output = io.BytesIO()
    cropped_image.save(output, 'JPEG')
    output.seek(0)

    face_key = str(uuid.uuid4())
    s3.put_object(Bucket=FACES_BUCKET_ID, Key=face_key, Body=output, ContentType="image/jpeg")

    pool.retry_operation_sync(insert_data, None, face_key, object_id)

    return {
        'statusCode': 200,
    }


def insert_data(session, face_key, photo_key):
    query = f'insert into photos(face_key , photo_key) values ("{face_key}", "{photo_key}");'
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
