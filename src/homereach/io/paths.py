"""Validate metadata paths beneath a caller-selected local project root."""
from __future__ import annotations

from pathlib import Path


_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}


def safe_filename(value: object) -> str:
    """Accept one portable filename, never a path or a Windows device/stream."""
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a non-empty filename, not a path.")
    if (value in {".", ".."} or value != value.strip() or value.endswith(".")
            or any(char in '/\\<>:"|?*' or ord(char) < 32 for char in value)
            or value.partition(".")[0].rstrip().upper() in _WINDOWS_DEVICES):
        raise ValueError(f"Unsafe filename: {value!r}. Use a filename, not a path.")
    return value


def contained_path(root: str | Path, relative: str | Path) -> Path:
    """Check relative components and symlinks before any content read or write.

    The root is an explicit local caller choice. Metadata may select only a
    descendant of that root. Keep the lexical filename so reports and atomic
    replacements retain their existing meaning; concurrent filesystem changes
    are outside this local, single-build contract.
    """
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts:
        raise ValueError("Expected a project-relative path.")
    for part in relative.parts:
        safe_filename(part)
    anchor = Path(root).resolve()
    candidate = anchor / relative
    if not candidate.resolve().is_relative_to(anchor):
        raise ValueError(f"Path escapes the project root: {relative}")
    return candidate
