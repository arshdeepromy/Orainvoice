"""Secure file upload router."""
from __future__ import annotations
import io, os, uuid, zlib
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_session
from app.core.encryption import envelope_encrypt, envelope_decrypt
from app.core.storage_manager import StorageManager

router = APIRouter()
UPLOAD_BASE = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
MAX_FILE_SIZE = 10 * 1024 * 1024
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
COMP_ZLIB = b"\x01"
COMP_IMAGE = b"\x02"
MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf", ".gif": "image/gif"}

def _get_org_id(request: Request) -> str:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return str(org_id)

def _compress_image(content: bytes, ext: str) -> tuple:
    from PIL import Image
    img = Image.open(io.BytesIO(content))
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = bg
    w, h = img.size
    if max(w, h) > 2048:
        r = 2048 / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = io.BytesIO()
    if ext.lower() == ".png":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), ".png"
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue(), ".jpg"

async def _store(content, filename, org_id, cat, db):
    ext = Path(filename).suffix.lower() or ".bin"
    if ext in IMAGE_EXTS:
        try:
            processed, ext = _compress_image(content, ext)
            flag = COMP_IMAGE
        except Exception:
            processed = zlib.compress(content, 6)
            flag = COMP_ZLIB
    else:
        processed = zlib.compress(content, 6)
        flag = COMP_ZLIB
    encrypted = envelope_encrypt(processed)
    fk = f"{cat}/{org_id}/{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_BASE / fk
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(flag + encrypted)
    sz = len(flag) + len(encrypted)
    sm = StorageManager(db)
    await sm.enforce_quota(org_id, sz)
    await sm.increment_usage(org_id, sz)
    return {"file_key": fk, "file_name": filename, "file_size": sz}

@router.post("/receipts", summary="Upload receipt")
async def upload_receipt(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")
    if not content:
        raise HTTPException(400, "Empty file")
    r = await _store(content, file.filename or "receipt.bin", org_id, "receipts", db)
    await db.commit()
    return r

@router.post("/attachments", summary="Upload attachment")
async def upload_attachment(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")
    if not content:
        raise HTTPException(400, "Empty file")
    r = await _store(content, file.filename or "attachment.bin", org_id, "attachments", db)
    await db.commit()
    return r

@router.post("/clock-photos", summary="Upload kiosk/self-service clock-in photo")
async def upload_clock_photo(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db_session)):
    """Upload a kiosk or self-service clock-in/out photo.

    Mirrors ``/receipts`` and ``/attachments``; files land at
    ``/app/uploads/clock_photos/<org_id>/<uuid>.{jpg,png}`` per the
    existing :func:`_store` helper. Returns ``{ file_key, file_name,
    file_size }`` — the ``file_key`` value is what the kiosk + self-
    service clock-action endpoints accept as ``photo_file_key`` (P3-N1).

    Validates: Requirements R3.5 — Staff Management Phase 3 task B9.
    """
    org_id = _get_org_id(request)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")
    if not content:
        raise HTTPException(400, "Empty file")
    r = await _store(content, file.filename or "clock-photo.bin", org_id, "clock_photos", db)
    await db.commit()
    return r


def _compress_passport_photo(content: bytes) -> tuple:
    """Compress an uploaded image to passport-thumbnail size.

    Tighter resize (≤512px on the long edge) and slightly lower JPEG
    quality (78) than ``_compress_image`` because these photos are
    rendered at avatar-size everywhere they appear (≤ 64×64 px on the
    profile hero, ≤ 40×40 px in the clocked-in drawer, ≤ 32×32 px in
    table rows). Anything larger is wasted bandwidth + storage. End
    result: a typical 4MB phone selfie → ~25–40 KB stored.

    Mirrors :func:`_compress_image` for transparency handling
    (RGBA / P / LA → RGB on white) so PNGs with alpha don't render
    with a black background.
    """
    from PIL import Image
    img = Image.open(io.BytesIO(content))
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > 512:
        r = 512 / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=78, optimize=True, progressive=True)
    return buf.getvalue(), ".jpg"


@router.post("/staff-photos", summary="Upload staff profile (passport-size) photo")
async def upload_staff_photo(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db_session)):
    """Upload a staff passport-size profile photo.

    Re-uses the encryption + storage pipeline from :func:`_store` but
    with a tighter compression profile (``_compress_passport_photo``,
    ≤ 512 px on the long edge, JPEG quality 78). Files land at
    ``/app/uploads/staff_photos/<org_id>/<uuid>.jpg``.

    Returns ``{ file_key, file_name, file_size }``. The ``file_key``
    is the value the staff-update endpoint accepts as
    ``on_file_photo_url`` so the same field name keeps working with
    its existing kiosk-lookup consumers.
    """
    org_id = _get_org_id(request)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")
    if not content:
        raise HTTPException(400, "Empty file")

    # Always run the passport compressor — staff photos are rendered
    # exclusively at avatar size so we pay the resize cost on the
    # write path, not on every read. Falls back to the generic
    # zlib path on PIL failure (corrupt upload, unsupported format)
    # so the upload is never lost — same shape as ``_store`` does
    # for non-image files.
    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in IMAGE_EXTS:
        # Non-image upload — refuse rather than store binary garbage
        # against the staff record (the frontend gates the file picker
        # to image/* but the backend is the security boundary).
        raise HTTPException(415, "Unsupported file type — image required")
    try:
        processed, ext = _compress_passport_photo(content)
        flag = COMP_IMAGE
    except Exception:
        processed = zlib.compress(content, 6)
        flag = COMP_ZLIB
    encrypted = envelope_encrypt(processed)
    fk = f"staff_photos/{org_id}/{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_BASE / fk
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(flag + encrypted)
    sz = len(flag) + len(encrypted)
    sm = StorageManager(db)
    await sm.enforce_quota(org_id, sz)
    await sm.increment_usage(org_id, sz)
    await db.commit()
    return {"file_key": fk, "file_name": file.filename or "photo.jpg", "file_size": sz}

@router.get("/{category}/{org_path}/{file_id}", summary="Download file")
async def download_file(category: str, org_path: str, file_id: str, request: Request):
    req_org = _get_org_id(request)
    if org_path != req_org:
        raise HTTPException(403, "Access denied")
    fp = UPLOAD_BASE / category / org_path / file_id
    if not fp.is_file():
        raise HTTPException(404, "File not found")
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    raw = fp.read_bytes()
    if len(raw) < 2:
        raise HTTPException(500, "Corrupt file")
    flag, blob = raw[0:1], raw[1:]
    try:
        dec = envelope_decrypt(blob)
    except Exception:
        raise HTTPException(500, "Decryption failed")
    out = zlib.decompress(dec) if flag == COMP_ZLIB else dec
    ext = Path(file_id).suffix.lower()
    return Response(
        content=out,
        media_type=MIME_MAP.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{file_id}"', "Cache-Control": "private, max-age=3600"},
    )
