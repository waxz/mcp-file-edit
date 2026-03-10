"""Cross-platform path normalization helpers."""

from __future__ import annotations

import os
import posixpath
from pathlib import PurePosixPath, PureWindowsPath


def is_windows_style_path(path_text: str) -> bool:
    """Return True when input uses Windows drive/backslash conventions."""
    return "\\" in path_text or bool(PureWindowsPath(path_text).drive)


def normalize_windows_path_text(path_text: str) -> str:
    """Normalize Windows path text for case-insensitive prefix comparison."""
    normalized = str(PureWindowsPath(path_text))
    anchor = PureWindowsPath(normalized).anchor
    if anchor:
        cleaned = normalized if normalized == anchor else normalized.rstrip("\\/")
    else:
        cleaned = normalized.rstrip("\\/")
    return (cleaned or anchor).casefold()


def normalize_posix_path(path_text: str) -> PurePosixPath:
    """Normalize POSIX path text, collapsing `.` and `..` segments."""
    text = path_text.replace("\\", "/")
    return PurePosixPath(posixpath.normpath(text))


def normalize_directory_value(path_text: str) -> str:
    """Normalize a configured directory path while preserving platform style."""
    text = path_text.strip()
    if not text:
        return text

    if is_windows_style_path(text):
        normalized = str(PureWindowsPath(text))
        anchor = PureWindowsPath(normalized).anchor
        if anchor and normalized != anchor:
            normalized = normalized.rstrip("\\/")
        elif not anchor:
            normalized = normalized.rstrip("\\/")
        return normalized or anchor

    normalized = str(normalize_posix_path(text))
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized or "."


def get_platform_path(path: str, platform: str, work_dir: str | None) -> str:
    text = path.strip()
    if not text:
        return text

    if platform == "windows":
        base = PureWindowsPath(work_dir or os.getcwd())
        windows_path = PureWindowsPath(text)
        if windows_path.is_absolute():
            return str(windows_path)
        return str(base / windows_path)

    if is_windows_style_path(text):
        raise ValueError(f"Invalid path {text} in {platform} env")

    base = PurePosixPath(work_dir or os.getcwd())
    posix_path = PurePosixPath(text)
    if posix_path.is_absolute():
        return str(posix_path)
    return str(base / posix_path)
