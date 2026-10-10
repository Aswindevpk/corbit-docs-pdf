#!/usr/bin/env python3
"""
Universal Documentation PDF Generator
====================================
Automatically discovers documentation in the standard docs folder structure:
  docs/
    00-overview/   (*.md)
    services/      (*.md, optional)
    modules/       (01-*, 02-*, etc., containing *.md files)

On FIRST RUN:
  - Scans docs/ and generates 'pdf_manifest.json' containing all discovered files and metadata.
  - The user can edit 'pdf_manifest.json' to add, remove, or reorder files as needed.

On SUBSEQUENT RUNS:
  - Reads directly from 'pdf_manifest.json'.
  - Any excluded or reordered files in the JSON are respected.
  - Use '--rescan' at any time to re-generate 'pdf_manifest.json' from scratch.

Usage:
    python generate_pdf.py
    python generate_pdf.py --rescan
    python generate_pdf.py --manifest my_config.json
    python generate_pdf.py --output custom.pdf
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

import markdown
import pymupdf


def natural_sort_key(s):
    """Sort strings containing numbers in human-readable natural order (e.g. 1, 2, 10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]


def format_title_from_slug(slug: str) -> str:
    """Format a directory or file slug into human-readable title."""
    clean = re.sub(r'^\d+[-_.]?', '', slug)
    clean = clean.replace('-', ' ').replace('_', ' ')
    return clean.title()


def find_chrome() -> str:
    """Auto-detect Google Chrome or Chromium executable across platforms."""
    env_chrome = os.environ.get('CHROME_PATH')
    if env_chrome and Path(env_chrome).exists():
        return env_chrome

    candidates = [
        # macOS
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        # Linux
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        # Windows
        os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
        os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
    ]
    for c in candidates:
        if Path(c).exists():
            return c

    for cmd in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome']:
        found = shutil.which(cmd)
        if found:
            return found

    raise FileNotFoundError(
        "Google Chrome or Chromium not found. Please install Chrome or set the CHROME_PATH environment variable."
    )


def resolve_mermaid_js(preferred_path: Path | None = None) -> str:
    """Resolve and return the JavaScript code for Mermaid.js."""
    search_paths = []
    if preferred_path:
        search_paths.append(preferred_path)

    # Check project directory, script directory, and user cache
    search_paths.extend([
        Path.cwd() / 'mermaid.min.js',
        Path(__file__).resolve().parent / 'mermaid.min.js',
        Path.home() / '.cache' / 'mermaid' / 'mermaid.min.js'
    ])

    for p in search_paths:
        if p and p.exists() and p.is_file():
            try:
                return p.read_text(encoding='utf-8')
            except Exception as e:
                print(f"Warning: Failed reading {p}: {e}")

    # Fallback: Auto-download to cache
    cache_file = Path.home() / '.cache' / 'mermaid' / 'mermaid.min.js'
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cdn_url = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
    print(f"Downloading mermaid.min.js from CDN into {cache_file}...")
    try:
        urllib.request.urlretrieve(cdn_url, cache_file)
        return cache_file.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Warning: Could not download mermaid.min.js: {e}. Falling back to CDN script tag.")
        return ""


