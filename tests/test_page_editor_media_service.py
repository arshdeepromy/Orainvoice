"""Unit tests for the page_editor media_service.

Covers MIME-by-content sniffing, upload size rejection, delete reference
checks, and WebP variant generation via Pillow.

Requirements: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from PIL import Image

from app.modules.page_editor import media_service
from app.modules.page_editor.media_service import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_SIZE,
    delete_media,
    sniff_mime_type,
    upload_media,
)


# ---------------------------------------------------------------------------
# Helpers — generate real image bytes for sniffing tests
# ---------------------------------------------------------------------------


def _png_bytes(width: int = 16, height: int = 16) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int = 16, height: int = 16) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _gif_bytes() -> bytes:
    img = Image.new("RGB", (8, 8), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def _svg_bytes() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        b'  <rect width="10" height="10" fill="red"/>\n'
        b'</svg>\n'
    )


# ---------------------------------------------------------------------------
# sniff_mime_type
# ---------------------------------------------------------------------------


def test_sniff_mime_type_detects_png():
    assert sniff_mime_type(_png_bytes()) == "image/png"


def test_sniff_mime_type_detects_jpeg():
    assert sniff_mime_type(_jpeg_bytes()) == "image/jpeg"


def test_sniff_mime_type_detects_gif():
    assert sniff_mime_type(_gif_bytes()) == "image/gif"


def test_sniff_mime_type_detects_svg():
    assert sniff_mime_type(_svg_bytes()) == "image/svg+xml"


def test_sniff_mime_type_rejects_text_disguised_as_jpg():
    """Renaming a .txt file to .jpg should not fool the sniffer."""
    assert sniff_mime_type(b"this is plain text, not an image") is None


def test_sniff_mime_type_rejects_riff_that_isnt_webp():
    """RIFF magic alone isn't WebP — must have WEBP at offset 8."""
    fake = b"RIFF\x00\x00\x00\x00WAVEfmt "
    assert sniff_mime_type(fake) != "image/webp"


def test_allowed_mime_types_includes_all_listed_in_spec():
    expected = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/svg+xml",
        "image/gif",
    }
    assert ALLOWED_MIME_TYPES == expected


# ---------------------------------------------------------------------------
# upload_media — size & MIME validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_media_rejects_oversize_file_413():
    db = AsyncMock()
    too_big = b"\x00" * (MAX_UPLOAD_SIZE + 1)
    with pytest.raises(HTTPException) as exc:
        await upload_media(db, too_big, "huge.png", uuid.uuid4())
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_upload_media_rejects_unknown_mime_415():
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await upload_media(db, b"not an image", "fake.png", uuid.uuid4())
    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_upload_media_persists_png_with_variants(tmp_path, monkeypatch):
    """Happy-path PNG upload: row added, variants written, dimensions captured."""
    monkeypatch.setattr(media_service, "UPLOAD_BASE", tmp_path)

    db = AsyncMock()
    captured = {}

    def _add(asset):
        captured["asset"] = asset

    db.add.side_effect = _add

    png = _png_bytes(width=2000, height=1500)  # large enough to fan out variants
    user_id = uuid.uuid4()
    await upload_media(db, png, "hero.png", user_id)

    asset = captured.get("asset")
    assert asset is not None
    assert asset.content_type == "image/png"
    assert asset.size_bytes == len(png)
    assert asset.width == 2000
    assert asset.height == 1500
    # Multiple WebP variants should have been generated
    assert len(asset.variants) >= 2
    for path in asset.variants.values():
        assert Path(path).exists()


@pytest.mark.asyncio
async def test_upload_media_skips_variant_generation_for_svg(tmp_path, monkeypatch):
    monkeypatch.setattr(media_service, "UPLOAD_BASE", tmp_path)

    db = AsyncMock()
    captured = {}
    db.add.side_effect = lambda a: captured.update(asset=a)

    await upload_media(db, _svg_bytes(), "logo.svg", uuid.uuid4())

    asset = captured["asset"]
    assert asset.content_type == "image/svg+xml"
    assert asset.variants == {}
    # Original is still saved
    assert Path(asset.original_path).exists()


# ---------------------------------------------------------------------------
# delete_media — reference check (Requirement 12.4)
# ---------------------------------------------------------------------------


def _media_asset(*, asset_id: uuid.UUID | None = None, deleted_at=None):
    asset = MagicMock()
    asset.id = asset_id or uuid.uuid4()
    asset.deleted_at = deleted_at
    return asset


def _execute_returns(scalar=None, *, all_rows=None):
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    res.all.return_value = all_rows or []
    return res


@pytest.mark.asyncio
async def test_delete_media_not_found_returns_404():
    db = AsyncMock()
    db.execute.return_value = _execute_returns(scalar=None)
    with pytest.raises(HTTPException) as exc:
        await delete_media(db, uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_media_already_deleted_returns_410():
    db = AsyncMock()
    asset = _media_asset(deleted_at=datetime.now(timezone.utc))
    db.execute.return_value = _execute_returns(scalar=asset)
    with pytest.raises(HTTPException) as exc:
        await delete_media(db, asset.id)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_delete_media_referenced_in_draft_returns_409():
    db = AsyncMock()
    asset = _media_asset()
    referencing_page_row = (
        "demo",
        "Demo Page",
        {"content": [{"type": "Image", "props": {"src": str(asset.id)}}], "root": {"props": {}}},
        None,
    )
    db.execute.side_effect = [
        _execute_returns(scalar=asset),                  # load asset
        _execute_returns(all_rows=[referencing_page_row]),  # page scan
    ]
    with pytest.raises(HTTPException) as exc:
        await delete_media(db, asset.id)
    assert exc.value.status_code == 409
    assert "Demo Page" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_delete_media_referenced_in_published_returns_409():
    db = AsyncMock()
    asset = _media_asset()
    referencing_page_row = (
        "live",
        "Live Page",
        None,
        {"content": [{"type": "Image", "props": {"src": str(asset.id)}}], "root": {"props": {}}},
    )
    db.execute.side_effect = [
        _execute_returns(scalar=asset),
        _execute_returns(all_rows=[referencing_page_row]),
    ]
    with pytest.raises(HTTPException) as exc:
        await delete_media(db, asset.id)
    assert exc.value.status_code == 409
    assert "Live Page" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_delete_media_unreferenced_soft_deletes():
    db = AsyncMock()
    asset = _media_asset()
    db.execute.side_effect = [
        _execute_returns(scalar=asset),
        _execute_returns(all_rows=[]),  # no pages reference this asset
    ]
    result = await delete_media(db, asset.id)
    assert result.deleted_at is not None
