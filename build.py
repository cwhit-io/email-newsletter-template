#!/usr/bin/env python3
"""Inline CSS from styles.css into base.html using premailer, outputting template.html."""

import os
import re

from io import StringIO

import lxml.html
from lxml.html import html5parser
from premailer import Premailer

DIR = os.path.dirname(os.path.abspath(__file__))

html_path = os.path.join(DIR, "base.html")
css_path = os.path.join(DIR, "styles.css")
output_path = os.path.join(DIR, "template.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

with open(css_path, "r", encoding="utf-8") as f:
    css_content = f.read()

# Strip Google Fonts @import — not needed in email and Premailer will try to
# fetch them, slowing things down and causing warnings.
css_content = re.sub(
    r"@import\s+url\(['\"]?https?://fonts\.googleapis\.com[^)]*['\"]?\);?\s*",
    "",
    css_content,
)

# Parse HTML with html5lib so that <a> wrapping <table> is preserved
# (lxml's default HTML4 parser would restructure the DOM).
# Use namespaceHTMLElements=False to prevent stripping xmlns:o / xmlns:v.
parser = html5parser.HTMLParser(namespaceHTMLElements=False)
doc = parser.parse(StringIO(html_content)).getroot()

p = Premailer(
    html=doc,
    css_text=css_content,
    remove_classes=False,
    strip_important=False,
    exclude_pseudoclasses=False,
)

result_tree = p.transform()

# Serialize the result tree to an HTML string
result = lxml.html.tostring(result_tree, encoding="unicode", method="html")

# --- Post-processing fixes ---

# 1. Restore xmlns:o and xmlns:v that html5lib mangled (to xmlnsU0003Ao etc.) or stripped
result = re.sub(r'\s+xmlnsU0003A[oov]="[^"]*"', '', result)
result = re.sub(
    r'(<html\b[^>]*)(>)',
    r'\1 xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:v="urn:schemas-microsoft-com:vml">',
    result,
)

# 2. Restore HTML entities that Premailer decoded to raw characters
result = result.replace("\u200c", "&zwnj;")   # zero-width non-joiner
result = result.replace("\u00a0", "&nbsp;")    # non-breaking space

# 3. Restore trailing semicolons stripped by cssutils inside <style> tags
#    (only where they were removed before a closing brace)
def fix_style_semicolons(match):
    content = match.group(1)
    # Add missing semicolons before closing braces
    content = re.sub(r'(?<=[a-z0-9)])\s*}', ';\\g<0>', content, flags=re.IGNORECASE)
    return f"<style type=\"text/css\">{content}</style>"

result = re.sub(
    r'<style type="text/css">(.*?)</style>',
    fix_style_semicolons,
    result,
    flags=re.DOTALL,
)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(result)

print(f"Inlined CSS written to {output_path}")
