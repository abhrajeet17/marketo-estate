import xml.etree.ElementTree as ET
from pathlib import Path

root = ET.fromstring(Path("app/lottiefiles/crmloader.svg").read_text(encoding="utf-8"))


def tree(elem, depth=0):
    tag = elem.tag.split("}")[-1]
    gid = elem.get("id", "")
    label = f"{tag}" + (f'#{gid}' if gid else "")
    d = elem.get("d", "")
    extra = ""
    if d:
        extra = f" d_len={len(d)} fill={elem.get('fill','')}"
    print("  " * depth + label + extra)
    for child in elem:
        if child.tag.split("}")[-1] not in ("animate", "animateTransform", "set"):
            tree(child, depth + 1)


i0s = [c for c in root if c.get("id") == "i0"]
for idx, g in enumerate(i0s):
    print(f"\n=== i0[{idx}] ===")
    tree(g)