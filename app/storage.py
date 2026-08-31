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


def dgp_path(root: Path, slug: str) -> Path:
    return raw_dir(root, slug) / "dgp.docx"


def tz_path(root: Path, slug: str) -> Path:
    return raw_dir(root, slug) / "tz.docx"


def contract_terms_path(root: Path, slug: str) -> Path:
    return raw_dir(root, slug) / "contract_terms.pdf"


def cost_increase_path(root: Path, slug: str) -> Path:
    """The project's cost-increase workbook. One file, always the latest one:
    it is kept cumulatively, so a newer version supersedes the previous one
    outright and keeping the old ones would only invite adding them up."""
    return raw_dir(root, slug) / "udorozhanie.xlsx"


# The claims-registry workbook behind "Прогнозируемое удорожание" — one
# shared file, not tied to any project, so it lives in its own directory
# alongside the per-project ones rather than inside one of them.
# ``list_project_slugs`` only picks up directories that have a passport.json
# (see below), so this sits safely next to the real projects without ever
# being mistaken for one.
def reestr_vis_dir(root: Path) -> Path:
    return root / "_reestr_vis"


def reestr_vis_path(root: Path) -> Path:
    return reestr_vis_dir(root) / "reestr_vis.xlsx"


COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def cover_path(root: Path, slug: str) -> Path | None:
    directory = project_dir(root, slug)
    for ext in COVER_EXTENSIONS:
        candidate = directory / f"cover{ext}"
        if candidate.exists():
            return candidate
    return None


def save_upload(file_storage, dest: Path) -> None:
    """Write an upload to ``dest`` atomically: saved to a sibling temporary
    file first, and only swapped into place once that succeeds — a write
    that fails partway (a full disk, an interrupted upload) then raises
    with ``dest`` still holding whatever was there before, rather than a
    truncated file with nothing to restore it from."""
    tmp = dest.with_name(dest.name + ".upload")
    file_storage.save(tmp)
    tmp.replace(dest)


def save_cover(root: Path, slug: str, file_storage, ext: str) -> Path:
    directory = project_dir(root, slug)
    dest = directory / f"cover{ext}"
    save_upload(file_storage, dest)
    for existing_ext in COVER_EXTENSIONS:
        if existing_ext != ext:
            (directory / f"cover{existing_ext}").unlink(missing_ok=True)
    return dest


def create_project(root: Path, project_name: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    slug = unique_slug(root, slugify(project_name))
    raw_dir(root, slug).mkdir(parents=True)
    return slug


def _staging_root(root: Path) -> Path:
    return root / ".staging"


def begin_project(root: Path, project_name: str):
    """Reserve a slug for a new project and set up a staging directory to
    build it in — not the real project directory yet.

    Returns ``(slug, staging_root)``; pass ``staging_root`` wherever
    ``root`` is expected (``raw_dir``, ``passport_path``, ``save_cover``,
    ...) to address files inside the staged copy. Nothing under it is
    visible to ``list_project_slugs`` or any other reader until
    ``publish_project`` moves it into place, so a creation that fails
    partway — a corrupt upload, a crash, anything at all — never leaves a
    half-built project sitting on disk with documents in it and no way to
    reach it through the UI to clean it up.
    """
    root.mkdir(parents=True, exist_ok=True)
    slug = unique_slug(root, slugify(project_name))
    staging_root = _staging_root(root)
    raw_dir(staging_root, slug).mkdir(parents=True)
    return slug, staging_root


def publish_project(root: Path, slug: str, staging_root: Path) -> None:
    """Move a fully-built staging directory into place as the real project
    — a rename, atomic because staging lives under ``root``, on the same
    volume."""
    project_dir(staging_root, slug).replace(project_dir(root, slug))


def discard_staging(staging_root: Path, slug: str) -> None:
    """Remove an abandoned staging directory after a creation fails
    partway. Best-effort, the same as ``delete_project``: Windows can hold
    a document just written open for an antivirus scan."""
    shutil.rmtree(project_dir(staging_root, slug), ignore_errors=True)


def sweep_staging(root: Path) -> None:
    """Remove every staging directory left by a process that crashed before
    it could publish or clean up after itself.

    Only ever call this once, at startup, before the app serves any
    requests — sweeping while a request is live would destroy a creation
    that's still being built.
    """
    staging_root = _staging_root(root)
    if not staging_root.exists():
        return
    for entry in staging_root.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)


