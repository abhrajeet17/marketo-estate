"""Inspect opacity/animation on eye groups."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "lottiefiles" / "crmloader.svg"
text = SRC.read_text(encoding="utf-8")

for gid in ["i18", "i19", "i20", "i13", "i15"]:
    idx = text.find(f'id="{gid}"')
    if idx < 0:
        print(f"{gid}: NOT FOUND")
        continue
    chunk = text[idx : idx + 2500]
    print(f"\n=== {gid} ===")
    print(chunk[:800])
    anims = re.findall(r'<animate[^>]*attributeName="([^"]*)"[^>]*values="([^"]*)"', chunk)
    for attr, vals in anims:
        print(f"  {attr}: {vals}")