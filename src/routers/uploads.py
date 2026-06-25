import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()

# Project root: src/routers/uploads.py → parents[2]
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"

_MAX_BYTES = 2 * 1024 * 1024  # 2 MB per file

# Logical name → saved filename. sales + cost are required; ads + returns optional.
_SLOTS = {
    "sales":   "sales.csv",
    "cost":    "cost.csv",
    "ads":     "ads.csv",
    "returns": "returns.csv",
}
_REQUIRED = {"sales", "cost"}


async def _read_capped(file: UploadFile, slot: str) -> bytes:
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{slot}: must be a .csv file")
    # Read one byte past the cap to detect oversize without loading huge files.
    data = await file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"{slot}: file exceeds 2 MB limit")
    if not data.strip():
        raise HTTPException(status_code=400, detail=f"{slot}: file is empty")
    return data


@router.post("/uploads", status_code=201)
async def create_upload(
    sales: UploadFile = File(...),
    cost: UploadFile = File(...),
    ads: UploadFile | None = File(None),
    returns: UploadFile | None = File(None),
):
    """Accept the 4 Shopee CSVs, save under uploads/<uuid>/, return the upload_id.

    sales + cost are required; ads + returns are optional. Each file is validated
    as a non-empty .csv and capped at 2 MB.
    """
    provided = {"sales": sales, "cost": cost, "ads": ads, "returns": returns}

    # Validate + read everything before writing anything (no partial dirs on error).
    # Some clients submit empty optional file fields (no filename) — skip those, but
    # a missing required field is still a 400. Close every handle on the way out.
    contents: dict[str, bytes] = {}
    try:
        for slot, file in provided.items():
            if file is None or not file.filename:
                if slot in _REQUIRED:
                    raise HTTPException(status_code=400, detail=f"{slot}: required .csv file is missing")
                continue
            contents[slot] = await _read_capped(file, slot)
    finally:
        for file in provided.values():
            if file is not None:
                await file.close()

    upload_id = uuid.uuid4().hex
    dest = UPLOAD_ROOT / upload_id
    dest.mkdir(parents=True, exist_ok=True)
    for slot, data in contents.items():
        (dest / _SLOTS[slot]).write_bytes(data)

    return {"upload_id": upload_id, "files": sorted(contents.keys())}
