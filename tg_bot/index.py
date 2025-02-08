import json
import os

import boto3
import requests
import ydb
from botocore.config import Config

PHOTO_BUCKET_ID = os.environ["PHOTO_BUCKET_ID"]
GATEWAY_URL = os.environ["GATEWAY_URL"]
TG_BOT_KEY = os.environ["TG_BOT_KEY"]
YDB_ENDPOINT = os.environ['ENDPOINT']
YDB_NAME = os.environ["DATABASE"]
ACCESS_TOKEN = os.environ["ACCESS_TOKEN"]
SECRET_KEY = os.environ["SECRET_KEY"]

ENDPOINT = "https://storage.yandexcloud.net"
HELP_TEXT = "Привет, я умею:\n/getface - отправлять лицо, которое не определено в бд\n/find <name> - отправлять оргинальные фотографии, с данным именем"
BAD_TEXT = "Нет не определенных имен"
ERROR_TEXT = "Произошла Ошибка"
SUCESS_TEXT = "Имя успешно добавлено"
WARNING_TEXT = "Имя уже существует"

session = boto3.Session(
        aws_access_key_id=ACCESS_TOKEN,
        aws_secret_access_key=SECRET_KEY,
        region_name="ru-central1",
    )


def handler(event, context):
    driver = ydb.Driver(
        endpoint=f"grpcs://{YDB_ENDPOINT}",
        database=YDB_NAME,
        credentials=ydb.AccessTokenCredentials(context.token["access_token"])
    )

    driver.wait(fail_fast=True, timeout=5)

    pool = ydb.SessionPool(driver)

    update = json.loads(event["body"])
    if not "message" in update:
        return
    message = update["message"]
    chat_id = message["chat"]["id"]
    action = "sendMessage"
    params = {"chat_id": chat_id}
    files = []

    s3 = session.client(
        "s3", endpoint_url=ENDPOINT, config=Config(signature_version="s3v4")
    )

    if "text" in message:
        text = message["text"].lower()
        if text == "/start":
            params["text"] = (HELP_TEXT)
        elif text == "/getface":
            r = pool.retry_operation_sync(select_face_witout_name)
            if len(r[0].rows) == 0:
                params["text"] = BAD_TEXT
            else:
                action = "sendPhoto"
                params[
                    "photo"] = f"{GATEWAY_URL}?face={r[0].rows[0]['face_key'].decode()}"
                params["caption"] = r[0].rows[0]['face_key'].decode()
                params["protect_content"] = True
        elif text.startswith("/find "):
            face_name = text[6:]
            r = pool.retry_operation_sync(select_photo_keys_by_face_name, None, face_name)
            if len(r[0].rows) == 0:
                params["text"] = f"Фотографии с {face_name} не найдены"
            else:
                action = "sendMediaGroup"
                params["media"] = []
                for row in r[0].rows:
                    url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": PHOTO_BUCKET_ID, "Key": row["photo_key"].decode()},
                        ExpiresIn=100,
                    )
                    r = requests.get(url=url)
                    files.append((row["photo_key"], r.content))
                    params["media"].append({
                        "type": "photo",
                        "media": f"attach://{row['photo_key'].decode()}"
                    })
                params["media"] = json.dumps(params["media"])

        elif "reply_to_message" in message:
            replied_message = message["reply_to_message"]
            if replied_message["from"]["is_bot"] and "photo" in replied_message:
                face_key = message["reply_to_message"]["caption"]
                r = pool.retry_operation_sync(select_face_name_by_face_key, None, face_key)
                if len(r[0].rows) == 0:
                    params["text"] = ERROR_TEXT
                else:
                    if r[0].rows[0]["face_name"] is None:
                        pool.retry_operation_sync(update_face_name, None, face_key, text)
                        params["text"] = SUCESS_TEXT
                    else:
                        params["text"] = WARNING_TEXT
            else:
                params["text"] = ERROR_TEXT
        else:
            params["text"] = ERROR_TEXT
    else:
        params["text"] = ERROR_TEXT

    url = f"https://api.telegram.org/bot{TG_BOT_KEY}/{action}"
    requests.get(url=url, params=params, files=files)
    return {
        'statusCode': 200,
    }


def select_face_witout_name(session):
    query = f'select face_key from photos where face_name is null limit 1;'
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def select_face_name_by_face_key(session, face_key):
    query = f'select face_name from photos where face_key = "{face_key}";'
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def select_photo_keys_by_face_name(session, face_name):
    query = f'select photo_key from photos where face_name = "{face_name}" group by photo_key;'
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def update_face_name(session, face_key, face_name):
    query = f'update photos set face_name = "{face_name}" where face_key = "{face_key}";'
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
