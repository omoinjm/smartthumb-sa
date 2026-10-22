import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "processor"))
import handler  # noqa: E402


def image_bytes(size, fmt="JPEG", mode="RGB", color=(200, 80, 40, 255)):
    img = Image.new(mode, size, color[: len(mode)] if mode != "P" else 1)
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, objects):
        self.objects = objects  # {(bucket, key): (bytes, metadata)}
        self.puts = {}

    def get_object(self, Bucket, Key):
        data, metadata = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data), "Metadata": metadata}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts[(Bucket, Key)] = (Body, kwargs)


class FakeRekognition:
    def __init__(self, fail=False):
        self.fail = fail

    def detect_labels(self, **kwargs):
        if self.fail:
            raise RuntimeError("rekognition down")
        return {"Labels": [{"Name": "Handbag", "Confidence": 97.123, "Categories": [{"Name": "Fashion"}]}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OUTPUT_BUCKET", "out")
    monkeypatch.setenv("ENABLE_LABELS", "true")


def run(monkeypatch, key, data, rek=None, tester="thandi"):
    fake = FakeS3({("src", key): (data, {"tester": tester})})
    monkeypatch.setattr(handler, "_s3", fake)
    monkeypatch.setattr(handler, "_rekognition", rek or FakeRekognition())
    event = {"Records": [{"s3": {"bucket": {"name": "src"}, "object": {"key": key.replace(" ", "+"), "size": len(data)}}}]}
    result = handler.lambda_handler(event, None)
    meta_key = ("out", f"meta/{key}.json")
    meta = json.loads(fake.puts[meta_key][0])
    return result, meta, fake


@pytest.mark.parametrize(
    "size,expected",
    [((1200, 800), (300, 200)), ((800, 1200), (200, 300)), ((4000, 500), (300, 38)), ((300, 300), (300, 300))],
)
def test_thumbnail_bounds_and_aspect(size, expected):
    thumb, info = handler.make_thumbnail(image_bytes(size))
    assert (info["thumb_width"], info["thumb_height"]) == expected
    assert Image.open(io.BytesIO(thumb)).size == expected


def test_small_image_not_upscaled():
    _, info = handler.make_thumbnail(image_bytes((120, 80)))
    assert (info["thumb_width"], info["thumb_height"]) == (120, 80)


def test_png_alpha_kept_as_png():
    thumb, info = handler.make_thumbnail(image_bytes((1000, 1000), "PNG", "RGBA", (0, 0, 0, 0)))
    assert info["thumb_format"] == "PNG"
    assert Image.open(io.BytesIO(thumb)).mode == "RGBA"


def test_png_without_alpha_becomes_jpeg():
    _, info = handler.make_thumbnail(image_bytes((1000, 1000), "PNG"))
    assert info["thumb_format"] == "JPEG"


def test_exif_orientation_applied():
    img = Image.new("RGB", (1200, 600), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    _, info = handler.make_thumbnail(buf.getvalue())
    assert (info["thumb_width"], info["thumb_height"]) == (150, 300)


@pytest.mark.parametrize(
    "data",
    [b"", b"hello, I am not an image", b"\xff\xd8\xff\xe0" + b"\x00garbage" * 50],
)
def test_bad_content_rejected(data):
    with pytest.raises(handler.Rejected):
        handler.make_thumbnail(data)


def test_unsupported_format_rejected():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, "GIF")
    with pytest.raises(handler.Rejected, match="GIF"):
        handler.make_thumbnail(buf.getvalue())


def test_end_to_end_ok(env, monkeypatch):
    key = "uploads/abc/red bag.jpg"
    result, meta, fake = run(monkeypatch, key, image_bytes((2000, 1500)))
    assert result["results"][0]["status"] == "ok"
    assert meta["status"] == "ok"
    assert meta["tester"] == "thandi"
    assert meta["thumb_key"] == "thumbs/uploads/abc/red bag.jpg"
    assert ("out", meta["thumb_key"]) in fake.puts
    assert meta["labels"][0]["name"] == "Handbag"
    assert meta["labels_status"] == "ok"
    assert 0 < meta["thumb_bytes"] < meta["orig_bytes"]


def test_end_to_end_bad_extension(env, monkeypatch):
    _, meta, fake = run(monkeypatch, "uploads/x/notes.txt", b"text")
    assert meta["status"] == "rejected"
    assert "extension" in meta["reason"]
    assert not any(k.startswith("thumbs/") for _, k in fake.puts)


def test_end_to_end_fake_jpeg(env, monkeypatch):
    _, meta, _ = run(monkeypatch, "uploads/x/fake.jpg", b"definitely text")
    assert meta["status"] == "rejected"


def test_labels_failure_does_not_fail_thumbnail(env, monkeypatch):
    _, meta, _ = run(monkeypatch, "uploads/x/a.png", image_bytes((600, 400), "PNG"), rek=FakeRekognition(fail=True))
    assert meta["status"] == "ok"
    assert meta["labels_status"] == "error"


def test_labels_disabled(env, monkeypatch):
    monkeypatch.setenv("ENABLE_LABELS", "false")
    _, meta, _ = run(monkeypatch, "uploads/x/a.jpg", image_bytes((600, 400)))
    assert meta["labels_status"] == "disabled"
    assert meta["labels"] == []
