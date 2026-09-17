"""Extract path data from crmloader.svg for static composition."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "lottiefiles" / "crmloader.svg"
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def find_by_id(elem, target_id):
    if elem.get("id") == target_id:
        return elem
    for child in elem:
        result = find_by_id(child, target_id)
        if result is not None:
            return result
    return None


def direct_paths(group):
    return [c for c in group if c.tag == f"{{{SVG_NS}}}path" or c.tag.endswith("path")]


def collect_paths(elem, parent_id=""):
    results = []
    gid = elem.get("id") or parent_id
    for child in elem:
        if child.tag == f"{{{SVG_NS}}}path" or child.tag.endswith("path"):
            d = child.get("d", "")
            if d:
                results.append(
                    {
                        "parent_id": gid,
                        "fill": child.get("fill", ""),
                        "fill_rule": child.get("fill-rule", ""),
                        "d": d,
                    }
                )
        else:
            results.extend(collect_paths(child, child.get("id") or gid))
    return results


def main():
    text = SRC.read_text(encoding="utf-8")
    root = ET.fromstring(text)

    i3 = find_by_id(root, "i3")
    i0 = find_by_id(root, "i0")

    print("=" * 80)
    print("PATH ELEMENTS IN CHARACTER GROUPS (i5, i6, i7, i8) + i2 placeholder in i3")
    print("=" * 80)

    for gid in ["i5", "i6", "i7", "i8", "i2"]:
        g = find_by_id(i3, gid) if i3 is not None else None
        if g is None:
            print(f"\n[{gid}] NOT FOUND")
            continue
        print(f"\n[{gid}] transform={g.get('transform', '(none)')}")
        paths = direct_paths(g)
        if not paths:
            print("  (no direct path children)")
        for i, p in enumerate(paths):
            d = p.get("d", "")
            print(f"  path[{i}] fill={p.get('fill', '(none)')} fill-rule={p.get('fill-rule', '')}")
            print(f"  d={'(empty)' if not d else d}")

    print("\n" + "=" * 80)
    print("i2 ORANGE BAR (animated group in i0/i1)")
    print("=" * 80)
    orange = find_by_id(i0, "i2") if i0 is not None else None
    if orange is not None:
        print(f"transform={orange.get('transform', '(none)')}")
        for i, p in enumerate(direct_paths(orange)):
            print(f"  path[{i}] fill={p.get('fill', '(none)')}")
            print(f"  d={p.get('d', '')}")

    print("\n" + "=" * 80)
    print("ALL NON-EMPTY PATHS IN i3 (character illustration)")
    print("=" * 80)
    if i3 is not None:
        all_paths = collect_paths(i3)
        print(f"Total: {len(all_paths)} paths\n")
        for idx, item in enumerate(all_paths, 1):
            print(f"--- Path {idx} | parent={item['parent_id']} | fill={item['fill']} ---")
            if item["fill_rule"]:
                print(f"fill-rule={item['fill_rule']}")
            print(item["d"])
            print()

    # Extract i3 transform chain (static/rest pose at keyframe 0.483334)
    print("=" * 80)
    print("i3 TRANSFORM CHAIN (from SVG structure + animation keyframe ~rest pose)")
    print("=" * 80)
    # Parse animateTransform values from raw text for i3 group
    i3_match = re.search(r'<g opacity="0" id="i3">(.*?)</g></svg>', text, re.S)
    if i3_match:
        i3_block = i3_match.group(1)
        transforms = re.findall(
            r'<g transform="([^"]*)"[^>]*>\s*<animateTransform[^>]*values="([^"]*)"',
            i3_block,
        )
        for i, (static_t, anim_vals) in enumerate(transforms):
            first_val = anim_vals.split(";")[0].strip()
            print(f"  layer[{i}] static transform attr: {static_t}")
            print(f"           animate first keyframe: {first_val}")

    print("\n" + "=" * 80)
    print("RECOMMENDED STATIC COMPOSE TRANSFORM (700x700 centered)")
    print("=" * 80)
    print(
        """
Rest-pose keyframe (~48.3% of 2s timeline) for character (i3):
  translate(351, 316.961)   # from i3 horizontal/vertical motion
  rotate(0)                 # settled rotation
  scale(2.13, 2.13)         # base scale (brief 2.23 pulse omitted for static)
  translate(-168.084, -159.726)  # artboard offset inside scaled group

Orange bar (i0) rest pose:
  translate(350.964, 350.816)  # vertical bounce at rest
  rotate(0)
  scale(2.13, 2.13) translate(-163.953, -163.883)
  + i2 local: matrix(1,0,0,1,164.387,182.382)

Suggested single wrapper for character paths (i3 inner content):
  transform=\"translate(351, 316.961) rotate(0) scale(2.13) translate(-168.084, -159.726)\"

Suggested single wrapper for orange bar (i0):
  transform=\"translate(350.964, 350.816) rotate(0) scale(2.13) translate(-163.953, -163.883)\"

ViewBox is already 0 0 700 700 — no extra centering transform needed.
Character and bar are positioned via the translate(350.x, 350.x) anchors near canvas center (350, 350).
"""
    )


if __name__ == "__main__":
    main()