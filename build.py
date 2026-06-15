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
import argparse

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
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Build the email newsletter template.")
parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable full terminal output and write template.html to disk.",
)
args, _ = parser.parse_known_args()
DEBUG = args.debug


def log(*args, **kwargs):
    """Print only in debug mode."""
    if DEBUG:
        print(*args, **kwargs)

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

    # Handle multiple API response formats:
    #   {"result": { ...data... }}                 — ScriptDash with parsed result
    #   {"output": "{ ...json... }"}               — ScriptDash raw output string
    #   {"status": "success", "stdout": "..."}     — older ScriptDash format
    #   {"output": "", "error": ""}                — ScriptDash empty response
    result = body.get("result")
    if result and isinstance(result, dict):
        return result

    raw = body.get("output") or body.get("stdout") or ""
    if raw:
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            print(f"⚠️  Failed to parse API response as JSON: {exc}", file=sys.stderr)
            return None

    # No data — report what we got
    error_msg = body.get("error") or body.get("stderr") or ""
    if error_msg:
        print(f"⚠️  API error: {error_msg[:300]}", file=sys.stderr)
    elif body.get("status") == "failed":
        print(f"⚠️  API script failed: {body.get('stderr', '')[:200]}", file=sys.stderr)
    else:
        print("⚠️  API returned empty output — the server script may need attention.", file=sys.stderr)

    return None


# ---------------------------------------------------------------------------
# Phase 3 — Build replacement blocks from API data
# ---------------------------------------------------------------------------
def build_blocks(data: dict) -> dict:
    """Build a simple placeholder map — only raw values, no HTML generation."""
    sources = data.get("sources", {})
    sermon = sources.get("sermon", {}).get("data", {})
    youtube = sources.get("youtube", {})
    facebook = sources.get("facebook", {})
    instagram = sources.get("instagram", {})

    sermon_title = (sermon.get("title") or "").strip()
    description = (sermon.get("description") or "").strip()
    church_center_link = (sermon.get("url") or "").strip()
    video_thumbnail = (sermon.get("thumbnail") or "").strip()

    yt_url = (youtube.get("url") or "").strip()
    yt_thumb = (youtube.get("thumbnail") or yt_url or "").strip()
    fb_url = (facebook.get("url") or "").strip()
    ig_url = (instagram.get("url") or "").strip()

    # Preheader text (plain string, not HTML)
    if sermon_title:
        preheader = f"Watch this week's message from Blackhawk Ministries: {sermon_title}"
        if description:
            preheader += f" — {description}"
        preheader += "."
    else:
        preheader = "Watch this week's message from Blackhawk Ministries."

    return {
        "{{PREHEADER_TEXT}}": escape_html(preheader),
        "{{SERMON_TITLE}}": escape_html(sermon_title),
        "{{VIDEO_THUMBNAIL}}": video_thumbnail,
        "{{CHURCH_CENTER_LINK}}": church_center_link,
        "{{HIGHLIGHT_YOUTUBE_URL}}": yt_url,
        "{{HIGHLIGHT_THUMB_URL}}": yt_thumb,
        "{{HIGHLIGHT_THUMB_ALT}}": escape_html(sermon_title),
        "{{HIGHLIGHT_FACEBOOK_URL}}": fb_url,
        "{{HIGHLIGHT_INSTAGRAM_URL}}": ig_url,
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
        log(f"⬇️  Fetched {label} from GitHub")
        return content
    except requests.RequestException as exc:
        log(f"⚠️  Could not fetch {label} from GitHub: {exc}")
        log(f"📂 Using local {label} instead.")
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
    log("📝 Inlining CSS…")
    inlined = inline_css(html_content, css_content)

    # Phase 2: Fetch data from API
    log("🌐 Fetching sermon data from API…")
    data = fetch_sermon_data()

    if data:
        # Phase 3 & 4: Build blocks and replace placeholders
        log("🔧 Building content blocks…")
        blocks = build_blocks(data)
        final_html = replace_placeholders(inlined, blocks)
        log("✅ Data successfully applied from API.")
    else:
        log("⚠️  Keeping placeholders — API data unavailable.")
        final_html = inlined

    if DEBUG:
        # Debug mode: write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_html)
        print(f"📄 Output written to {output_path}")
    else:
        # JSON mode: output to stdout for API consumption
        sys.stdout.write(json.dumps({"html": final_html}))


if __name__ == "__main__":
    main()
