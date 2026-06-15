#!/usr/bin/env python3
"""Build the email newsletter template.

1. Inline CSS from styles.css into base.html using premailer.
2. Fetch live sermon data from the ScriptDash API.
3. Replace placeholders in the inlined HTML with real data.
"""

import os
import re
import json
import sys

from io import StringIO

import lxml.html
from lxml.html import html5parser
from premailer import Premailer

try:
    from dotenv import load_dotenv
    import requests
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DIR = os.path.dirname(os.path.abspath(__file__))
html_path = os.path.join(DIR, "base.html")
css_path = os.path.join(DIR, "styles.css")
output_path = os.path.join(DIR, "template.html")
env_path = os.path.join(DIR, ".env")
api_url = "https://scriptdash.bhm.li/api/v1/scripts/15/execute"

# GitHub raw URLs for sourcing the freshest files
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/cwhit-io/email-newsletter-template/main"
github_html_url = f"{GITHUB_RAW_BASE}/base.html"
github_css_url = f"{GITHUB_RAW_BASE}/styles.css"

# ---------------------------------------------------------------------------
# Bible book name → bible.com abbreviation mapping
# ---------------------------------------------------------------------------
BOOK_ABBR_MAP = {
    "genesis": "GEN", "exodus": "EXO", "leviticus": "LEV", "numbers": "NUM",
    "deuteronomy": "DEU", "joshua": "JOS", "judges": "JDG", "ruth": "RUT",
    "i samuel": "1SA", "ii samuel": "2SA", "i kings": "1KI", "ii kings": "2KI",
    "i chronicles": "1CH", "ii chronicles": "2CH", "ezra": "EZR", "nehemiah": "NEH",
    "esther": "EST", "job": "JOB", "psalms": "PSA", "psalm": "PSA",
    "proverbs": "PRO", "ecclesiastes": "ECC", "song of solomon": "SNG",
    "isaiah": "ISA", "jeremiah": "JER", "lamentations": "LAM", "ezekiel": "EZK",
    "daniel": "DAN", "hosea": "HOS", "joel": "JOL", "amos": "AMO",
    "obadiah": "OBA", "jonah": "JON", "micah": "MIC", "nahum": "NAH",
    "habakkuk": "HAB", "zephaniah": "ZEP", "haggai": "HAG", "zechariah": "ZEC",
    "malachi": "MAL",
    "matthew": "MAT", "mark": "MRK", "luke": "LUK", "john": "JHN",
    "acts": "ACT", "romans": "ROM", "i corinthians": "1CO", "ii corinthians": "2CO",
    "galatians": "GAL", "ephesians": "EPH", "philippians": "PHP", "colossians": "COL",
    "i thessalonians": "1TH", "ii thessalonians": "2TH", "i timothy": "1TI",
    "ii timothy": "2TI", "titus": "TIT", "philemon": "PHM", "hebrews": "HEB",
    "james": "JAS", "i peter": "1PE", "ii peter": "2PE", "i john": "1JN",
    "ii john": "2JN", "iii john": "3JN", "jude": "JUD", "revelation": "REV",
}


def _normalize_book(name: str) -> str:
    """Convert a book name like 'I Samuel' or '1 Samuel' to a bible.com code."""
    # Normalise whitespace and lowercase
    key = name.strip().lower()
    # Replace unicode/mixed roman numerals
    key = key.replace("ⅰ", "i").replace("ⅱ", "ii").replace("ⅲ", "iii")
    key = key.replace("ⅳ", "iv").replace("ⅴ", "v").replace("ⅵ", "vi")
    # "1st" / "2nd" style -> "i" / "ii"
    key = re.sub(r"^\d+\s+", lambda m: {"1": "i ", "2": "ii ", "3": "iii "}.get(m.group(0).strip(), m.group(0)), key)
    key = re.sub(r"^(\d)(st|nd|rd|th)\s+", r"\1 ", key)
    if key in BOOK_ABBR_MAP:
        return BOOK_ABBR_MAP[key]
    # Try stripping leading numbers: "1 samuel" -> "i samuel"
    key2 = re.sub(r"^\d\s+", lambda m: {"1": "i ", "2": "ii ", "3": "iii "}.get(m.group(0).strip(), m.group(0)), key)
    if key2 in BOOK_ABBR_MAP:
        return BOOK_ABBR_MAP[key2]
    # Last-ditch: try exact match after stripping the number prefix entirely
    key3 = re.sub(r"^(i|ii|iii|iv|v|vi|1|2|3|4|5)\s+", "", key)
    if key3 in BOOK_ABBR_MAP:
        return BOOK_ABBR_MAP[key3]
    return ""


