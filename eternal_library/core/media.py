from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def save_content_image(uploaded, directory: Path, prefix: str) -> str | None:
    if not uploaded or not uploaded.filename:
        return None

    extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Допустимы PNG, JPG/JPEG и WEBP.")

    try:
        raw = uploaded.read()
        image = Image.open(BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Файл не удалось распознать как изображение.") from exc

    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")

    image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:16]}.webp"
    image.save(directory / filename, "WEBP", quality=88, method=6)
    return filename
