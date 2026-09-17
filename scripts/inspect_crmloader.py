import re
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "app" / "lottiefiles" / "crmloader.svg"
text = SRC.read_text(encoding="utf-8")
root = ET.fromstring(text)

ids = []
for el in root.iter():
    if el.get("id"):
        ids.append(el.get("id"))
print("All ids:", ids)

# i3 animation keyframes from raw text
m = re.search(r'id="i3"[^>]*>.*?translate\(54\.764,341\.961\)"[^>]*values="([^"]+)"', text, re.S)
if m:
    print("\ni3 translate keyframes:", m.group(1))

m2 = re.search(r'translate\(54\.764,341\.961\)".*?rotate\(-7\)".*?values="([^"]+)"', text, re.S)
if m2:
    print("i3 rotate keyframes:", m2.group(1))

m3 = re.search(r'scale\(2\.13,2\.13\)".*?values="([^"]+)"', text, re.S)
# first scale in i3
idx = text.find('id="i3"')
sub = text[idx:idx+5000]
for pat, name in [
    (r'translate\(54\.764,341\.961\)".*?values="([^"]+)"', 'translate'),
    (r'rotate\(-7\)".*?values="([^"]+)"', 'rotate'),
    (r'scale\(2\.13,2\.13\)".*?values="([^"]+)"', 'scale'),
]:
    m = re.search(pat, sub, re.S)
    if m:
        vals = [v.strip() for v in m.group(1).split(';')]
        print(f"i3 {name} keyframes ({len(vals)}): {vals}")

# top-level groups
for child in root:
    tag = child.tag.split('}')[-1]
    print(f"top-level <{tag}> id={child.get('id')} opacity={child.get('opacity')}")