def discover_docs_files(docs_dir: Path) -> list[tuple[str, Path]]:
    """
    Manually loops through the standard docs folder structure:
    1. 00-overview/ (*.md)
    2. services/    (*.md, if present)
    3. modules/     (loops through each module directory 01-*, 02-*, etc., and all *.md files inside)
    4. Any other non-module documentation subdirectories.
    
    Returns a list of tuples: (section_badge, absolute_file_path)
    """
    if not docs_dir.exists() or not docs_dir.is_dir():
        raise FileNotFoundError(f"Documentation directory not found: {docs_dir}")

    discovered = []

    # 1. Overview folder (e.g., 00-overview)
    overview_dirs = [d for d in docs_dir.iterdir() if d.is_dir() and 'overview' in d.name.lower()]
    for ov_dir in sorted(overview_dirs, key=lambda p: natural_sort_key(p.name)):
        md_files = sorted([f for f in ov_dir.glob('*.md') if f.is_file()], key=lambda p: natural_sort_key(p.name))
        
        # Sort system actors / overview first, error dictionaries last
        def overview_priority(p: Path):
            n = p.stem.lower()
            if any(k in n for k in ['actor', 'system', 'role', 'overview', 'architecture']):
                return (0, natural_sort_key(p.name))
            if any(k in n for k in ['error', 'dictionary', 'glossary']):
                return (2, natural_sort_key(p.name))
            return (1, natural_sort_key(p.name))

        md_files.sort(key=overview_priority)
        for f in md_files:
            discovered.append(('00-overview', f))

    # 2. Services / integrations folder (if present)
    services_dir = docs_dir / 'services'
    if services_dir.exists() and services_dir.is_dir():
        for f in sorted([f for f in services_dir.glob('*.md') if f.is_file()], key=lambda p: natural_sort_key(p.name)):
            discovered.append(('services', f))

    # 3. Modules folder (modules/01-*, modules/02-*, etc.)
    modules_dir = docs_dir / 'modules'
    if modules_dir.exists() and modules_dir.is_dir():
        module_subdirs = sorted([d for d in modules_dir.iterdir() if d.is_dir()], key=lambda p: natural_sort_key(p.name))
        for m_dir in module_subdirs:
            badge = m_dir.name
            m_files = sorted([f for f in m_dir.glob('*.md') if f.is_file()], key=lambda p: natural_sort_key(p.name))
            for f in m_files:
                discovered.append((badge, f))

    # 4. Any other subdirectories in docs/ (excluding already handled and database directories)
    handled_names = {'00-overview', 'services', 'modules', 'database', '.git', 'archive', 'images', 'assets'}
    handled_names.update(d.name for d in overview_dirs)
    other_subdirs = sorted(
        [d for d in docs_dir.iterdir() if d.is_dir() and d.name not in handled_names],
        key=lambda p: natural_sort_key(p.name)
    )
    for o_dir in other_subdirs:
        badge = o_dir.name
        for f in sorted([f for f in o_dir.glob('*.md') if f.is_file()], key=lambda p: natural_sort_key(p.name)):
            discovered.append((badge, f))

    return discovered


def extract_title_from_md(md_text: str, fallback_filename: str) -> str:
    """Extract first H1 heading from markdown text, otherwise fallback to filename."""
    match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        return re.sub(r'\s*\{#.*\}$', '', title)
    return format_title_from_slug(fallback_filename)


def extract_and_convert_markdown(md_text: str) -> str:
    """Extract mermaid code blocks and convert markdown to HTML."""
    parts = []
    lines = md_text.split('\n')
    in_code = False
    code_lang = ''
    code_buf = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if in_code:
                in_code = False
                code_str = '\n'.join(code_buf)
                if code_lang == 'mermaid':
                    parts.append(f'\n\n<div class="mermaid-wrap"><div class="mermaid">\n{code_str}\n</div></div>\n\n')
                else:
                    parts.append(f'\n\n```{code_lang}\n{code_str}\n```\n\n')
                code_buf = []
                code_lang = ''
            else:
                in_code = True
                code_lang = stripped[3:].strip()
                code_buf = []
            continue

        if in_code:
            code_buf.append(line)
        else:
            parts.append(line + '\n')

    processed_md = ''.join(parts)
    return markdown.markdown(processed_md, extensions=['tables', 'fenced_code', 'nl2br'])


