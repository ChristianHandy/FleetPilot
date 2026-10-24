"""Build the PDF editions of the guides from their Markdown sources.

    pip install markdown        # once
    python3 docs/user-guides/build_pdfs.py

Needs LibreOffice (soffice) for the HTML -> PDF step, and a font that covers
Chinese for the zh-CN guides (e.g. Noto Sans CJK; DejaVu Sans has no CJK glyphs).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.dirname(HERE)

GUIDES = [   # source, PDF name, language
    ("user-guide.md", "FleetPilot_User_Guide_EN.pdf", "en"),
    ("installation.md", "FleetPilot_Installation_EN.pdf", "en"),
    ("de/benutzerhandbuch.md", "FleetPilot_Handbuch_DE.pdf", "de"),
    ("de/installation.md", "FleetPilot_Installation_DE.pdf", "de"),
    ("zh-CN/user-guide.md", "FleetPilot_User_Guide_ZH.pdf", "zh-CN"),
    ("zh-CN/installation.md", "FleetPilot_Installation_ZH.pdf", "zh-CN"),
]

CSS = """
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1d2433; }
h1, h2, h3 { font-family: 'DejaVu Sans', Arial, sans-serif; }
h1 { font-size: 22pt; color: #12355b; border-bottom: 2px solid #2f6fb5; padding-bottom: 4pt; }
h2 { font-size: 15pt; color: #12355b; margin-top: 18pt; border-bottom: 1px solid #c9d6e6; }
h3 { font-size: 12pt; color: #1f4f82; margin-top: 12pt; }
code, pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.5pt; }
pre { background: #f2f5f9; border: 1px solid #d5dde8; padding: 6pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th, td { border: 1px solid #c9d6e6; padding: 3pt 5pt; vertical-align: top; font-size: 9pt; }
th { background: #e7eef7; }
a { color: #1f5fa8; }
"""

# DejaVu Sans has no Chinese characters, so the zh-CN guides ask for a CJK font first.
CJK_CSS = """
body, h1, h2, h3 { font-family: 'Noto Sans CJK SC', 'Noto Sans SC', 'Noto Sans CJK', 'DejaVu Sans', Arial, sans-serif; }
code, pre { font-family: 'Noto Sans Mono CJK SC', 'DejaVu Sans Mono', monospace; }
"""


def build(source, target, lang):
    with open(os.path.join(DOCS, source), encoding="utf-8") as fh:
        text = fh.read()
    # Links to other Markdown files are meaningless inside a PDF: keep the text only.
    text = re.sub(r"\[([^\]]+)\]\((?!https?:|#)[^)]+\)", r"\1", text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    title = re.search(r"^# (.+)$", text, re.M).group(1)
    extra = CJK_CSS if lang == "zh-CN" else ""
    html = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{CSS}{extra}</style></head><body>{body}</body></html>")
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, os.path.splitext(target)[0] + ".html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(html)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf:writer_web_pdf_Export",
                        "--outdir", tmp, page], check=True, capture_output=True, timeout=180)
        shutil.move(os.path.join(tmp, target), os.path.join(HERE, target))
    print("built", target)


if __name__ == "__main__":
    for source, target, lang in GUIDES:
        if len(sys.argv) == 1 or target in sys.argv[1:]:
            build(source, target, lang)
