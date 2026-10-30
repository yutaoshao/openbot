"""Fixed entrypoint for the Python service owned by the native desktop host."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--resource-dir", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.resource_dir.resolve(strict=True)
    if not Path(sys.executable).resolve().is_relative_to(runtime):
        parser.error("The service must use the Python interpreter inside its runtime.")
    source_root = runtime / "app"
    if not (source_root / "src" / "desktop" / "launcher.py").is_file():
        parser.error("The packaged desktop service is missing; rebuild the runtime.")
    # This must precede all OpenBot imports. Desktop never searches parent .env files.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["TIKTOKEN_CACHE_DIR"] = str(runtime / "tokenizer-cache")
    sys.path.insert(0, str(source_root))
    from src.desktop.launcher import run

    return run(args.data_dir, args.ready_file, runtime)


if __name__ == "__main__":
    raise SystemExit(main())
