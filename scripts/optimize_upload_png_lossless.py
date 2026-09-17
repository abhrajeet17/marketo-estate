import argparse
import os
from pathlib import Path

from PIL import Image


def optimize_png_in_place(path: Path) -> bool:
    try:
        before = path.stat().st_size
    except Exception:
        return False

    try:
        img = Image.open(path)
    except Exception:
        return False

    if (img.format or "").upper() != "PNG":
        return False

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        img.save(tmp, format="PNG", optimize=True, compress_level=9)
        after = tmp.stat().st_size
        if after and before and after < before:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
        return False
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="uploads", help="Directory to optimize (default: uploads)")
    args = ap.parse_args()

    root = Path(args.dir)
    if not root.exists() or not root.is_dir():
        return 2

    changed = 0
    seen = 0
    for p in root.rglob("*.png"):
        seen += 1
        if optimize_png_in_place(p):
            changed += 1

    print(f"Optimized {changed}/{seen} PNG files (lossless).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
