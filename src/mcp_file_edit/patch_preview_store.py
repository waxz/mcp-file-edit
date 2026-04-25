from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import secrets


PREVIEW_TTL = timedelta(hours=1)


@dataclass
class PatchPreviewSession:
    preview_id: str
    patch: str
    structured_preview: Dict[str, Any]
    created_at: datetime
    expires_at: datetime
    confirm_token: str
    reject_token: str
    status: str = "pending"
    confirmed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


_SESSIONS: Dict[str, PatchPreviewSession] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_expired_sessions() -> None:
    now = _now()
    expired = [preview_id for preview_id, session in _SESSIONS.items() if session.expires_at <= now]
    for preview_id in expired:
        _SESSIONS.pop(preview_id, None)


def create_patch_preview_session(
    patch: str,
    structured_preview: Dict[str, Any],
) -> PatchPreviewSession:
    cleanup_expired_sessions()
    created_at = _now()
    preview_id = secrets.token_urlsafe(12)
    session = PatchPreviewSession(
        preview_id=preview_id,
        patch=patch,
        structured_preview=structured_preview,
        created_at=created_at,
        expires_at=created_at + PREVIEW_TTL,
        confirm_token=secrets.token_urlsafe(18),
        reject_token=secrets.token_urlsafe(18),
    )
    _SESSIONS[preview_id] = session
    return session


def get_patch_preview_session(preview_id: str) -> Optional[PatchPreviewSession]:
    cleanup_expired_sessions()
    return _SESSIONS.get(preview_id)


def set_patch_preview_status(preview_id: str, *, token: str, status: str) -> PatchPreviewSession:
    session = get_patch_preview_session(preview_id)
    if session is None:
        raise KeyError(preview_id)
    if status == "confirmed":
        if token != session.confirm_token:
            raise PermissionError("Invalid confirmation token")
        session.status = "confirmed"
        session.confirmed_at = _now()
    elif status == "rejected":
        if token != session.reject_token:
            raise PermissionError("Invalid rejection token")
        session.status = "rejected"
        session.rejected_at = _now()
    else:
        raise ValueError(f"Unsupported status: {status}")
    return session


def mark_patch_preview_applied(preview_id: str) -> PatchPreviewSession:
    session = get_patch_preview_session(preview_id)
    if session is None:
        raise KeyError(preview_id)
    session.status = "applied"
    session.applied_at = _now()
    return session


def update_patch_preview_files(
    preview_id: str,
    files: list[Dict[str, Any]],
) -> PatchPreviewSession:
    session = get_patch_preview_session(preview_id)
    if session is None:
        raise KeyError(preview_id)
    session.structured_preview["files"] = files
    session.updated_at = _now()
    return session
