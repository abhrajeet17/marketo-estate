import re
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "lottiefiles" / "crmloader.svg"
root = ET.fromstring(SRC.read_text(encoding="utf-8"))

for el in root.iter():
    if not el.tag.endswith("path"):
        continue
    d = el.get("d", "")
    if not d:
        continue
    pid = el.get("id", "")
    parent = None
    # find parent id by walking
    for p in root.iter():
        for c in p:
            if c is el:
                parent = p.get("id", "")
    attrs = {k: el.get(k) for k in el.attrib}
    print(attrs)
    print()