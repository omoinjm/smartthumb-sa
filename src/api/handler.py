"""RekogNail web API (API Gateway HTTP API, payload v2).

GET  /                 the single-page test app (no auth; the page asks for the team code)
GET  /api/config       labels toggle, dashboard link, limits
POST /api/uploads      presigned S3 POST for one file (size-limited by S3 itself)
GET  /api/results      ?key=... one result, otherwise the most recent results from everyone
POST /api/votes        {key, useful} -> stores a label-usefulness vote in the meta document
GET  /api/logs         recent CloudWatch log events for the processor/api functions
"""

import base64
import hmac
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "eu-west-1")
SOURCE_BUCKET = os.environ.get("SOURCE_BUCKET", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
TEAM_CODE = os.environ.get("TEAM_CODE", "")
LOG_GROUPS = {
    "processor": os.environ.get("PROCESSOR_LOG_GROUP", ""),
    "api": os.environ.get("API_LOG_GROUP", ""),
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
URL_TTL = 900

# Regional virtual-host endpoint: avoids the 307 redirect (which breaks browser CORS)
# that the global endpoint returns for freshly created buckets outside us-east-1.
s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
logs = boto3.client("logs", region_name=REGION)

INDEX_HTML = (Path(__file__).parent / "index.html").read_text()


def log(level, event, **fields):
    print(json.dumps({"level": level, "event": event, **fields}, default=str))


def respond(status, body, headers=None):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store", **(headers or {})},
        "body": json.dumps(body, default=str),
    }


def authorised(event):
    supplied = (event.get("headers") or {}).get("x-team-code", "")
    return bool(TEAM_CODE) and hmac.compare_digest(supplied.encode(), TEAM_CODE.encode())


def body_json(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    return json.loads(raw)


def clean(text, limit, fallback):
    text = re.sub(r"[^A-Za-z0-9._ -]", "", str(text or "")).strip()[:limit]
    return text or fallback


def presign_get(bucket, key):
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=URL_TTL)


def get_config(_event):
    return respond(200, {
        "labels_enabled": os.environ.get("ENABLE_LABELS", "false") == "true",
        "dashboard_url": os.environ.get("DASHBOARD_URL", ""),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "source_bucket": SOURCE_BUCKET,
        "output_bucket": OUTPUT_BUCKET,
        "region": REGION,
    })


def create_upload(event):
    payload = body_json(event)
    filename = clean(payload.get("filename"), 80, "upload.bin").replace(" ", "_")
    tester = clean(payload.get("tester"), 40, "anonymous")
    content_type = str(payload.get("content_type") or "application/octet-stream")[:100]
    # Deliberately no content-type allowlist: the test suite uploads invalid files on
    # purpose to prove the processor rejects them (FR7). S3 enforces the size limit.
    key = f"uploads/{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}/{filename}"
    post = s3.generate_presigned_post(
        Bucket=SOURCE_BUCKET,
        Key=key,
        Fields={"Content-Type": content_type, "x-amz-meta-tester": tester},
        Conditions=[
            {"Content-Type": content_type},
            {"x-amz-meta-tester": tester},
            ["content-length-range", 1, MAX_UPLOAD_BYTES],
        ],
        ExpiresIn=300,
    )
    log("INFO", "upload_url_issued", key=key, tester=tester, content_type=content_type)
    return respond(200, {"key": key, "url": post["url"], "fields": post["fields"]})


def load_meta(key):
    obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=f"meta/{key}.json")
    return json.loads(obj["Body"].read())


def with_urls(meta):
    meta["original_url"] = presign_get(SOURCE_BUCKET, meta["key"])
    if meta.get("thumb_key"):
        meta["thumb_url"] = presign_get(OUTPUT_BUCKET, meta["thumb_key"])
    return meta