def parse_sermon_title(title: str):
    """Parse a title like 'I Samuel 18:1-5' into (book_abbr, chapter, start_verse)."""
    # Pattern: optional book prefix, then "Chapter:Verse" or "Chapter"
    m = re.match(
        r"^(.+?)\s+(\d+)(?::(\d+)(?:[–—-]\d+)?)?\s*$",
        title.strip(),
    )
    if not m:
        return None, None, None
    book_name = m.group(1).strip()
    chapter = m.group(2)
    start_verse = m.group(3) or "1"
    book_abbr = _normalize_book(book_name)
    return book_abbr, chapter, start_verse


def build_bible_url(book_abbr: str, chapter: str, verse: str) -> str:
    """Build a bible.com URL for the passage."""
    return f"https://www.bible.com/bible/59/{book_abbr}.{chapter}.{verse}.ESV"


def escape_html(text: str) -> str:
    """Escape text for safe inclusion in HTML."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            )


# ---------------------------------------------------------------------------
# Phase 1 — Inline CSS
# ---------------------------------------------------------------------------
def inline_css(html_content: str, css_content: str) -> str:
    """Run premailer to inline CSS and return the resulting HTML string."""
    # Strip Google Fonts @import
    css_content = re.sub(
        r"@import\s+url\(['\"]?https?://fonts\.googleapis\.com[^)]*['\"]?\);?\s*",
        "",
        css_content,
    )

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
    result = lxml.html.tostring(result_tree, encoding="unicode", method="html")

    # Post-processing fixes ---------------------------------------------------
    # 1. Restore xmlns:o / xmlns:v
    result = re.sub(r'\s+xmlnsU0003A[oov]="[^"]*"', "", result)
    result = re.sub(
        r'(<html\b[^>]*)(>)',
        r'\1 xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:v="urn:schemas-microsoft-com:vml">',
        result,
    )
    # 2. Restore entities
    result = result.replace("\u200c", "&zwnj;")
    result = result.replace("\u00a0", "&nbsp;")
    # 3. Fix missing semicolons in <style> blocks
    def fix_style_semicolons(match):
        content = match.group(1)
        content = re.sub(r'(?<=[a-z0-9)])\s*}', ';\\g<0>', content, flags=re.IGNORECASE)
        return f"<style type=\"text/css\">{content}</style>"

    result = re.sub(
        r'<style type="text/css">(.*?)</style>',
        fix_style_semicolons,
        result,
        flags=re.DOTALL,
    )
    return result


# ---------------------------------------------------------------------------
# Phase 2 — Fetch API data
# ---------------------------------------------------------------------------
def fetch_sermon_data():
    """Fetch sermon data from the ScriptDash API. Returns dict or None."""
    load_dotenv(env_path)
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("⚠️  No API_KEY found in .env", file=sys.stderr)
        return None

    try:
        resp = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as exc:
        print(f"⚠️  API request failed: {exc}", file=sys.stderr)
        return None
    except ValueError:
        print("⚠️  API returned non-JSON response", file=sys.stderr)
        return None

    if body.get("status") != "success":
        print(f"⚠️  API script status: {body.get('status')} — {body.get('stderr', '')[:200]}", file=sys.stderr)
        return None

    stdout_str = body.get("stdout", "")
    if not stdout_str:
        print("⚠️  API returned empty stdout", file=sys.stderr)
        return None

    try:
        data = json.loads(stdout_str)
    except json.JSONDecodeError as exc:
        print(f"⚠️  Failed to parse API stdout as JSON: {exc}", file=sys.stderr)
        return None

    return data


# ---------------------------------------------------------------------------
# Phase 3 — Build replacement blocks from API data
# ---------------------------------------------------------------------------
def build_blocks(data: dict) -> dict:
    """Build HTML blocks to replace each placeholder."""
    sources = data.get("sources", {})
    sermon = sources.get("sermon", {}).get("data", {})
    youtube = sources.get("youtube", {})
    facebook = sources.get("facebook", {})
    instagram = sources.get("instagram", {})

    sermon_title = (sermon.get("title") or "").strip()
    description = (sermon.get("description") or "").strip()
    church_center_link = (sermon.get("url") or "").strip()
    video_thumbnail = (sermon.get("thumbnail") or "").strip()
    video_url = (sermon.get("video_url") or "").strip()
    resources = sermon.get("resources") or []

    yt_url = (youtube.get("url") or "").strip()
    yt_thumb = (youtube.get("thumbnail") or "").strip()
    fb_url = (facebook.get("url") or "").strip()
    ig_url = (instagram.get("url") or "").strip()

    book_abbr, chapter, start_verse = parse_sermon_title(sermon_title)
    bible_url = build_bible_url(book_abbr, chapter, start_verse) if book_abbr else ""

    # -- PREHEADER_TEXT -------------------------------------------------------
    if sermon_title:
        preheader = f"Watch this week's message from Blackhawk Ministries: {sermon_title}"
        if description:
            preheader += f" — {description}"
        preheader += "."
    else:
        preheader = "Watch this week's message from Blackhawk Ministries."
    preheader = escape_html(preheader)

    # -- SCRIPTURE_LINK_BLOCK -------------------------------------------------
    if bible_url and sermon_title:
        scripture_link_block = (
            f'<a href="{bible_url}" target="_blank" '
            f'class="scripture-link" '
            f'style="display:inline-block; font-size:13px; font-weight:700; '
            f'color:#00819e !important; letter-spacing:0.5px; '
            f'border-bottom:2px solid #00819e; padding-bottom:1px; '
            f'margin:0 0 24px 0; text-decoration:none !important;">\n'
            f'  📖 {escape_html(sermon_title)} — Read on Bible.com →\n'
            f"</a>"
        )
    else:
        scripture_link_block = ""

    # -- SUMMARY_TEXT_BLOCK ---------------------------------------------------
    if description:
        summary_text_block = (
            f'<p class="summary-theme" '
            f'style="font-size:15px; color:#4a5568; line-height:24px; '
            f'margin:0 0 24px 0; padding:0; font-style:italic;">'
            f'{escape_html(description)}'
            f"</p>"
        )
    else:
        summary_text_block = ""

    # -- KEY_POINTS_BLOCK -----------------------------------------------------
    # The API may not provide key points yet, so leave as placeholder if missing.
    key_points = data.get("key_points")
    if key_points and isinstance(key_points, list):
        items_html = ""
        for i, kp in enumerate(key_points, 1):
            text = escape_html(kp.get("text", kp) if isinstance(kp, dict) else str(kp))
            items_html += (
                f'<div class="key-point-row" style="margin:0 0 12px 0;">\n'
                f'  <span class="key-point-number" '
                f'style="display:inline-block; width:28px; height:28px; '
                f'background-color:#00819e; color:#ffffff; font-size:13px; '
                f'font-weight:900; text-align:center; line-height:28px; '
                f'border-radius:50%; margin-right:10px; vertical-align:middle;">'
                f"{i}</span>\n"
                f'  <span class="key-point-text" '
                f'style="font-size:15px; font-weight:700; color:#1a202c; '
                f'vertical-align:middle;">{text}</span>\n'
                f"</div>\n"
            )
        key_points_block = (
            f'<hr class="divider" '
            f'style="border:none; border-top:1px solid #e2e8f0; '
            f'margin:0 0 20px 0;">\n'
            f'<p class="key-points-header" '
            f'style="font-size:13px; font-weight:700; letter-spacing:2px; '
            f'text-transform:uppercase; color:#718096; '
            f'margin:0 0 12px 0; padding:0;">Key Points</p>\n'
            f"{items_html}"
        )
    else:
        key_points_block = "{{KEY_POINTS_BLOCK}}"

    # -- RESOURCES_SECTION ----------------------------------------------------
    if resources:
        rows_html = ""
        for res in resources:
            res_url = (res.get("url") or "").strip()
            res_thumb = (res.get("thumbnail") or res.get("image") or "").strip()
            res_title = escape_html(res.get("title") or "Resource")
            if res_thumb:
                rows_html += (
                    f'<table role="presentation" width="100%" cellpadding="0" '
                    f'cellspacing="0" border="0" style="margin:0 0 16px 0;">\n'
                    f"  <tr>\n"
                    f'    <td width="25%"></td>\n'
                    f'    <td class="resource-col" width="50%" valign="top">\n'
                    f'      <a href="{res_url}" target="_blank" '
                    f'style="display:block; text-decoration:none;">\n'
                    f'        <img src="{res_thumb}" '
                    f'alt="{res_title}" class="resource-img" width="262" '
                    f'style="border-radius:6px; border:1px solid #e2e8f0; '
                    f'width:100%; max-width:262px; display:block; height:auto;">\n'
                    f"      </a>\n"
                    f"    </td>\n"
                    f'    <td width="25%"></td>\n'
                    f"  </tr>\n"
                    f"</table>\n"
                )
            elif res_url:
                rows_html += (
                    f'<a href="{res_url}" target="_blank" class="resource-link" '
                    f'style="display:block; font-size:15px; font-weight:700; '
                    f'color:#00819e !important; background-color:#ffffff; '
                    f'border:1px solid #e2e8f0; border-radius:6px; '
                    f'padding:14px 16px; text-decoration:none !important; '
                    f'line-height:1.4;">{res_title}</a>\n'
                )

        resources_section = (
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">\n'
            f"  <tr>\n"
            f'    <td class="resources-cell" '
            f'style="mso-line-height-rule:exactly; background-color:#f7f8fa; '
            f'padding:28px 32px" bgcolor="#f7f8fa">\n'
            f'      <p class="section-label" '
            f'style="font-size:13px; font-weight:700; letter-spacing:3px; '
            f'text-transform:uppercase; color:#00819e; '
            f'margin:0 0 16px 0; padding:0;">🔎 Sermon Resources</p>\n'
            f'      <p style="font-size:13px; color:#718096; '
            f'margin:0 0 16px 0; padding:0;">'
            f"Click any image to download</p>\n"
            f"{rows_html}"
            f"    </td>\n"
            f"  </tr>\n"
            f"</table>"
        )
    else:
        resources_section = "{{RESOURCES_SECTION}}"

    # -- HIGHLIGHT_SECTION ----------------------------------------------------
    has_social = any([yt_url, fb_url, ig_url])
    if has_social or yt_thumb:
        # Build social buttons
        social_btns = ""
        cols = []

        if yt_url:
            cols.append(
                f'<td class="social-col" width="32%" valign="top" '
                f'style="mso-line-height-rule:exactly; padding:0; '
                f'vertical-align:top">\n'
                f'  <a href="{yt_url}" target="_blank" '
                f'class="social-btn social-btn-youtube" '
                f'style="display:block; font-size:14px; font-weight:700; '
                f'letter-spacing:0.5px; padding:14px 20px; border-radius:4px; '
                f'text-decoration:none !important; text-align:center; '
                f'color:#ffffff !important; background-color:#FF0000;">\n'
                f'    ▶️ Share on YouTube\n'
                f"  </a>\n"
                f"</td>"
            )
        if fb_url:
            if cols:
                cols.append(
                    f'<td class="social-spacer" width="2%" '
                    f'style="mso-line-height-rule:exactly; font-size:0; '
                    f'line-height:0;">&nbsp;</td>\n'
                )
            cols.append(
                f'<td class="social-col" width="32%" valign="top" '
                f'style="mso-line-height-rule:exactly; padding:0; '
                f'vertical-align:top">\n'
                f'  <a href="{fb_url}" target="_blank" '
                f'class="social-btn social-btn-facebook" '
                f'style="display:block; font-size:14px; font-weight:700; '
                f'letter-spacing:0.5px; padding:14px 20px; border-radius:4px; '
                f'text-decoration:none !important; text-align:center; '
                f'color:#ffffff !important; background-color:#1877F2;">\n'
                f'    📘 Share on Facebook\n'
                f"  </a>\n"
                f"</td>"
            )
        if ig_url:
            if cols:
                cols.append(
                    f'<td class="social-spacer" width="2%" '
                    f'style="mso-line-height-rule:exactly; font-size:0; '
                    f'line-height:0;">&nbsp;</td>\n'
                )
            cols.append(
                f'<td class="social-col" width="32%" valign="top" '
                f'style="mso-line-height-rule:exactly; padding:0; '
                f'vertical-align:top">\n'
                f'  <a href="{ig_url}" target="_blank" '
                f'class="social-btn social-btn-instagram" '
                f'style="display:block; font-size:14px; font-weight:700; '
                f'letter-spacing:0.5px; padding:14px 20px; border-radius:4px; '
                f'text-decoration:none !important; text-align:center; '
                f'color:#ffffff !important; background-color:#E1306C;">\n'
                f'    📸 Share on Instagram\n'
                f"  </a>\n"
                f"</td>"
            )

        if cols:
            social_btns = (
                f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0" style="margin-top:4px;">\n'
                f"  <tr>\n" + "\n".join(f"    {c}" for c in cols) + "\n"
                f"  </tr>\n"
                f"</table>"
            )

        highlight_thumb_html = ""
        if yt_thumb:
            link_target = yt_url or church_center_link or "#"
            highlight_thumb_html = (
                f'<a href="{link_target}" target="_blank" '
                f'class="highlight-thumb-link" '
                f'style="display:block; line-height:0; font-size:0; '
                f'text-decoration:none;">\n'
                f'  <img src="{yt_thumb}" '
                f'alt="{escape_html(sermon_title or "Sermon Highlight")}" '
                f'width="600" class="highlight-thumb" '
                f'style="width:100%; max-width:600px; height:auto; '
                f'display:block; border-radius:0; border:0;">\n'
                f"</a>\n"
            )

        highlight_section = (
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">\n'
            f"  <tr>\n"
            f'    <td class="highlight-cell" '
            f'style="mso-line-height-rule:exactly; background-color:#111111; '
            f'padding:0 0 28px 0; text-align:center" bgcolor="#111111" '
            f'align="center">\n'
            f"{highlight_thumb_html}"
            f'      <div class="highlight-inner" '
            f'style="padding:24px 32px 0;">\n'
            f'        <p class="highlight-label" '
            f'style="font-size:13px; font-weight:700; letter-spacing:3px; '
            f'text-transform:uppercase; color:#00819e; '
            f'margin:0 0 8px 0; padding:0;">💡 Sermon Highlight</p>\n'
            f'        <p class="highlight-heading" '
            f'style="font-size:24px; font-weight:900; color:#ffffff; '
            f'margin:0 0 20px 0; padding:0;">'
            f"Share this week's message</p>\n"
            f"{social_btns}\n"
            f"      </div>\n"
            f"    </td>\n"
            f"  </tr>\n"
            f"</table>"
        )
    else:
        highlight_section = "{{HIGHLIGHT_SECTION}}"

    # -- SCRIPTURE_QUICK_LINK_BLOCK -------------------------------------------
    if bible_url and sermon_title:
        scripture_quick_link_block = (
            f'<div class="quick-link-row" '
            f'style="border-left:3px solid #00819e; '
            f'padding:10px 0 10px 16px; margin:0;">\n'
            f'  <a href="{bible_url}" target="_blank" '
            f'style="font-size:15px; font-weight:700; color:#00819e !important; '
            f'text-decoration:none;">\n'
            f'    Read {escape_html(sermon_title)} on Bible.com →\n'
            f"  </a>\n"
            f'  <p class="quick-link-desc" '
            f'style="font-size:13px; color:#718096; '
            f'margin:2px 0 0 0; padding:0;">'
            f"Follow along with this week's passage</p>\n"
            f"</div>"
        )
    else:
        scripture_quick_link_block = ""

    # -- CHURCH_CENTER_LINK (used in hero thumbnail and quick links) ----------
    # Already available as raw variable.

    # ---- Build the block map -------------------------------------------------
    return {
        "{{PREHEADER_TEXT}}": preheader,
        "{{SERMON_TITLE}}": escape_html(sermon_title),
        "{{VIDEO_THUMBNAIL}}": video_thumbnail,
        "{{CHURCH_CENTER_LINK}}": church_center_link,
        "{{SCRIPTURE_LINK_BLOCK}}": scripture_link_block,
        "{{SUMMARY_TEXT_BLOCK}}": summary_text_block,
        "{{KEY_POINTS_BLOCK}}": key_points_block,
        "{{RESOURCES_SECTION}}": resources_section,
        "{{HIGHLIGHT_SECTION}}": highlight_section,
        "{{SCRIPTURE_QUICK_LINK_BLOCK}}": scripture_quick_link_block,
    }


# ---------------------------------------------------------------------------
# Phase 4 — Replace placeholders in HTML
# ---------------------------------------------------------------------------
def replace_placeholders(html: str, blocks: dict) -> str:
    """Replace each placeholder key with its HTML block value."""
    for placeholder, replacement in blocks.items():
        html = html.replace(placeholder, replacement)
    return html


# ---------------------------------------------------------------------------
# Helper — fetch file from GitHub with local fallback
# ---------------------------------------------------------------------------
def fetch_github_file(github_url: str, local_path: str, label: str) -> str:
    """Try fetching a file from GitHub raw; fall back to the local copy."""
    try:
        resp = requests.get(github_url, timeout=10)
        resp.raise_for_status()
        content = resp.text
        print(f"⬇️  Fetched {label} from GitHub")
        return content
    except requests.RequestException as exc:
        print(f"⚠️  Could not fetch {label} from GitHub: {exc}", file=sys.stderr)
        print(f"📂 Using local {label} instead.", file=sys.stderr)
        with open(local_path, "r", encoding="utf-8") as f:
            return f.read()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Read source files — try GitHub first, fall back to local
    html_content = fetch_github_file(github_html_url, html_path, "base.html")
    css_content = fetch_github_file(github_css_url, css_path, "styles.css")

    # Phase 1: Inline CSS
    print("📝 Inlining CSS…")
    inlined = inline_css(html_content, css_content)

    # Phase 2: Fetch data from API
    print("🌐 Fetching sermon data from API…")
    data = fetch_sermon_data()

    if data:
        # Phase 3 & 4: Build blocks and replace placeholders
        print("🔧 Building content blocks…")
        blocks = build_blocks(data)
        final_html = replace_placeholders(inlined, blocks)
        print("✅ Data successfully applied from API.")
    else:
        print("⚠️  Keeping placeholders — API data unavailable.")
        final_html = inlined

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"📄 Output written to {output_path}")


if __name__ == "__main__":
    main()
