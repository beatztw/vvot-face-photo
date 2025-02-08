import base64
import json
import os

import boto3
import requests
from botocore.client import Config
from requests_auth_aws_sigv4 import AWSSigV4

ACCESS_TOKEN = os.environ["ACCESS_TOKEN"]
SECRET_KEY = os.environ["SECRET_KEY"]
QUEUE_URL_ENV = os.environ["QUEUE_URL"]

ENDPOINT = "https://storage.yandexcloud.net"
url_vision = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
url_queue = "https://message-queue.api.cloud.yandex.net"

session = boto3.Session(
    aws_access_key_id=ACCESS_TOKEN,
    aws_secret_access_key=SECRET_KEY,
    region_name="ru-central1",
)


def handler(event, context):
    access_token = context.token["access_token"]
    token_type = context.token["token_type"]

    s3 = session.client(
        "s3", endpoint_url=ENDPOINT, config=Config(signature_version="s3v4")
    )

    bucket_id = event["messages"][0]["details"]["bucket_id"]
    object_id = event["messages"][0]["details"]["object_id"]
    folder_id = event["messages"][0]["event_metadata"]["folder_id"]

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_id, "Key": object_id},
        ExpiresIn=100,
    )
    r = requests.get(url=url)

    headers = {
        "Authorization": f"{token_type} {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "folderId": folder_id,
        "analyze_specs": [{
            "content": base64.b64encode(r.content).decode(),
            "features": [{
                "type": "FACE_DETECTION"
            }]
        }]
    }

    r = requests.post(url=url_vision, headers=headers, data=json.dumps(data))

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    auth = AWSSigV4('sqs',
                    aws_access_key_id=ACCESS_TOKEN,
                    aws_secret_access_key=SECRET_KEY,
                    region="ru-central1")

    ss = r.json()
    faceDetection = ss["results"][0]["results"][0]["faceDetection"]

    if "faces" in faceDetection:
        for face in faceDetection["faces"]:
            message = {
                "key": object_id,
                "vertices": face["boundingBox"]["vertices"]
            }
            data = {
                "Action": "SendMessage",
                "MessageBody": json.dumps(message),
                "QueueUrl": QUEUE_URL_ENV,
            }
            requests.post(
                url_queue,
                headers=headers,
                auth=auth,
                data=data
            )

    return {
        'statusCode': 200,
    }
