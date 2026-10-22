"""RekogNail processor.

Triggered by S3 ObjectCreated events on the source bucket (prefix uploads/).
For each object: validate, create a <=300x300 thumbnail, optionally ask
Rekognition for labels, then write the thumbnail and a meta JSON document to
the output bucket. Every record is handled independently so one bad file never
fails the whole invocation (FR7).
"""

import io
import json
import os
import time
import urllib.parse

from PIL import Image, ImageOps, UnidentifiedImageError

THUMB_SIZE = (300, 300)
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_FORMATS = {"JPEG", "PNG"}
JPEG_QUALITY = 85

# Guard against decompression bombs: refuse anything above ~40 megapixels.
Image.MAX_IMAGE_PIXELS = 40_000_000

_s3 = None
_rekognition = None


class Rejected(Exception):
    """A file we deliberately refuse to process (bad type, too big, corrupt)."""


def s3():
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def rekognition():
    global _rekognition
    if _rekognition is None:
        import boto3

        _rekognition = boto3.client("rekognition")
    return _rekognition


def log(level, event, **fields):
    """One JSON line per log entry so the web Logs tab and Logs Insights can filter."""
    print(json.dumps({"level": level, "event": event, **fields}, default=str))


def check_extension(key):
    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise Rejected(f"unsupported file extension '{ext or '(none)'}'")


def make_thumbnail(data):
    """Return (thumb_bytes, info) for raw image bytes, or raise Rejected.

    Decides format from the file content, not the extension, so a text file
    renamed to .jpg is still rejected.
    """
    if not data:
        raise Rejected("empty file")
    if len(data) > MAX_BYTES:
        raise Rejected(f"file is {len(data)} bytes; limit is {MAX_BYTES}")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise Rejected(f"image too large in pixels: {exc}") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise Rejected(f"not a readable image: {str(exc).split(' <')[0]}") from exc

    if img.format not in ALLOWED_FORMATS:
        raise Rejected(f"unsupported image format '{img.format}'")

    source_format = img.format
    img = ImageOps.exif_transpose(img)
    orig_w, orig_h = img.size
    img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    out = io.BytesIO()
    if source_format == "PNG" and has_alpha:
        out_format, content_type = "PNG", "image/png"
        img.save(out, "PNG", optimize=True)
    else:
        out_format, content_type = "JPEG", "image/jpeg"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)

    thumb = out.getvalue()
    return thumb, {
        "source_format": source_format,
        "thumb_format": out_format,
        "content_type": content_type,
        "orig_width": orig_w,
        "orig_height": orig_h,
        "thumb_width": img.width,
        "thumb_height": img.height,
    }


def thumb_key_for(key, thumb_format):
    base = os.path.splitext(key)[0]
    return f"thumbs/{base}.{'png' if thumb_format == 'PNG' else 'jpg'}"


def meta_key_for(key):
    return f"meta/{key}.json"


def detect_labels(bucket, key):
    resp = rekognition().detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=int(os.environ.get("MAX_LABELS", "10")),
        MinConfidence=float(os.environ.get("MIN_CONFIDENCE", "70")),
    )
    return [
        {
            "name": label["Name"],
            "confidence": round(label["Confidence"], 1),
            "categories": [c["Name"] for c in label.get("Categories", [])],
        }
        for label in resp.get("Labels", [])
    ]


def process_record(record, request_id):
    started = time.perf_counter()
    bucket = record["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
    output_bucket = os.environ["OUTPUT_BUCKET"]
    labels_enabled = os.environ.get("ENABLE_LABELS", "false").lower() == "true"

    meta = {
        "key": key,
        "source_bucket": bucket,
        "request_id": request_id,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_time": record.get("eventTime"),
        "labels_enabled": labels_enabled,
        "votes": {},
    }
    log("INFO", "received", key=key, bucket=bucket, size=record["s3"]["object"].get("size"),
        request_id=request_id)

    try:
        check_extension(key)
        obj = s3().get_object(Bucket=bucket, Key=key)
        meta["tester"] = obj.get("Metadata", {}).get("tester", "unknown")
        data = obj["Body"].read()
        meta["orig_bytes"] = len(data)

        thumb, info = make_thumbnail(data)
        meta.update(info)
        thumb_key = thumb_key_for(key, info["thumb_format"])
        s3().put_object(
            Bucket=output_bucket,
            Key=thumb_key,
            Body=thumb,
            ContentType=info["content_type"],
            # Each upload gets a unique key, so its thumbnail never changes: let CloudFront
            # and browsers keep it for a year.
            CacheControl="public, max-age=31536000, immutable",
            Metadata={"source-key": urllib.parse.quote(key)},
        )
        meta.update(
            thumb_key=thumb_key,
            thumb_bytes=len(thumb),
            reduction_pct=round((len(data) - len(thumb)) / len(data) * 100, 1),
        )

        if labels_enabled:
            label_started = time.perf_counter()
            try:
                meta["labels"] = detect_labels(bucket, key)
                meta["labels_status"] = "ok"
            except Exception as exc:  # labels are optional; never fail the thumbnail for them
                meta["labels"] = []
                meta["labels_status"] = "error"
                meta["labels_error"] = str(exc)
                log("WARN", "labels_failed", key=key, error=str(exc), request_id=request_id)
            meta["labels_ms"] = round((time.perf_counter() - label_started) * 1000)
        else:
            meta["labels"] = []
            meta["labels_status"] = "disabled"

        meta["status"] = "ok"
    except Rejected as exc:
        meta.update(status="rejected", reason=str(exc))
    except Exception as exc:
        meta.update(status="error", reason=f"{type(exc).__name__}: {exc}")

    meta["duration_ms"] = round((time.perf_counter() - started) * 1000)
    meta.setdefault("tester", "unknown")

    s3().put_object(
        Bucket=output_bucket,
        Key=meta_key_for(key),
        Body=json.dumps(meta, indent=2).encode(),
        ContentType="application/json",
    )

    level = {"ok": "INFO", "rejected": "WARN"}.get(meta["status"], "ERROR")
    log(
        level,
        "processed",
        key=key,
        tester=meta["tester"],
        status=meta["status"],
        reason=meta.get("reason"),
        duration_ms=meta["duration_ms"],
        orig_bytes=meta.get("orig_bytes"),
        thumb_bytes=meta.get("thumb_bytes"),
        reduction_pct=meta.get("reduction_pct"),
        thumb=f"{meta.get('thumb_width')}x{meta.get('thumb_height')}" if meta["status"] == "ok" else None,
        labels=[l["name"] for l in meta.get("labels", [])],
        request_id=request_id,
    )
    return meta


def lambda_handler(event, context):
    request_id = getattr(context, "aws_request_id", "local")
    results = []
    for record in event.get("Records", []):
        if not record.get("s3"):
            continue
        try:
            meta = process_record(record, request_id)
            results.append({"key": meta["key"], "status": meta["status"]})
        except Exception as exc:  # e.g. could not even write the meta file
            log("ERROR", "unhandled", error=f"{type(exc).__name__}: {exc}", request_id=request_id,
                record_key=record.get("s3", {}).get("object", {}).get("key"))
            results.append({"key": record["s3"]["object"].get("key"), "status": "error"})
    return {"results": results}