CSS_STYLES = """
@page {
    size: A4;
    margin: 15mm;
}
* {
    box-sizing: border-box;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 10pt;
    color: #1e293b;
    line-height: 1.5;
    margin: 0;
    background: #ffffff;
}

/* Page Break Helpers */
.cover-page {
    height: 92vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 30px;
    break-after: page;
    page-break-after: always;
}
.toc-section {
    padding: 20px 0;
    break-after: page;
    page-break-after: always;
}
.doc-section {
    padding: 10px 0;
    break-after: page;
    page-break-after: always;
}
.doc-section:last-of-type {
    break-after: auto;
    page-break-after: auto;
}

/* Headings Avoid Orphans */
h1, h2, h3, h4, h5, h6 {
    break-after: avoid;
    page-break-after: avoid;
    color: #0f172a;
}
h1 {
    font-size: 16pt;
    font-weight: 700;
    border-bottom: 2px solid #cbd5e1;
    padding-bottom: 5px;
    margin: 12px 0 10px;
}
h2 {
    font-size: 13pt;
    font-weight: 600;
    margin: 14px 0 6px;
}
h3 {
    font-size: 11pt;
    font-weight: 600;
    margin: 12px 0 5px;
}
h4 {
    font-size: 10pt;
    font-weight: 600;
    margin: 10px 0 4px;
}
p {
    margin: 5px 0;
}

/* Badges & Meta */
.badge {
    display: inline-block;
    font-size: 7.5pt;
    font-weight: 700;
    text-transform: uppercase;
    color: #64748b;
    background: #f1f5f9;
    padding: 2px 8px;
    border-radius: 4px;
    margin-bottom: 6px;
    letter-spacing: 0.5px;
}

/* Blockquotes */
blockquote {
    margin: 8px 0;
    padding: 8px 14px;
    background: #f8fafc;
    border-left: 4px solid #f59e0b;
    border-radius: 0 6px 6px 0;
    font-size: 9pt;
    color: #334155;
}
blockquote p { margin: 3px 0; }

/* Lists & Tables */
ul, ol { margin: 5px 0; padding-left: 20px; }
li { margin: 2px 0; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 12px 0; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
    font-size: 8.5pt;
    break-inside: avoid;
    page-break-inside: avoid;
}
th {
    background: #f1f5f9;
    color: #0f172a;
    font-weight: 600;
    text-align: left;
    padding: 5px 8px;
    border: 1px solid #cbd5e1;
}
td {
    padding: 5px 8px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
}
tr:nth-child(even) td { background: #f8fafc; }

/* Code Blocks */
code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 8.5pt;
    background: #f1f5f9;
    color: #0f172a;
    padding: 2px 4px;
    border-radius: 3px;
}
pre {
    background: #0f172a;
    color: #f8fafc;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 8pt;
    line-height: 1.4;
    overflow-x: auto;
    break-inside: avoid;
    page-break-inside: avoid;
}
pre code {
    background: transparent;
    color: inherit;
    padding: 0;
}

/* Mermaid Diagrams Container & Scaling */
.mermaid-wrap {
    background: #ffffff !important;
    border: 1.5px solid #cbd5e1;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
    text-align: center;
    break-inside: avoid !important;
    page-break-inside: avoid !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.mermaid, .mermaid-wrap div {
    background: transparent !important;
    color: #0f172a !important;
    break-inside: avoid !important;
    page-break-inside: avoid !important;
}
.mermaid-wrap svg {
    max-width: 100% !important;
    max-height: 480px !important;
    width: auto !important;
    height: auto !important;
    display: inline-block !important;
    margin: 0 auto !important;
    background: #ffffff !important;
}
.mermaid-wrap svg text {
    fill: #0f172a !important;
    font-weight: 500;
}

/* Cover & TOC elements */
.cover-badge {
    background: #fef3c7;
    color: #92400e;
    font-weight: 700;
    font-size: 11pt;
    padding: 6px 20px;
    border-radius: 9999px;
    letter-spacing: 2px;
    border: 1px solid #fde68a;
    margin-bottom: 20px;
}
.cover-title {
    font-size: 28pt;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 10px;
    letter-spacing: -0.5px;
}
.cover-sub {
    font-size: 13pt;
    font-weight: 400;
    color: #475569;
    max-width: 550px;
    margin: 0 0 32px;
    line-height: 1.4;
}
.cover-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 18px 24px;
    text-align: left;
    font-size: 9.5pt;
    color: #334155;
    width: 480px;
}
.cover-box p { margin: 4px 0; }
.toc-list {
    columns: 2;
    column-gap: 28px;
    font-size: 9.5pt;
    line-height: 1.85;
    padding-left: 20px;
}
.toc-list a { color: #2563eb; text-decoration: none; }
"""


