"""
app/api/v1/reports.py

Simple reports router to list and download generated campaign reports.

Endpoints:
- GET /reports/            : list available report files (filename, size, modified_at, campaign_id if parsable)
- GET /reports/download/{filename:path} : download a specific report file
"""
from typing import List, Dict, Optional
import os
from datetime import datetime
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings

router = APIRouter()
settings = get_settings()

_REPORT_NAME_RE = re.compile(r"^campaign_(?P<campaign_id>\d+)_(?P<ts>\d+)\.csv$")


def _list_report_files() -> List[Dict]:
    reports_dir = os.path.abspath(settings.REPORTS_DIR)
    if not os.path.exists(reports_dir):
        return []

    out = []
    for fname in sorted(os.listdir(reports_dir), reverse=True):
        path = os.path.join(reports_dir, fname)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        m = _REPORT_NAME_RE.match(fname)
        campaign_id = int(m.group("campaign_id")) if m else None
        ts = int(m.group("ts")) if m else None
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        out.append(
            {
                "filename": fname,
                "campaign_id": campaign_id,
                "size": stat.st_size,
                "modified_at": modified_at,
                "path": path,
            }
        )
    return out


@router.get("/", summary="List report files")
def list_reports() -> List[Dict]:
    """
    Return a list of generated report files with metadata.
    """
    items = _list_report_files()
    # strip path for API surface
    for i in items:
        i.pop("path", None)
    return items


@router.get("/download/{filename:path}", summary="Download a report file")
def download_report(filename: str):
    """
    Download the requested report file by filename. For safety we only serve
    files that actually exist under REPORTS_DIR.
    """
    reports_dir = os.path.abspath(settings.REPORTS_DIR)
    requested = os.path.normpath(os.path.join(reports_dir, filename))

    # security: prevent path traversal
    if not requested.startswith(reports_dir):
        raise HTTPException(status_code=400, detail="invalid filename")

    if not os.path.exists(requested) or not os.path.isfile(requested):
        raise HTTPException(status_code=404, detail="report not found")

    # Return a FileResponse (streamed by Starlette)
    return FileResponse(path=requested, filename=os.path.basename(requested), media_type="text/csv")