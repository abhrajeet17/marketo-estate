"""Build a complete, performant static CRM loader SVG from the Lottie export."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "lottiefiles" / "crmloader.svg"
OUT = ROOT / "app" / "lottiefiles" / "crmloader-smooth.svg"

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

COLOR_MAP = {
    "#002348": "#333333",
    "#ffa330": "#FFA300",
    "#ffa300": "#FFA300",
}

REST_OVERRIDES = {
    "translate(54.764,341.961)": "translate(351,316.961)",
    "rotate(-7)": "rotate(0)",
}

EYEBROW_D = {
    "i13": "M-103,155C-103,155,40,155,40,155",
    "i15": "M-103,155C-103,155,-20.4,155,-20.4,155",
}


def map_color(value: str | None) -> str | None:
    if not value:
        return value
    return COLOR_MAP.get(value.lower(), value)


def is_anim_tag(tag: str) -> bool:
    return tag.endswith(("animate", "animateTransform", "set"))


def normalize_transform(value: str | None) -> str | None:
    if not value:
        return None
    return REST_OVERRIDES.get(value, value)


def path_attrs(elem: ET.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key in ("d", "fill", "fill-rule", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"):
        val = elem.get(key)
        if not val:
            continue
        if key in ("fill", "stroke"):
            val = map_color(val) or val
        attrs[key] = val
    return attrs


def render_path(elem: ET.Element, indent: int) -> str | None:
    attrs = path_attrs(elem)
    d = attrs.get("d", "")
    if not d:
        return None
    parts = [f'{" " * indent}<path']
    for key, val in attrs.items():
        parts.append(f' {key}="{val}"')
    parts.append("/>")
    return "".join(parts)


def collect_paths(group: ET.Element) -> list[tuple[list[str], str]]:
    output: list[tuple[list[str], str]] = []
    skip_stroke_eyebrows = False

    def inner(elem: ET.Element, chain: list[str]) -> None:
        nonlocal skip_stroke_eyebrows
        t = normalize_transform(elem.get("transform"))
        chain = chain + ([t] if t else [])
        tag = elem.tag.split("}")[-1]
        gid = elem.get("id")

        if gid in ("i13", "i15"):
            pad = 4 + len(chain)
            output.append(
                (
                    chain,
                    f'{" " * pad}<path d="{EYEBROW_D[gid]}" stroke="#333333" '
                    f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
                )
            )
            skip_stroke_eyebrows = True
            for child in elem:
                if is_anim_tag(child.tag.split("}")[-1]):
                    continue
                inner(child, chain)
            skip_stroke_eyebrows = False
            return

        if tag == "path":
            attrs = path_attrs(elem)
            if skip_stroke_eyebrows and attrs.get("stroke") and not attrs.get("fill"):
                return
            line = render_path(elem, indent=4 + len(chain))
            if line:
                output.append((chain, line))
            return

        for child in elem:
            if is_anim_tag(child.tag.split("}")[-1]):
                continue
            inner(child, chain)

    inner(group, [])
    return output


def wrap_paths(path_entries: list[tuple[list[str], str]]) -> list[str]:
    lines: list[str] = []
    for chain, path_line in path_entries:
        lines.append("  <g>")
        for t in chain:
            lines.append(f'    <g transform="{t}">')
        lines.append(path_line)
        for _ in chain:
            lines.append("    </g>")
        lines.append("  </g>")
    return lines


def top_children(root: ET.Element, target_id: str) -> list[ET.Element]:
    return [child for child in root if child.get("id") == target_id]


def main() -> None:
    root = ET.fromstring(SRC.read_text(encoding="utf-8"))
    i0_groups = top_children(root, "i0")

    layers: list[tuple[list[str], str]] = []

    # 1) Orange bar (first i0 group).
    if i0_groups:
        layers.extend(collect_paths(i0_groups[0]))

    # 2) Character body.
    i3_groups = top_children(root, "i3")
    if i3_groups:
        layers.extend(collect_paths(i3_groups[0]))

    # 3) Head, collar, glasses, eyebrows (remaining i0 groups).
    for head_group in i0_groups[1:]:
        layers.extend(collect_paths(head_group))

    # 4) Eye accent strokes.
    for eye_id in ("i18", "i19", "i20"):
        for group in top_children(root, eye_id):
            layers.extend(collect_paths(group))

    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 700" fill="none" role="img" aria-hidden="true">',
    ]
    body.extend(wrap_paths(layers))
    body.append("</svg>")

    OUT.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, {len(layers)} paths)")


if __name__ == "__main__":
    main()