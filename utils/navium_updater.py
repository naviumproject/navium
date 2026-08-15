import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from urllib import error, request

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/naviumproject/navium/releases/latest"
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str) -> Tuple[int, int, int]:
    """Parse versions like '0.0.3' or 'v0.0.4'."""
    cleaned = str(version).strip().lower()
    if cleaned.startswith('v'):
        cleaned = cleaned[1:]
    match = SEMVER_RE.match(cleaned)
    if not match:
        raise ValueError(f"Invalid semantic version: {version!r}")
    return tuple(int(part) for part in match.groups())


def should_update(current_version: str, latest_release_tag: Optional[str]) -> bool:
    """Return True only when the latest stable release is newer than the local version."""
    if not latest_release_tag:
        return False

    tag = str(latest_release_tag).strip()
    if not tag:
        return False
    if tag.startswith('v'):
        tag = tag[1:]
    if re.search(r"[-_]", tag):
        return False

    try:
        current = parse_version(current_version)
        latest = parse_version(tag)
    except ValueError:
        return False
    return latest > current


def fetch_latest_stable_release(repo: str = "naviumproject/navium") -> Optional[dict]:
    """Fetch the newest stable release metadata, skipping prereleases and drafts."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "navium-updater",
        },
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except (error.HTTPError, error.URLError, TimeoutError, ValueError):
        return None

    if payload.get("draft") or payload.get("prerelease"):
        return None
    if not payload.get("tag_name"):
        return None
    return payload


def get_installed_version(version_file_path: str) -> str:
    """Read the installed app version from a file stored next to the executable."""
    path = Path(version_file_path)
    return path.read_text(encoding="utf-8").strip()


def get_release_zip_asset(release_payload: Optional[dict]) -> Optional[str]:
    """Return the browser_download_url for the first .zip asset if one exists."""
    if not release_payload:
        return None
    for asset in release_payload.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".zip") and "source" not in name:
            return asset.get("browser_download_url")
    return None


def download_file(url: str, destination: Path) -> Path:
    """Download a file and save it to destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "navium-updater",
        },
    )
    with request.urlopen(req, timeout=60) as response, open(destination, "wb") as fobj:
        shutil.copyfileobj(response, fobj)
    return destination


def extract_zip(zip_path: Path, destination_dir: Path) -> Path:
    """Extract the zip to destination_dir."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination_dir)
    return destination_dir


def find_update_root(root_dir: Path) -> Path:
    """Return the directory in the extracted ZIP that contains navium.exe or navium."""
    candidates = [root_dir, *[p for p in root_dir.iterdir() if p.is_dir()]]
    for candidate in candidates:
        if (candidate / "navium.exe").exists() or (candidate / "navium").exists():
            return candidate
    return root_dir


def install_update_bundle(app_dir: Path, zip_path: Path) -> Path:
    """Extract a new navium bundle and merge it into the current app directory."""
    app_dir = Path(app_dir)
    with tempfile.TemporaryDirectory(prefix="navium-update-") as tmp_dir:
        extracted = extract_zip(zip_path, Path(tmp_dir))
        update_root = find_update_root(extracted)

        for item in update_root.iterdir():
            target = app_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                if target.exists() or target.is_symlink():
                    target.unlink()
                shutil.copy2(item, target)
    return app_dir


def write_installed_version(version_file_path: str, version: str) -> None:
    """Persist the current version to disk to allow future comparisons."""
    path = Path(version_file_path)
    path.write_text(version.strip(), encoding="utf-8")


def check_for_update(current_version: str, version_file_path: str, repo: str = "naviumproject/navium") -> dict:
    """Check whether a newer stable navium release exists."""
    installed = get_installed_version(version_file_path)
    release = fetch_latest_stable_release(repo)
    tag = release.get("tag_name") if release else None
    update_available = should_update(current_version or installed, tag)
    return {
        "current_version": installed,
        "latest_release_tag": tag,
        "update_available": update_available,
        "release": release,
        "zip_url": get_release_zip_asset(release),
    }


def update_navium(app_dir: Path, version_file_path: str, repo: str = "naviumproject/navium") -> dict:
    """Check GitHub, download the latest stable release zip and install it in-place."""
    current_version = get_installed_version(version_file_path)
    release = fetch_latest_stable_release(repo)
    if not release:
        return {"update_available": False, "current_version": current_version, "reason": "No stable release found."}

    tag = release.get("tag_name")
    zip_url = get_release_zip_asset(release)
    if not zip_url or not should_update(current_version, tag):
        return {"update_available": False, "current_version": current_version, "latest_release_tag": tag}

    with tempfile.TemporaryDirectory(prefix="navium-update-") as tmp_dir:
        zip_path = Path(tmp_dir) / "navium-update.zip"
        download_file(zip_url, zip_path)
        install_update_bundle(Path(app_dir), zip_path)
        write_installed_version(version_file_path, str(tag).lstrip("v"))

    return {
        "update_available": True,
        "current_version": current_version,
        "latest_release_tag": tag,
        "zip_url": zip_url,
    }


def restart_navium(executable_path: str) -> None:
    """Launch the updated browser after the update has been applied."""
    subprocess.Popen([executable_path], shell=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Navium updater")
    parser.add_argument("--current-version", default="0.0.0", help="Installed navium version")
    parser.add_argument("--version-file", default="navium_version.txt", help="Path to the app version file")
    parser.add_argument("--repo", default="naviumproject/navium", help="GitHub repo in owner/name form")
    parser.add_argument("--check-only", action="store_true", help="Only check for an update and print JSON")
    parser.add_argument("--app-dir", default=".", help="Directory containing the installed navium files")
    parser.add_argument("--restart-exe", default="navium.exe", help="Executable to launch after update")
    args = parser.parse_args()

    if args.check_only:
        result = check_for_update(args.current_version, args.version_file, args.repo)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    result = update_navium(Path(args.app_dir), args.version_file, args.repo)
    if not result.get("update_available"):
        print(json.dumps({"update_available": False, "current_version": result.get("current_version", args.current_version)}, indent=2))
        return 0

    restart_navium(str(Path(args.app_dir) / args.restart_exe))
    print(json.dumps({"update_available": True, "latest_release_tag": result.get("latest_release_tag")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