# Marks a folder the user has already deleted, whose files couldn't all be
# removed at the time. Its presence takes the folder out of
# ``list_project_slugs`` on its own, so a deleted project stays deleted no
# matter what survived, and ``purge_deleted`` knows to come back for it.
DELETED_MARKER = ".deleted"


def _purge(directory: Path) -> bool:
    """Remove the folder and whatever is left inside. True once it's gone.

    Failures to remove an individual file are passed over rather than
    raised: what matters to the caller is only whether anything is still
    there, and a file that won't go this second often will a minute later.

    The marker is removed last, and only once the folder is otherwise
    empty. Sweeping it away with everything else would erase the only
    record that this project was ever deleted, leaving the leftovers to sit
    there forever with nothing coming back for them.

    ``purge_deleted`` runs on every dashboard load, so two of them can land
    on the same marked folder at once. Whichever finishes first removes the
    directory out from under the other, and the other's own ``iterdir()``
    then raises ``FileNotFoundError`` — treated here as success, since the
    folder being gone is exactly what this function is trying to achieve.
    """
    marker = directory / DELETED_MARKER
    try:
        for entry in directory.iterdir():
            if entry == marker:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                try:
                    entry.unlink()
                except OSError:
                    pass
        if any(entry != marker for entry in directory.iterdir()):
            return False
    except FileNotFoundError:
        return True
    try:
        marker.unlink(missing_ok=True)
        directory.rmdir()
    except OSError:
        marker.touch()
        return False
    return True


def delete_project(root: Path, slug: str) -> None:
    """Delete the project. Whatever can't go now goes later.

    Windows refuses to remove a file another program is holding open — an
    estimate still open in Excel, an antivirus mid-scan — and refuses to
    rename either the file or the folder around it, so there's nowhere to
    move the leftovers aside to and no way to always finish on the spot.

    What the user asked for still happens: the folder is flagged deleted
    first, which hides it immediately and permanently, and ``purge_deleted``
    finishes the removal on the next dashboard load, once the other program
    has let go. Never raises — a delete the user asked for is not something
    to hand back to them as an error.
    """
    directory = project_dir(root, slug)
    if not directory.exists():
        return
    # Flag first, delete second. The other order is what left an invisible,
    # undeletable folder behind: if removal stopped halfway with no flag,
    # nothing remembered the project was meant to be gone.
    (directory / DELETED_MARKER).write_bytes(b"")
    _purge(directory)


def purge_deleted(root: Path) -> None:
    """Retry the removal of every folder a previous delete couldn't finish.

    Only touches folders carrying the marker. A folder without one may be a
    project whose upload is still in progress, which must survive.
    """
    if not root.exists():
        return
    for entry in root.iterdir():
        if entry.is_dir() and (entry / DELETED_MARKER).exists():
            _purge(entry)


def list_project_slugs(root: Path) -> list:
    """Slugs of complete projects, i.e. directories that have a passport.json.

    A directory without a passport.json is an orphan: creation got as far as
    making the folder but never saved the passport (crash, unreadable upload,
    manual meddling). Such a directory is unusable — the project page 404s on
    it — so it must not be listed. Filtering here (rather than trying to catch
    every possible failure mode at creation time) also self-heals from crashes.

    A folder flagged with DELETED_MARKER is likewise skipped: the user has
    already deleted it and it must not reappear just because a file inside
    it was in use and outlived the delete.
    """
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir()
        and not (p / DELETED_MARKER).exists()
        and passport_path(root, p.name).exists()
    )
