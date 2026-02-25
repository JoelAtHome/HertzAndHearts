import argparse
import cProfile
import importlib.util
import subprocess
from pathlib import Path

APP_PATH = Path(__file__).with_name("app.py")
APP_SPEC = importlib.util.spec_from_file_location("hnh_profile_mock_app", APP_PATH)
if APP_SPEC is None or APP_SPEC.loader is None:
    raise RuntimeError(f"Could not load profiling mock app at {APP_PATH}")
APP_MODULE = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(APP_MODULE)
main = APP_MODULE.main


def run_profile(output: Path, open_viewer: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cProfile.runctx("main()", globals(), locals(), str(output))
    if open_viewer:
        subprocess.run(["snakeviz", str(output)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Profile the app startup/runtime with mock sensor input."
    )
    parser.add_argument(
        "--output",
        default="profiles/hnh.profile",
        help="Path to write cProfile output.",
    )
    parser.add_argument(
        "--no-view",
        action="store_true",
        help="Capture profile only; do not launch snakeviz.",
    )
    args = parser.parse_args()
    run_profile(Path(args.output), open_viewer=not args.no_view)
