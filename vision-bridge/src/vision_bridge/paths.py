from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from vision_bridge.errors import (
    DirectoryNotAllowed,
    ExtensionNotAllowed,
    FileTooLarge,
    PathNotFound,
    SecretPatternRefused,
)

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_SECRET_NAMES = frozenset(
    {
        ".netrc",
        "cookies",
        "credentials",
        "credentials.json",
        "credentials.sqlite",
        "keyring",
        "login data",
        "logins.json",
        "passwords",
        "secrets.json",
        "storage-state.json",
    }
)
_SECRET_COMPONENTS = frozenset({".aws", ".ssh", "credential-store"})
_SECRET_STEMS = frozenset(
    {
        "access-key",
        "api-key",
        "auth-token",
        "credential",
        "credentials",
        "private-key",
        "refresh-token",
        "secret-key",
    }
)
_SECRET_SUFFIXES = frozenset({".db", ".key", ".pfx", ".pem"})


@dataclass(frozen=True, slots=True)
class ValidatedPath:
    path: Path
    extension: str
    sensitivity_concern: bool


def validate_image_path(
    value: str,
    *,
    allowed_directories: Iterable[Path],
) -> ValidatedPath:
    return _validate_path(
        value,
        kind="image",
        extensions=IMAGE_EXTENSIONS,
        size_cap=MAX_IMAGE_BYTES,
        allowed_directories=allowed_directories,
    )


def _validate_path(
    value: str,
    *,
    kind: str,
    extensions: frozenset[str],
    size_cap: int,
    allowed_directories: Iterable[Path],
) -> ValidatedPath:
    candidate = Path(value).expanduser()
    if candidate.suffix.lower() not in extensions:
        raise ExtensionNotAllowed(f"{kind} extension is not allowed")
    if _is_secret_name(candidate):
        raise SecretPatternRefused("path matches a known-secret pattern")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PathNotFound(f"{kind} file was not found") from exc
    resolved_extension = resolved.suffix.lower()
    if resolved_extension not in extensions:
        raise ExtensionNotAllowed(f"resolved {kind} extension is not allowed")
    if _is_secret_name(resolved):
        raise SecretPatternRefused("resolved path matches a known-secret pattern")
    roots = tuple(root.resolve(strict=False) for root in allowed_directories)
    if roots and not any(resolved.is_relative_to(root) for root in roots):
        raise DirectoryNotAllowed(f"{kind} path is outside the configured directory allow-list")
    if not resolved.is_file():
        raise PathNotFound(f"{kind} file was not found")
    if resolved.stat().st_size > size_cap:
        raise FileTooLarge(f"{kind} file exceeds 20 MB per-file limit")
    return ValidatedPath(
        path=resolved,
        extension=resolved_extension,
        sensitivity_concern=_looks_sensitive(resolved),
    )


def _is_secret_name(path: Path) -> bool:
    name = path.name.casefold()
    if any(component.casefold() in _SECRET_COMPONENTS for component in path.parts):
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    if name in _SECRET_NAMES:
        return True
    if path.suffix.casefold() in _SECRET_SUFFIXES:
        return True
    stem = path.stem.casefold()
    return stem in _SECRET_STEMS or stem.startswith("id_rsa") or stem.startswith("id_ed25519")


def _looks_sensitive(path: Path) -> bool:
    sensitive_components = {"confidential", "private", "secret", "secrets", "sensitive"}
    return any(component.casefold() in sensitive_components for component in path.parts)
