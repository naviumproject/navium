import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.navium_updater_windows import check_for_update, run_update_flow


def find_navium_exe(app_dir: Path) -> Path:
    candidates = [
        app_dir / "navium.exe",
        app_dir / "navium",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"navium executable not found in {app_dir}")


def launch_navium(app_dir: str = ".", version_file: str = "navium_version.txt", check_only: bool = False) -> int:
    app_path = Path(app_dir).resolve()
    version_path = app_path / version_file

    status = check_for_update(str(version_path))
    print(json.dumps(status, indent=2))

    if check_only:
        return 0

    if status.get("update_available"):
        print("Update available. Applying update before launch...")
        result = run_update_flow(str(app_path), str(version_path))
        if result.get("updated"):
            print("Update installed successfully.")
        elif result.get("reason"):
            print(f"Update skipped: {result['reason']}")

    exe = find_navium_exe(app_path)
    try:
        subprocess.Popen([str(exe)], cwd=str(app_path), shell=False)
        print(f"Launched: {exe}")
        return 0
    except Exception as exc:  # pragma: no cover - platform/runtime error path
        print(f"Failed to launch navium: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch navium and check for stable updates first.")
    parser.add_argument("--app-dir", default=".", help="Directory containing navium.exe and navium_version.txt")
    parser.add_argument("--version-file", default="navium_version.txt", help="Version file to read and update")
    parser.add_argument("--check-only", action="store_true", help="Only check the update status and exit")
    args = parser.parse_args()
    return launch_navium(args.app_dir, args.version_file, args.check_only)


if __name__ == "__main__":
    sys.exit(main())