def build_full_html(
    docs_dir: Path,
    file_list: list[tuple[str, Path]],
    title: str,
    subtitle: str,
    system_name: str,
    mermaid_code: str
) -> str:
    """Build unified multi-module HTML document with cover page and table of contents."""
    sections_html = []
    toc_items = []

    # Collect distinct module names for cover page summary
    module_names = []
    for badge, _ in file_list:
        clean_name = format_title_from_slug(badge)
        if clean_name not in module_names and clean_name.lower() not in ['overview', 'services']:
            module_names.append(clean_name)

    modules_summary_str = ", ".join(module_names) if module_names else "Overview & System Modules"

    for idx, (badge, file_path) in enumerate(file_list):
        raw_md = file_path.read_text(encoding='utf-8')
        doc_title = extract_title_from_md(raw_md, file_path.stem)
        
        toc_items.append(
            f'<li><a href="#section-{idx}">{doc_title}</a> <span style="color:#94a3b8; font-size:8pt;">({badge})</span></li>'
        )

        converted_content = extract_and_convert_markdown(raw_md)
        section_markup = f"""
        <section class="doc-section" id="section-{idx}">
            <div class="badge">{badge}</div>
            {converted_content}
        </section>
        """
        sections_html.append(section_markup)

    current_date_str = datetime.now().strftime("%B %Y")

    mermaid_script_tag = f"<script>{mermaid_code}</script>" if mermaid_code else \
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>'

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{CSS_STYLES}</style>
{mermaid_script_tag}
<script>
mermaid.initialize({{
    startOnLoad: true,
    theme: 'default',
    themeVariables: {{
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif',
        fontSize: '13px',
        primaryColor: '#e0f2fe',
        primaryTextColor: '#0f172a',
        primaryBorderColor: '#0284c7',
        lineColor: '#334155',
        secondaryColor: '#fef3c7',
        tertiaryColor: '#f1f5f9',
        edgeLabelBackground: '#ffffff',
        nodeTextColor: '#0f172a',
        clusterBkg: '#f8fafc',
        clusterBorder: '#cbd5e1'
    }},
    flowchart: {{ useMaxWidth: true, htmlLabels: true, curve: 'basis' }},
    sequence: {{ useMaxWidth: true }},
    er: {{ useMaxWidth: true }}
}});
</script>
</head>
<body>
    <div class="cover-page">
        <div class="cover-badge">SYSTEM ARCHITECTURE &amp; LOGIC</div>
        <div class="cover-title">{title}</div>
        <div class="cover-sub">{subtitle}</div>
        <div class="cover-box">
            <p><strong>System:</strong> {system_name}</p>
            <p><strong>Scope:</strong> {len(file_list)} Specifications Across {len(module_names)} Modules</p>
            <p><strong>Modules:</strong> {modules_summary_str}</p>
            <p><strong>Date:</strong> {current_date_str} &bull; Production Reference Guide</p>
        </div>
    </div>

    <div class="toc-section">
        <h2>Table of Contents</h2>
        <ol class="toc-list">
            {''.join(toc_items)}
        </ol>
    </div>

    {''.join(sections_html)}
