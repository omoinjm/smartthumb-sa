"""RekogNail web API (API Gateway HTTP API, payload v2).

GET  /                 the single-page test app (no auth; the page asks for the team code)
GET  /api/config       labels toggle, dashboard link, limits
POST /api/uploads      presigned S3 POST for one file (size-limited by S3 itself)
GET  /api/results      ?key=... one result, otherwise a page of the newest results from everyone
                       (?offset=&limit=&status=&tester=) plus a summary over all results
GET  /api/original     ?key=... short-lived link to an original upload (private bucket)
POST /api/votes        {key, useful} -> stores a label-usefulness vote in the meta document
GET  /api/logs         recent CloudWatch log events for the processor/api functions
"""

import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

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
# Thumbnails are served by CloudFront (cached at the edge and in browsers); fall back to
# presigned S3 links when no distribution is configured.
THUMB_BASE_URL = os.environ.get("THUMB_BASE_URL", "").rstrip("/")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
URL_TTL = 900
GZIP_MIN_BYTES = 1024

# Regional virtual-host endpoint: avoids the 307 redirect (which breaks browser CORS)
# that the global endpoint returns for freshly created buckets outside us-east-1.
s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
logs = boto3.client("logs", region_name=REGION)

# Packaged next to the handler in Lambda; read from web/ when running tests locally.
_HERE = Path(__file__).parent
INDEX_HTML = next(p for p in (_HERE / "index.html", _HERE.parents[1] / "web" / "index.html") if p.exists()).read_text()
INDEX_ETAG = '"' + hashlib.sha256(INDEX_HTML.encode()).hexdigest()[:16] + '"'

# Meta documents keyed by results key -> (S3 ETag, parsed meta). Survives between invocations
# while the Lambda stays warm, so the gallery only downloads documents that are new or changed.
META_CACHE = {}


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
    meta = json.loads(obj["Body"].read())
    META_CACHE[key] = (obj["ETag"], meta)
    return meta


def thumb_url(meta):
    if not meta.get("thumb_key"):
        return None
    if THUMB_BASE_URL:
        return f"{THUMB_BASE_URL}/{quote(meta['thumb_key'])}"
    return presign_get(OUTPUT_BUCKET, meta["thumb_key"])


def with_urls(meta):
    meta = dict(meta)
    meta["original_url"] = presign_get(SOURCE_BUCKET, meta["key"])
    meta["thumb_url"] = thumb_url(meta)
    return meta


# Only what a gallery card needs; keeps the list response small on slow connections.
CARD_FIELDS = ("key", "status", "reason", "tester", "processed_at", "thumb_width", "thumb_height",
               "reduction_pct", "duration_ms", "labels_status", "labels_error", "votes")


def card(meta):
    item = {f: meta.get(f) for f in CARD_FIELDS if meta.get(f) is not None}
    item["labels"] = [{"name": l["name"], "confidence": l["confidence"]} for l in meta.get("labels", [])]
    item["thumb_url"] = thumb_url(meta)
    return item


def all_metas():
    """Every meta document, newest upload first, downloading only new or changed ones."""
    objects = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=OUTPUT_BUCKET, Prefix="meta/"):
        objects.extend(page.get("Contents", []))
    current = {o["Key"][len("meta/"):-len(".json")]: o["ETag"] for o in objects}
    stale = [k for k, etag in current.items() if META_CACHE.get(k, (None,))[0] != etag]

    def fetch(k):
        try:
            load_meta(k)
        except Exception as exc:
            META_CACHE[k] = (None, {"key": k, "status": "unreadable", "reason": str(exc)})

    if stale:
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(fetch, stale))
    for gone in set(META_CACHE) - set(current):
        META_CACHE.pop(gone, None)
    # Keys embed the upload time (uploads/YYYYmmdd-HHMMSS-id/...), so key order = upload order
    # and an item does not jump to the top when someone votes on it.
    return [META_CACHE[k][1] for k in sorted(current, reverse=True)], len(stale)


