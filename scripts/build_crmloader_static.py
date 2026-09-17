import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / 'app' / 'lottiefiles' / 'crmloader.svg'
out = ROOT / 'app' / 'lottiefiles' / 'crmloader-static.svg'

text = src.read_text(encoding='utf-8')
text = re.sub(r'<animate(?:Transform)?\b[^>]*/>', '', text, flags=re.I)
text = re.sub(
    r'<animate(?:Transform)?\b[^>]*>.*?</animate(?:Transform)?>',
    '',
    text,
    flags=re.I | re.S,
)
text = text.replace('opacity="0" id="i3"', 'opacity="1" id="i3"')
out.write_text(text, encoding='utf-8')
print(f'Wrote {out} ({out.stat().st_size} bytes)')