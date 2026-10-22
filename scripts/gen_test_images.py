"""Generate a reproducible synthetic test set in test_images/generated/.

Covers sizes, aspect ratios, formats, EXIF rotation, transparency and invalid
files. Real product photos go in test_images/real/ (see README there).
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "test_images" / "generated"


def product(size, seed, colour):
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, (236, 228, 214))
    d = ImageDraw.Draw(img)
    u = min(w, h)
    d.rounded_rectangle([w / 2 - u * .3, h / 2 - u * .12, w / 2 + u * .3, h / 2 + u * .28], radius=u * .05, fill=colour)
    d.arc([w / 2 - u * .17, h / 2 - u * .29, w / 2 + u * .17, h / 2 + u * .05], 180, 360, fill=(60, 30, 20), width=max(2, int(u * .04)))
    # photo-like noise so JPEG sizes resemble real phone photos
    noise = Image.effect_noise(size, 18).convert("RGB")
    img = Image.blend(img, noise, 0.08).filter(ImageFilter.SMOOTH)
    if rnd.random() > .5:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return img


def save(img, name, **kw):
    path = OUT / name
    img.save(path, **kw)
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    colours = [(122, 46, 29), (25, 70, 120), (30, 110, 60), (150, 120, 20), (90, 40, 110)]
    sizes = [(4032, 3024), (3024, 4032), (1920, 1080), (1080, 1080), (2400, 1600), (800, 600), (640, 960), (5000, 700)]

    for i, size in enumerate(sizes):
        img = product(size, i, colours[i % len(colours)])
        save(img, f"product_{i:02d}_{size[0]}x{size[1]}.jpg", quality=92)
    for i, size in enumerate([(1500, 1500), (1200, 800), (2000, 3000)]):
        save(product(size, 50 + i, colours[i]), f"product_png_{i:02d}.png")

    # Transparent PNG logo (should stay PNG)
    logo = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse([150, 150, 850, 850], fill=(11, 122, 92, 255))
    save(logo, "logo_transparent.png")

    # Phone photo stored sideways with EXIF orientation 6 (thumbnail must come out portrait)
    exif = Image.Exif()
    exif[0x0112] = 6
    save(product((3000, 2000), 99, colours[0]), "phone_exif_rotated.jpg", quality=90, exif=exif)

    # Already-small images (no upscaling; may not shrink 50%)
    save(product((200, 150), 7, colours[1]), "tiny_200x150.jpg", quality=80)
    save(product((300, 300), 8, colours[2]), "exact_300.png")

    # Invalid files (expected: rejected)
    (OUT / "fake_text.jpg").write_bytes(b"this is not an image")
    (OUT / "corrupt.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes(random.Random(1).randrange(256) for _ in range(4000)))
    (OUT / "price_list.txt").write_text("handbag R350\n")
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (200, 0, 0)).save(buf, "GIF")
    (OUT / "animated.gif").write_bytes(buf.getvalue())
    (OUT / "empty.png").write_bytes(b"")  # S3 POST requires >=1 byte, so the API refuses this one up front

    print(f"Wrote {len(list(OUT.iterdir()))} files to {OUT}")


if __name__ == "__main__":
    main()
