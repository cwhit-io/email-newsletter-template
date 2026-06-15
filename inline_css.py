#!/usr/bin/env python3
"""Inline CSS from styles.css into base.html using premailer, outputting template.html."""

import os
from premailer import Premailer

DIR = os.path.dirname(os.path.abspath(__file__))

html_path = os.path.join(DIR, "base.html")
css_path = os.path.join(DIR, "styles.css")
output_path = os.path.join(DIR, "template.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

with open(css_path, "r", encoding="utf-8") as f:
    css_content = f.read()

# Preserve the @import rule (Google Fonts) — premailer strips it by default
# We'll keep it in a <style> tag instead of inlining it
p = Premailer(
    html=html_content,
    css_text=css_content,
    remove_classes=False,
    strip_important=False,
    exclude_pseudoclasses=False,
)

result = p.transform()

with open(output_path, "w", encoding="utf-8") as f:
    f.write(result)

print(f"Inlined CSS written to {output_path}")
