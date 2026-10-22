import base64
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

API_HANDLER = Path(__file__).resolve().parents[1] / "src" / "api" / "handler.py"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("SOURCE_BUCKET", "src")
    monkeypatch.setenv("OUTPUT_BUCKET", "out")
    monkeypatch.setenv("TEAM_CODE", "code")
    monkeypatch.setenv("THUMB_BASE_URL", "https://cdn.example")
    # Both Lambdas are called handler.py, so load this one under its own module name.
    spec = importlib.util.spec_from_file_location("api_handler", API_HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.s3 = FakeS3()
    return mod


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakePaginator:
    def __init__(self, s3):
        self.s3 = s3

    def paginate(self, Bucket, Prefix):
        yield {"Contents": [{"Key": k, "ETag": v[0]} for k, v in self.s3.objects.items() if k.startswith(Prefix)]}


class FakeS3:
    def __init__(self):
        self.objects = {}  # key -> (etag, bytes)
        self.gets = 0

    def add(self, key, meta, etag="e1"):
        self.objects[f"meta/{key}.json"] = (etag, json.dumps(meta).encode())

    def get_paginator(self, name):
        return FakePaginator(self)

    def get_object(self, Bucket, Key):
        self.gets += 1
        etag, data = self.objects[Key]
        return {"ETag": etag, "Body": FakeBody(data)}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = ("e-new", Body)
        return {"ETag": "e-new"}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Bucket']}/{Params['Key']}"


def event(path, method="GET", query=None, headers=None, body=None):
    h = {"x-team-code": "code", **(headers or {})}
    return {"requestContext": {"http": {"method": method, "sourceIp": "1.1.1.1"}}, "rawPath": path,
            "queryStringParameters": query, "headers": h, "body": json.dumps(body) if body else None}


def meta(i, status="ok", tester="joe"):
    m = {"key": f"uploads/20261022-0000{i:02d}-abc/p{i}.jpg", "status": status, "tester": tester,
         "orig_bytes": 1000, "votes": {}, "labels": [{"name": "Bag", "confidence": 99.0, "categories": ["x"]}]}
    if status == "ok":
        m.update(thumb_key=f"thumbs/{m['key']}", reduction_pct=90.0 + i % 5, thumb_width=300, thumb_height=200)
    return m


def body_of(resp):
    raw = base64.b64decode(resp["body"]) if resp.get("isBase64Encoded") else resp["body"].encode()
    if resp["headers"].get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def test_results_paged_newest_first_with_cdn_thumbs(api):
    for i in range(30):
        api.s3.add(meta(i)["key"], meta(i))
    data = body_of(api.lambda_handler(event("/api/results", query={"limit": "10"}), None))
    assert data["total"] == 30 and len(data["items"]) == 10 and data["next_offset"] == 10
    assert data["items"][0]["key"].endswith("p29.jpg")
    assert data["items"][0]["thumb_url"].startswith("https://cdn.example/thumbs/uploads/")
    assert "original_url" not in data["items"][0]
    assert data["items"][0]["labels"] == [{"name": "Bag", "confidence": 99.0}]
    last = body_of(api.lambda_handler(event("/api/results", query={"limit": "10", "offset": "20"}), None))
    assert last["next_offset"] is None and len(last["items"]) == 10


def test_meta_cache_only_refetches_changed_documents(api):
    for i in range(5):
        api.s3.add(meta(i)["key"], meta(i))
    api.lambda_handler(event("/api/results"), None)
    assert api.s3.gets == 5
    api.lambda_handler(event("/api/results"), None)
    assert api.s3.gets == 5  # warm: nothing re-downloaded
    api.s3.add(meta(2)["key"], meta(2), etag="e2")
    api.lambda_handler(event("/api/results"), None)
    assert api.s3.gets == 6  # only the changed one


def test_vote_updates_cache_without_refetch(api):
    m = meta(1)
    api.s3.add(m["key"], m)
    api.lambda_handler(event("/api/results"), None)
    gets = api.s3.gets
    api.lambda_handler(event("/api/votes", "POST", body={"key": m["key"], "useful": True, "tester": "Tumelo"}), None)
    data = body_of(api.lambda_handler(event("/api/results"), None))
    assert data["items"][0]["votes"] == {"Tumelo": True}
    assert data["summary"]["votes_up"] == 1
    assert api.s3.gets == gets + 1  # the vote's own read, then served from cache


def test_filters_and_summary_cover_everything(api):
    api.s3.add(meta(1)["key"], meta(1))
    api.s3.add(meta(2)["key"], meta(2, status="rejected", tester="lo"))
    api.s3.add(meta(3)["key"], meta(3, status="error"))
    data = body_of(api.lambda_handler(event("/api/results", query={"status": "rejected"}), None))
    assert [i["status"] for i in data["items"]] == ["rejected"] and data["matched"] == 1
    assert data["summary"] == {"total": 3, "ok": 1, "rejected": 1, "errors": 1, "success_pct": 50.0,
                               "avg_reduction_pct": 91.0, "votes_up": 0, "votes_total": 0}
    mine = body_of(api.lambda_handler(event("/api/results", query={"tester": "lo"}), None))
    assert mine["matched"] == 1


def test_single_result_still_has_original(api):
    m = meta(4)
    api.s3.add(m["key"], m)
    data = body_of(api.lambda_handler(event("/api/results", query={"key": m["key"]}), None))
    assert data["original_url"].startswith("https://signed/src/")
    assert data["thumb_url"].startswith("https://cdn.example/")


def test_original_link(api):
    data = body_of(api.lambda_handler(event("/api/original", query={"key": "uploads/x/a.jpg"}), None))
    assert data["url"] == "https://signed/src/uploads/x/a.jpg"
    assert api.lambda_handler(event("/api/original", query={"key": "../etc"}), None)["statusCode"] == 400


def test_gzip_only_when_accepted(api):
    for i in range(10):
        api.s3.add(meta(i)["key"], meta(i))
    plain = api.lambda_handler(event("/api/results"), None)
    assert "content-encoding" not in plain["headers"]
    zipped = api.lambda_handler(event("/api/results", headers={"accept-encoding": "gzip, br"}), None)
    assert zipped["headers"]["content-encoding"] == "gzip" and zipped["isBase64Encoded"]
    assert body_of(zipped) == body_of(plain)


def test_page_cacheable_with_etag(api):
    first = api.lambda_handler(event("/", headers={"accept-encoding": "gzip"}), None)
    assert first["statusCode"] == 200 and "max-age=60" in first["headers"]["cache-control"]
    assert first["headers"]["content-encoding"] == "gzip"
    again = api.lambda_handler(event("/", headers={"if-none-match": first["headers"]["etag"]}), None)
    assert again["statusCode"] == 304 and again["body"] == ""


def test_auth_still_required(api):
    resp = api.lambda_handler(event("/api/results", headers={"x-team-code": "nope"}), None)
    assert resp["statusCode"] == 401
