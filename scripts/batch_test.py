"""Run every file in test_images/ through the LIVE pipeline (same path as the web app)
and write results/metrics.csv plus a summary against the proposal's targets.

    python scripts/batch_test.py --url https://xxxx.execute-api.eu-west-1.amazonaws.com --code TEAMCODE

Needs no AWS credentials, only the live URL and team code, so any teammate can run it.
"""

import argparse
import csv
import json
import mimetypes
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVALID_HINTS = ("fake", "corrupt", ".txt", ".gif", "empty")

# eu-west-1 list prices (USD), checked Oct 2026. Re-check on the AWS pricing pages before quoting.
PRICE = {
    "lambda_gb_s": 0.0000166667,
    "lambda_request": 0.20 / 1_000_000,
    "s3_put": 0.005 / 1000,
    "s3_get": 0.0004 / 1000,
    "rekognition_image": 0.001,
}
PROCESSOR_MEMORY_GB = 1.0


def api(base, code, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", "x-team-code": code},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def multipart(fields, filename, data, content_type):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode() + data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def run_one(base, code, tester, path):
    expected = "rejected" if any(h in path.name.lower() for h in INVALID_HINTS) else "ok"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    row = {"file": path.name, "source": path.parent.name, "expected": expected, "orig_bytes": len(data)}
    t0 = time.time()

    status, up = api(base, code, "POST", "/api/uploads",
                     {"filename": path.name, "content_type": content_type, "tester": tester})
    if status == 401:
        sys.exit("Team code rejected (401).")
    body, ctype = multipart(up["fields"], path.name, data, content_type)
    try:
        urllib.request.urlopen(urllib.request.Request(up["url"], data=body, method="POST",
                                                      headers={"content-type": ctype}), timeout=60)
    except urllib.error.HTTPError as exc:
        row.update(status="upload_refused", reason=f"S3 {exc.code}", passed=expected == "rejected")
        return row

    key = up["key"]
    meta = None
    while time.time() - t0 < 60:
        status, meta = api(base, code, "GET", "/api/results?key=" + urllib.parse.quote(key))
        if status == 200:
            break
        time.sleep(1)
    else:
        row.update(status="timeout", passed=False, key=key)
        return row

    row.update(
        key=key,
        status=meta["status"],
        reason=meta.get("reason", ""),
        end_to_end_s=round(time.time() - t0, 2),
        lambda_ms=meta.get("duration_ms"),
        labels_ms=meta.get("labels_ms"),
        orig_size=f"{meta.get('orig_width')}x{meta.get('orig_height')}" if meta["status"] == "ok" else "",
        thumb_size=f"{meta.get('thumb_width')}x{meta.get('thumb_height')}" if meta["status"] == "ok" else "",
        thumb_bytes=meta.get("thumb_bytes"),
        reduction_pct=meta.get("reduction_pct"),
        labels="; ".join(f"{l['name']} ({l['confidence']:.0f}%)" for l in meta.get("labels", [])),
        label_useful="",  # filled in by a human reviewer afterwards
    )
    ok_dims = meta["status"] != "ok" or max(meta["thumb_width"], meta["thumb_height"]) <= 300
    row["passed"] = meta["status"] == expected and ok_dims
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--tester", default="batch-test")
    ap.add_argument("--out", default=str(ROOT / "results" / "metrics.csv"))
    args = ap.parse_args()
    base = args.url.rstrip("/")

    files = sorted(p for p in (ROOT / "test_images").rglob("*") if p.is_file() and p.name != "README.md")
    if not files:
        sys.exit("No files in test_images/. Run `make images` and/or add photos to test_images/real/.")
    print(f"Uploading {len(files)} files to {base} ...")

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda p: run_one(base, args.code, args.tester, p), files))

    fields = ["file", "source", "expected", "status", "passed", "reason", "orig_bytes", "thumb_bytes", "reduction_pct",
              "orig_size", "thumb_size", "lambda_ms", "labels_ms", "end_to_end_s", "labels", "label_useful", "key"]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    for r in rows:
        mark = "PASS" if r.get("passed") else "FAIL"
        print(f"  {mark}  {r['file']:<34} {r.get('status', ''):<10} {r.get('thumb_size', ''):<9} "
              f"{r.get('reduction_pct') or '':>6}%  {r.get('lambda_ms') or '':>5} ms  {r.get('labels', '')[:50]}")

    valid = [r for r in rows if r["expected"] == "ok"]
    ok = [r for r in valid if r.get("status") == "ok"]
    invalid = [r for r in rows if r["expected"] == "rejected"]
    reductions = [r["reduction_pct"] for r in ok]
    durations = [r["lambda_ms"] for r in rows if r.get("lambda_ms") is not None]
    labelled = sum(1 for r in ok if r.get("labels_ms") is not None)

    per_image = (
        PRICE["lambda_request"]
        + (statistics.mean(durations) / 1000 if durations else 0) * PROCESSOR_MEMORY_GB * PRICE["lambda_gb_s"]
        + 3 * PRICE["s3_put"]  # original upload + thumbnail + meta
        + 4 * PRICE["s3_get"]  # processor read + UI polling/viewing (approx.)
        + (PRICE["rekognition_image"] if labelled else 0)
    )

    print("\nSummary (proposal targets in brackets)")
    print(f"  valid images processed ok : {len(ok)}/{len(valid)} = {len(ok) / max(len(valid), 1) * 100:.1f}%  [>= 95%]")
    print(f"  invalid files rejected    : {sum(r.get('passed', False) for r in invalid)}/{len(invalid)}  [all, no crash]")
    if reductions:
        print(f"  avg size reduction        : {statistics.mean(reductions):.1f}%  (median {statistics.median(reductions):.1f}%)  [>= 50%]")
    if durations:
        print(f"  lambda duration           : avg {statistics.mean(durations):.0f} ms, max {max(durations)} ms")
    print(f"  est. cost per 100 images  : ${per_image * 100:.4f}  (Free Tier ignored; labels {'on' if labelled else 'off'})")
    print(f"\nWrote {args.out}. Next: have a reviewer fill in 'label_useful' (y/n) to score the >= 80% target.")


if __name__ == "__main__":
    main()
