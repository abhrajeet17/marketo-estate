"""List all paths in crmloader.svg with full transform chain."""
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "lottiefiles" / "crmloader.svg"


def walk(elem, chain=None, transforms=None):
    chain = chain or []
    transforms = transforms or []
    gid = elem.get("id")
    if gid:
        chain = chain + [gid]
    t = elem.get("transform")
    if t:
        transforms = transforms + [t]
    if elem.tag.endswith("path"):
        d = elem.get("d", "")
        if d:
            print(f"chain={' > '.join(chain)}")
            print(f"  fill={elem.get('fill','') or '(none)'}")
            print(f"  transforms={' | '.join(transforms)}")
            print(f"  d_len={len(d)}")
            print()
    for child in elem:
        walk(child, chain, transforms)


root = ET.fromstring(SRC.read_text(encoding="utf-8"))
print("=== ALL NON-EMPTY PATHS ===\n")
for child in root:
    walk(child)