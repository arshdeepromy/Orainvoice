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