def summarise(metas):
    ok = [m for m in metas if m.get("status") == "ok"]
    errors = sum(1 for m in metas if m.get("status") == "error")
    votes = [v for m in metas for v in (m.get("votes") or {}).values()]
    return {
        "total": len(metas),
        "ok": len(ok),
        "rejected": sum(1 for m in metas if m.get("status") == "rejected"),
        "errors": errors,
        "success_pct": round(len(ok) / (len(ok) + errors) * 100, 1) if ok or errors else None,
        "avg_reduction_pct": round(sum(m["reduction_pct"] for m in ok) / len(ok), 1) if ok else None,
        "votes_up": sum(1 for v in votes if v),
        "votes_total": len(votes),
    }


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

    limit = max(1, min(int(params.get("limit", "24")), 100))
    offset = max(0, int(params.get("offset", "0")))
    metas, fetched = all_metas()
    matched = [
        m for m in metas
        if (not params.get("status") or m.get("status") == params["status"])
        and (not params.get("tester") or m.get("tester") == params["tester"])
    ]
    page = matched[offset:offset + limit]
    next_offset = offset + limit if offset + limit < len(matched) else None
    log("INFO", "results_listed", total=len(metas), fetched_from_s3=fetched, returned=len(page))
    return respond(200, {
        "items": [card(m) for m in page],
        "total": len(metas),
        "matched": len(matched),
        "next_offset": next_offset,
        "summary": summarise(metas),
    })


def get_original(event):
    key = (event.get("queryStringParameters") or {}).get("key", "")
    if not key.startswith("uploads/"):
        return respond(400, {"error": "key must start with uploads/"})
    return respond(200, {"url": presign_get(SOURCE_BUCKET, key)})


def add_vote(event):
    payload = body_json(event)
    key = str(payload.get("key", ""))
    if not key.startswith("uploads/"):
        return respond(400, {"error": "key must start with uploads/"})
    tester = clean(payload.get("tester"), 40, "anonymous")
    meta = load_meta(key)
    meta.setdefault("votes", {})[tester] = bool(payload.get("useful"))
    put = s3.put_object(Bucket=OUTPUT_BUCKET, Key=f"meta/{key}.json", Body=json.dumps(meta, indent=2).encode(),
                        ContentType="application/json")
    META_CACHE[key] = (put["ETag"], meta)
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
    ("GET", "/api/original"): get_original,
    ("POST", "/api/votes"): add_vote,
    ("GET", "/api/logs"): get_logs,
}


def compress(event, response):
    """gzip text responses when the client accepts it (the link to Ireland is the slow part)."""
    body = response.get("body")
    accepts = (event.get("headers") or {}).get("accept-encoding", "")
    if not body or response.get("isBase64Encoded") or "gzip" not in accepts or len(body) < GZIP_MIN_BYTES:
        return response
    response["body"] = base64.b64encode(gzip.compress(body.encode(), compresslevel=6)).decode()
    response["isBase64Encoded"] = True
    response["headers"] = {**response.get("headers", {}), "content-encoding": "gzip", "vary": "accept-encoding"}
    return response


def serve_page(event):
    # Short shared cache: CloudFront and browsers reuse the page for a minute, then revalidate
    # with the ETag, so a deploy shows up within ~60 s without re-downloading unchanged HTML.
    headers = {"content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=60",
               "etag": INDEX_ETAG}
    if (event.get("headers") or {}).get("if-none-match") == INDEX_ETAG:
        return {"statusCode": 304, "headers": headers, "body": ""}
    return {"statusCode": 200, "headers": headers, "body": INDEX_HTML}


def lambda_handler(event, context):
    return compress(event, route_request(event, context))


def route_request(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")

    if method == "GET" and path in ("/", "/index.html"):
        return serve_page(event)

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
