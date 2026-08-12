import re
import shutil
from pathlib import Path

INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
WHITESPACE_RE = re.compile(r'\s+')
# Windows silently drops trailing dots/spaces from directory names, and
# rejects these device names outright regardless of extension.
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


def slugify(name: str) -> str:
    name = name.strip()
    name = INVALID_CHARS_RE.sub('', name)
    name = WHITESPACE_RE.sub('_', name.strip())
    name = name.rstrip('. ')
    if not name:
        raise ValueError("project name is empty after cleanup")
    if name.upper() in RESERVED_NAMES:
        raise ValueError(f"{name} is a reserved Windows device name")
    return name


def unique_slug(root: Path, base_slug: str) -> str:
    candidate = base_slug
    n = 2
    while (root / candidate).exists():
        candidate = f"{base_slug}_{n}"
        n += 1
    return candidate


def project_dir(root: Path, slug: str) -> Path:
    return root / slug


def raw_dir(root: Path, slug: str) -> Path:
    return project_dir(root, slug) / "raw"


def passport_path(root: Path, slug: str) -> Path:
    return project_dir(root, slug) / "passport.json"


def estimate_path(root: Path, slug: str) -> Path:
    return raw_dir(root, slug) / "smeta.xlsx"


def create_project(root: Path, project_name: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    slug = unique_slug(root, slugify(project_name))
    raw_dir(root, slug).mkdir(parents=True)
    return slug


def delete_project(root: Path, slug: str) -> None:
    shutil.rmtree(project_dir(root, slug), ignore_errors=True)


def list_project_slugs(root: Path) -> list:
    """Slugs of complete projects, i.e. directories that have a passport.json.

    A directory without a passport.json is an orphan: creation got as far as
    making the folder but never saved the passport (crash, unreadable upload,
    manual meddling). Such a directory is unusable — the project page 404s on
    it — so it must not be listed. Filtering here (rather than trying to catch
    every possible failure mode at creation time) also self-heals from crashes.
    """
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and passport_path(root, p.name).exists()
    )