</body>
</html>
"""
    return full_html


def load_or_create_manifest(
    project_dir: Path,
    docs_dir: Path,
    manifest_path: Path,
    rescan: bool = False,
    cli_title: str | None = None,
    cli_subtitle: str | None = None,
    cli_system: str | None = None,
    cli_output: Path | None = None
) -> dict:
    """
    Load an existing manifest JSON or create a new one on first run (or if rescan=True).
    Returns manifest dictionary.
    """
    is_first_run = not manifest_path.exists()

    if is_first_run or rescan:
        # First Run or Rescan: discover all files automatically
        print(f"🔍 {'Scanning docs/' if rescan else 'First run detected: scanning docs/'} at: {docs_dir}")
        discovered = discover_docs_files(docs_dir)

        folder_clean = format_title_from_slug(project_dir.name)
        title = cli_title or f"{folder_clean} Logic Documentation"
        subtitle = cli_subtitle or "Comprehensive Business Logic, Workflow State Machines & Integration Specifications"
        system_name = cli_system or f"{folder_clean} Engine"
        output_pdf = str(cli_output.name) if cli_output else f"{project_dir.name}_logic_documentation.pdf"

        # Store paths relative to project_dir for clean human readability
        relative_files = []
        for badge, fpath in discovered:
            try:
                rel = str(fpath.relative_to(project_dir))
            except ValueError:
                rel = str(fpath)
            relative_files.append(rel)

        manifest_data = {
            "title": title,
            "subtitle": subtitle,
            "system_name": system_name,
            "output_pdf": output_pdf,
            "files": relative_files
        }

        # Save manifest
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding='utf-8')
        action_verb = "Re-generated" if rescan else "Generated"
        print(f"✨ {action_verb} '{manifest_path.name}' with {len(relative_files)} files.")
        print(f"   💡 You can edit '{manifest_path.name}' at any time to add, remove, or reorder files.")
        return manifest_data

    else:
        # Subsequent Run: load existing JSON
        print(f"📋 Reading configuration from: {manifest_path.name}")
        try:
            content = manifest_path.read_text(encoding='utf-8')
            manifest_data = json.loads(content)
        except Exception as e:
            print(f"❌ Error reading '{manifest_path}': {e}")
            print("   (Tip: Run with --rescan to recreate a clean manifest)")
            sys.exit(1)

        # Allow CLI flags to override manifest fields if explicitly passed
        if cli_title:
            manifest_data['title'] = cli_title
        if cli_subtitle:
            manifest_data['subtitle'] = cli_subtitle
        if cli_system:
            manifest_data['system_name'] = cli_system
        if cli_output:
            manifest_data['output_pdf'] = str(cli_output)

        return manifest_data


def resolve_manifest_files(project_dir: Path, raw_files: list) -> list[tuple[str, Path]]:
    """
    Parse the files array from the manifest JSON.
    Supports:
      - Simple strings: "docs/01-auth/01.1-login.md"
      - Objects: {"path": "docs/01-auth/01.1-login.md", "badge": "Auth", "enabled": true}
    """
    resolved = []
    for item in raw_files:
        if isinstance(item, str):
            fpath = (project_dir / item).resolve()
            enabled = True
            badge = fpath.parent.name
        elif isinstance(item, dict):
            enabled = item.get("enabled", True)
            raw_path = item.get("path", "")
            fpath = (project_dir / raw_path).resolve()
            badge = item.get("badge") or fpath.parent.name
        else:
            continue

        if not enabled:
            continue

        if not fpath.exists():
            print(f"⚠️  Warning: File specified in manifest not found (skipping): {item}")
            continue

        resolved.append((badge, fpath))

    return resolved


def generate_pdf(
    docs_dir: Path,
    output_pdf: Path | None = None,
    manifest_path: Path | None = None,
    rescan: bool = False,
    title: str | None = None,
    subtitle: str | None = None,
    system_name: str | None = None,
    mermaid_js_path: Path | None = None,
    chrome_path: str | None = None,
    prune_blank_pages: bool = True
):
    """Compile documentation into output_pdf using the manifest JSON."""
    print("=" * 65)
    print(" 📄 Documentation PDF Generator")
    print("=" * 65)

    docs_dir = docs_dir.resolve()
    project_dir = docs_dir.parent if docs_dir.name == 'docs' else docs_dir
    manifest_file = (manifest_path or (project_dir / "pdf_manifest.json")).resolve()

    # Step 1: Load or create the JSON manifest
    manifest_data = load_or_create_manifest(
        project_dir=project_dir,
        docs_dir=docs_dir,
        manifest_path=manifest_file,
        rescan=rescan,
        cli_title=title,
        cli_subtitle=subtitle,
        cli_system=system_name,
        cli_output=output_pdf
    )

    doc_title = manifest_data.get("title", f"{format_title_from_slug(project_dir.name)} Documentation")
    doc_subtitle = manifest_data.get("subtitle", "Business Logic & Architecture Specifications")
    doc_system = manifest_data.get("system_name", f"{format_title_from_slug(project_dir.name)} System")
    
    final_output_pdf = output_pdf or (project_dir / manifest_data.get("output_pdf", f"{project_dir.name}_documentation.pdf"))
    final_output_pdf = final_output_pdf.resolve()

    # Step 2: Resolve files from manifest
    file_list = resolve_manifest_files(project_dir, manifest_data.get("files", []))
    if not file_list:
        print("❌ Error: No valid markdown files found in manifest! Check 'pdf_manifest.json' or run with '--rescan'.")
        sys.exit(1)

    print(f"\n📑 Compiling {len(file_list)} files from manifest:")
    for idx, (badge, fpath) in enumerate(file_list, 1):
        try:
            rel = fpath.relative_to(project_dir)
        except ValueError:
            rel = fpath.name
        print(f"   {idx:2d}. [{badge}] {rel}")

    # Step 3: Locate dependencies
    chrome = chrome_path or find_chrome()
    print(f"\n🌐 Chrome Engine : {chrome}")
    mermaid_code = resolve_mermaid_js(mermaid_js_path)

    # Step 4: Build HTML
    print("📝 Building HTML document...")
    full_html = build_full_html(
        docs_dir=docs_dir,
        file_list=file_list,
        title=doc_title,
        subtitle=doc_subtitle,
        system_name=doc_system,
        mermaid_code=mermaid_code
    )

    tmp_dir = Path(tempfile.gettempdir())
    tmp_source_html = tmp_dir / f"docs_source_{os.getpid()}.html"
    tmp_rendered_html = tmp_dir / f"docs_rendered_{os.getpid()}.html"
    raw_pdf_path = tmp_dir / f"docs_raw_{os.getpid()}.pdf"

    try:
        tmp_source_html.write_text(full_html, encoding='utf-8')

        # Step 5: Headless Chrome Render (Mermaid Diagrams)
        print("📊 Rendering Mermaid diagrams via Headless Chrome DOM dump...")
        rendered_dom = subprocess.check_output([
            chrome,
            '--headless',
            '--disable-gpu',
            '--virtual-time-budget=15000',
            '--dump-dom',
            tmp_source_html.as_uri()
        ], stderr=subprocess.DEVNULL)

        rendered_str = rendered_dom.decode('utf-8')
        if '</head>' in rendered_str:
            rendered_str = rendered_str.replace('</head>', f'<style>{CSS_STYLES}</style></head>')
        else:
            rendered_str = f'<html><head><style>{CSS_STYLES}</style></head><body>{rendered_str}</body></html>'

        tmp_rendered_html.write_text(rendered_str, encoding='utf-8')

        # Step 6: Print to PDF
        print(f"🖨️  Printing PDF via Chrome...")
        subprocess.check_call([
            chrome,
            '--headless',
            '--disable-gpu',
            f'--print-to-pdf={raw_pdf_path}',
            '--no-pdf-header-footer',
            '--run-all-compositor-stages-before-draw',
            tmp_rendered_html.as_uri()
        ], stderr=subprocess.DEVNULL)

        # Step 7: Prune blank artifact pages using PyMuPDF
        final_output_pdf.parent.mkdir(parents=True, exist_ok=True)
        if prune_blank_pages:
            print("✂️  Pruning blank artifact pages with PyMuPDF...")
            doc = pymupdf.open(str(raw_pdf_path))
            original_pages = len(doc)
            pages_to_keep = []

            for i, page in enumerate(doc):
                text = page.get_text().strip()
                drawings = page.get_drawings()
                images = page.get_images()

                is_empty_artifact = (len(text) == 0 and len(images) == 0 and len(drawings) <= 10)
                if is_empty_artifact:
                    print(f"   [Pruned] Page {i+1}: Blank/Frame-only artifact ({len(drawings)} empty rects)")
                else:
                    pages_to_keep.append(i)

            clean_doc = pymupdf.open()
            clean_doc.insert_pdf(doc, from_page=0, to_page=original_pages - 1)

            # Delete backwards so page indices remain valid
            pages_to_delete = [i for i in range(original_pages) if i not in pages_to_keep]
            for p_idx in sorted(pages_to_delete, reverse=True):
                clean_doc.delete_page(p_idx)

            clean_doc.save(str(final_output_pdf))
            clean_doc.close()
            doc.close()
            pruned_count = len(pages_to_delete)
        else:
            shutil.copy2(raw_pdf_path, final_output_pdf)
            pruned_count = 0

        final_pages = len(pymupdf.open(str(final_output_pdf)))
        final_size_mb = final_output_pdf.stat().st_size / (1024 * 1024)

        print("\n" + "=" * 65)
        print(" 🎉 PDF Generated Successfully!")
        print(f"    Output File : {final_output_pdf}")
        print(f"    Manifest    : {manifest_file.name}")
        print(f"    Total Pages : {final_pages}" + (f" (Pruned {pruned_count} blank pages)" if pruned_count else ""))
        print(f"    File Size   : {final_size_mb:.2f} MB")
        print("=" * 65)

    finally:
        # Clean up temporary files
        for tmp_file in [tmp_source_html, tmp_rendered_html, raw_pdf_path]:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(
        description="Universal Documentation PDF Generator: Compiles docs/ into publication-ready PDF using a configurable JSON manifest."
    )
    parser.add_argument(
        "--docs", "-d",
        type=Path,
        default=Path("docs"),
        help="Path to documentation directory (default: ./docs)"
    )
    parser.add_argument(
        "--manifest", "-m",
        type=Path,
        default=None,
        help="Path to manifest JSON file (default: ./pdf_manifest.json)"
    )
    parser.add_argument(
        "--rescan", "-r",
        action="store_true",
        help="Re-scan docs folder and re-generate pdf_manifest.json"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Path to output PDF file (overrides manifest output_pdf)"
    )
    parser.add_argument(
        "--title", "-t",
        type=str,
        default=None,
        help="Document title for cover page (overrides manifest title)"
    )
    parser.add_argument(
        "--subtitle", "-s",
        type=str,
        default=None,
        help="Document subtitle for cover page"
    )
    parser.add_argument(
        "--system",
        type=str,
        default=None,
        help="System/platform name for cover page"
    )
    parser.add_argument(
        "--mermaid-js",
        type=Path,
        default=None,
        help="Custom path to mermaid.min.js"
    )
    parser.add_argument(
        "--chrome",
        type=str,
        default=None,
        help="Custom path to Chrome/Chromium executable"
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Skip PyMuPDF blank page pruning"
    )

    args = parser.parse_args()

    docs_dir = args.docs.resolve()
    if not docs_dir.exists():
        if Path("docs").exists():
            docs_dir = Path("docs").resolve()
        else:
            print(f"Error: Docs directory not found at {docs_dir}")
            sys.exit(1)

    generate_pdf(
        docs_dir=docs_dir,
        output_pdf=args.output,
        manifest_path=args.manifest,
        rescan=args.rescan,
        title=args.title,
        subtitle=args.subtitle,
        system_name=args.system,
        mermaid_js_path=args.mermaid_js,
        chrome_path=args.chrome,
        prune_blank_pages=not args.no_prune
    )


if __name__ == '__main__':
    main()
