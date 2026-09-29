"""Build HTML deliverables (quotes, newsletters, reports). Owned by the main agent.

The model supplies content as Markdown; the template supplies the branding. Keeping the
layout in code means every quote and report looks the same, and the model spends its
tokens on substance rather than CSS. Files land in ``output/`` so a person can open them
in a browser, attach them to an email, or diff them in git.
"""

from __future__ import annotations

import html
import re
from datetime import date

from langchain.tools import tool

from config import OUTPUT_DIR

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ --ink: #1d2430; --muted: #5b6573; --line: #e3e7ee; --accent: #1f6feb; --bg: #ffffff; }}
  body {{ margin: 0; background: #f4f6f9; color: var(--ink); font: 15px/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
  main {{ max-width: 860px; margin: 32px auto; background: var(--bg); border: 1px solid var(--line); border-radius: 12px; padding: 40px 48px; }}
  header {{ border-bottom: 3px solid var(--accent); padding-bottom: 14px; margin-bottom: 26px; }}
  header h1 {{ margin: 0 0 4px; font-size: 26px; }}
  header .sub {{ color: var(--muted); }}
  h2 {{ font-size: 18px; margin: 28px 0 8px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); }}
  th {{ background: #f7f9fc; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  img {{ max-width: 100%; border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; }}
  footer {{ margin-top: 32px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 10px; }}
</style></head>
<body><main>
<header><h1>{title}</h1><div class="sub">{subtitle}</div></header>
{body}
<footer>Chinook Sales Assistant &middot; generated {today}</footer>
</main></body></html>
"""


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _is_num(cell: str) -> bool:
    return bool(re.fullmatch(r"[$€£]?-?[\d,]+(\.\d+)?%?", cell.strip()))


def markdown_to_html(md: str) -> str:
    """A small Markdown subset: headings, paragraphs, bullet lists, pipe tables, images."""
    out: list[str] = []
    lines = md.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 3)
            out.append(f"<h{level + 1}>{_inline(line.lstrip('#').strip())}</h{level + 1}>")
            i += 1
        elif line.lstrip().startswith(("- ", "* ")):
            out.append("<ul>")
            while i < len(lines) and lines[i].lstrip().startswith(("- ", "* ")):
                out.append(f"<li>{_inline(lines[i].lstrip()[2:].strip())}</li>")
                i += 1
            out.append("</ul>")
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                head, body = rows[0], rows[1:]
                out.append("<table><thead><tr>" + "".join(
                    f"<th class=\"{'num' if body and all(_is_num(r[k]) for r in body if k < len(r)) else ''}\">{_inline(h)}</th>"
                    for k, h in enumerate(head)) + "</tr></thead><tbody>")
                for r in body:
                    out.append("<tr>" + "".join(
                        f"<td class=\"{'num' if _is_num(c) else ''}\">{_inline(c)}</td>" for c in r) + "</tr>")
                out.append("</tbody></table>")
        elif m := re.fullmatch(r"!\[(.*?)\]\((.+?)\)", line.strip()):
            out.append(f'<img alt="{html.escape(m.group(1))}" src="{html.escape(m.group(2))}">')
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "- ", "* ", "![")):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip("-") or "report"
    return name if name.endswith(".html") else f"{name}.html"


@tool
def write_html_report(filename: str, title: str, subtitle: str, body_markdown: str) -> str:
    """Save a branded HTML deliverable (quote, newsletter, report) to output/<filename>.html.

    Write the body in Markdown: '## Heading', paragraphs, '- bullets', pipe tables
    ('| col | col |' with a '|---|---|' separator row) and images by relative file name
    ('![Sales by country](territory-jane.png)' for a chart rendered with render_bar_chart).
    Put exact figures from your specialists in tables; never invent numbers. Returns the path
    of the file so you can tell the user where to open it.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / _safe_name(filename)
    page = _TEMPLATE.format(
        title=html.escape(title),
        subtitle=html.escape(subtitle),
        body=markdown_to_html(body_markdown),
        today=date.today().isoformat(),
    )
    path.write_text(page, encoding="utf-8")
    return f"Saved {path} ({len(page):,} bytes). Open it with: open {path}"


HTML_TOOLS = [write_html_report]