def get_results(event):
    params = event.get("queryStringParameters") or {}
    key = params.get("key")
    if key:
        try:
            return respond(200, with_urls(load_meta(key)))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return respond(404, {"status": "pending", "key": key})
            raise

    limit = min(int(params.get("limit", "50")), 100)
    objects = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=OUTPUT_BUCKET, Prefix="meta/"):
        objects.extend(page.get("Contents", []))
    objects.sort(key=lambda o: o["LastModified"], reverse=True)
    keys = [o["Key"][len("meta/"):-len(".json")] for o in objects[:limit]]

    def fetch(k):
        try:
            return with_urls(load_meta(k))
        except Exception as exc:
            return {"key": k, "status": "unreadable", "reason": str(exc)}

    with ThreadPoolExecutor(max_workers=16) as pool:
        items = list(pool.map(fetch, keys))
    return respond(200, {"items": items, "total": len(objects)})


def add_vote(event):
    payload = body_json(event)
    key = str(payload.get("key", ""))
    if not key.startswith("uploads/"):
        return respond(400, {"error": "key must start with uploads/"})
    tester = clean(payload.get("tester"), 40, "anonymous")
    meta = load_meta(key)
    meta.setdefault("votes", {})[tester] = bool(payload.get("useful"))
    s3.put_object(Bucket=OUTPUT_BUCKET, Key=f"meta/{key}.json", Body=json.dumps(meta, indent=2).encode(),
                  ContentType="application/json")
    log("INFO", "label_vote", key=key, tester=tester, useful=meta["votes"][tester])
    return respond(200, {"votes": meta["votes"]})


def parse_line(message):
    message = message.strip()
    if message.startswith("{"):
        try:
            return json.loads(message)
        except ValueError:
            pass
    # Lambda platform lines: START / END / REPORT / INIT_START, or plain prints
    level = "ERROR" if re.search(r"error|exception|traceback|task timed out", message, re.I) else "INFO"
    if message.startswith("REPORT"):
        return {"level": "INFO", "event": "lambda_report", "message": message}
    return {"level": level, "event": "raw", "message": message}


def get_logs(event):
    params = event.get("queryStringParameters") or {}
    since = int(params.get("since") or (time.time() - 15 * 60) * 1000)
    source = params.get("source", "all")
    text = (params.get("filter") or "").replace('"', "")[:100]
    groups = {k: v for k, v in LOG_GROUPS.items() if v and source in ("all", k)}

    events = []
    for name, group in groups.items():
        kwargs = {"logGroupName": group, "startTime": since, "limit": 300}
        if text:
            kwargs["filterPattern"] = f'"{text}"'
        try:
            resp = logs.filter_log_events(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                continue
            raise
        for e in resp.get("events", []):
            entry = parse_line(e["message"])
            entry.update(source=name, ts=e["timestamp"], id=e["eventId"])
            events.append(entry)
    events.sort(key=lambda e: e["ts"])
    return respond(200, {"events": events[-400:], "now": int(time.time() * 1000)})


ROUTES = {
    ("GET", "/api/config"): get_config,
    ("POST", "/api/uploads"): create_upload,
    ("GET", "/api/results"): get_results,
    ("POST", "/api/votes"): add_vote,
    ("GET", "/api/logs"): get_logs,
}


def lambda_handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")

    if method == "GET" and path in ("/", "/index.html"):
        return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8",
                                                "cache-control": "no-store"}, "body": INDEX_HTML}

    route = ROUTES.get((method, path))
    if not route:
        return respond(404, {"error": f"no route {method} {path}"})
    if not authorised(event):
        log("WARN", "unauthorised", path=path, ip=event["requestContext"]["http"].get("sourceIp"))
        return respond(401, {"error": "missing or wrong team code"})

    try:
        return route(event)
    except Exception as exc:
        log("ERROR", "api_error", path=path, error=f"{type(exc).__name__}: {exc}",
            request_id=getattr(context, "aws_request_id", None))
        return respond(500, {"error": str(exc)})
