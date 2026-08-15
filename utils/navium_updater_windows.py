import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib import error, request


GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/naviumproject/navium/releases/latest"
SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(version: str):
    cleaned = str(version).strip().lower()
    if cleaned.startswith('v'):
        cleaned = cleaned[1:]
    match = SEMVER_RE.match(cleaned)
    if not match:
        raise ValueError(f"Invalid semantic version: {version!r}")
    return tuple(int(part) for part in match.groups())


def should_update(current_version: str, latest_release_tag: str | None) -> bool:
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


def fetch_latest_stable_release() -> dict | None:
    req = request.Request(
        GITHUB_LATEST_RELEASE_URL,
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
    return Path(version_file_path).read_text(encoding="utf-8").strip()


def get_zip_asset_url(release_payload: dict | None) -> str | None:
    if not release_payload:
        return None
    for asset in release_payload.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".zip") and "source" not in name:
            return asset.get("browser_download_url")
    return None


def download_file(url: str, destination: Path) -> Path:
    req = request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "navium-updater",
        },
    )
    with request.urlopen(req, timeout=60) as response, open(destination, "wb") as out:
        shutil.copyfileobj(response, out)
    return destination


def extract_zip(zip_path: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target_dir)
    return target_dir


def find_release_root(root_dir: Path) -> Path:
    dirs = [root_dir] + [p for p in root_dir.iterdir() if p.is_dir()]
    for candidate in dirs:
        if (candidate / "navium.exe").exists():
            return candidate
    return root_dir


def install_update(app_dir: Path, zip_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="navium-update-") as tmp_dir:
        extracted = extract_zip(zip_path, Path(tmp_dir))
        root = find_release_root(extracted)

        for item in root.iterdir():
            target = app_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                if target.exists() or target.is_symlink():
                    target.unlink()
                shutil.copy2(item, target)


def check_for_update(version_file_path: str = "navium_version.txt") -> dict:
    installed = get_installed_version(version_file_path)
    release = fetch_latest_stable_release()
    tag = release.get("tag_name") if release else None
    return {
        "current_version": installed,
        "latest_release_tag": tag,
        "update_available": should_update(installed, tag),
        "zip_url": get_zip_asset_url(release),
    }


def run_update_flow(app_dir: str = ".", version_file_path: str = "navium_version.txt") -> dict:
    status = check_for_update(version_file_path)
    if not status["update_available"]:
        return status

    zip_url = status.get("zip_url")
    if not zip_url:
        status["update_available"] = False
        status["reason"] = "No stable zip asset found."
        return status

    with tempfile.TemporaryDirectory(prefix="navium-download-") as tmp_dir:
        zip_path = Path(tmp_dir) / "navium-update.zip"
        download_file(zip_url, zip_path)
        install_update(Path(app_dir), zip_path)

    Path(version_file_path).write_text(str(status["latest_release_tag"]).lstrip("v"), encoding="utf-8")
    status["updated"] = True
    return status


def prompt_restart(executable_path: str = "navium.exe") -> None:
    try:
        subprocess.Popen([executable_path], shell=False)
    except Exception:
        pass


if __name__ == "__main__":
    result = run_update_flow()
    print(json.dumps(result, indent=2))
