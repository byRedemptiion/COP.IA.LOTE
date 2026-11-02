"""Préparation de l'image envoyée à l'IA : taille bornée, JPEG (envoi plus rapide que PNG)."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from alicia.core.ai.base import PreparedImage


def prepare_image(
    image: Image.Image, max_side: int = 1568, jpeg_quality: int = 88
) -> PreparedImage:
    rgb = image.convert("RGB") if image.mode != "RGB" else image
    scale = min(1.0, max_side / max(rgb.width, rgb.height))
    if scale < 1.0:
        size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        rgb = rgb.resize(size, Image.Resampling.LANCZOS)
    buffer = BytesIO()
    rgb.save(buffer, format="JPEG", quality=jpeg_quality, optimize=False, subsampling=0)
    return PreparedImage(buffer.getvalue(), "image/jpeg", rgb.width, rgb.height)
