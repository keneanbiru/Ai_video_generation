"""Minimal Markdown -> .docx for the report (headings, paragraphs, bullets, numbered lists, **bold**, `code`, > quotes)."""
import re
import sys

from docx import Document
from docx.shared import Pt, RGBColor


def add_runs(par, text):
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)", text):
        if not part:
            continue
        if part.startswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`"):
            r = par.add_run(part[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(9.5)
        elif part.startswith("*") and len(part) > 2:
            par.add_run(part[1:-1]).italic = True
        else:
            par.add_run(part)


def convert(src, dst):
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)
    for line in open(src, encoding="utf-8").read().splitlines():
        s = line.rstrip()
        if not s:
            continue
        if s.startswith("#"):
            lvl = len(s) - len(s.lstrip("#"))
            doc.add_heading(s.lstrip("#").strip(), level=min(lvl - 1, 3) if lvl > 1 else 0)
        elif re.match(r"^\s*[*-] ", s):
            add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[*-] ", "", s))
        elif re.match(r"^\s*\d+\. ", s):
            add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\s*\d+\. ", "", s))
        elif s.startswith(">"):
            p = doc.add_paragraph(); add_runs(p, s.lstrip("> "))
            for r in p.runs:
                r.font.color.rgb = RGBColor(0xB0, 0x30, 0x20)
        else:
            add_runs(doc.add_paragraph(), s)
    doc.save(dst)


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
