# Corbit Docs PDF (`docs2pdf`)

A universal CLI tool to compile multi-module software documentation (`docs/`) into a publication-grade, self-contained PDF with Mermaid diagrams, print-ready CSS styling, and automatic blank page pruning.

Compatible natively with **macOS**, **Windows**, and **Linux**.

---

## 🚀 Installation

Install directly from GitHub via `pip`:

```bash
pip install git+https://github.com/<YOUR_GITHUB_ORG_OR_USERNAME>/corbit-docs-pdf.git
```

* **On macOS:** The `docs2pdf` command will be added to your PATH.
* **On Windows:** `docs2pdf.exe` will be added to your Python Scripts PATH.

> **Prerequisites:** 
> - Python 3.10+
> - Google Chrome or Chromium (auto-detected across Windows and Mac)

---

## 📖 Usage

Navigate into **any project directory** containing a `docs/` folder:

```bash
docs2pdf
```

### 1. First Run (Auto-Discovery & Manifest Generation)
On the first run inside a project:
1. `docs2pdf` automatically scans `docs/` (`00-overview/`, `services/`, and `modules/01-*/`, etc.).
2. It generates a **`pdf_manifest.json`** in your project root with all discovered files.
3. It compiles and creates `<project>_logic_documentation.pdf`.

### 2. Customizing Included Files
You can edit `pdf_manifest.json` at any time to:
- **Exclude a file:** Delete its line from the `"files"` array, or set `{"path": "...", "enabled": false}`.
- **Reorder files:** Cut and paste lines in the exact order you want them in the PDF.
- **Add custom files:** Add extra markdown paths (e.g., `"docs/database/er-diagram.md"`).

### 3. Subsequent Runs
On future runs:
```bash
docs2pdf
```
`docs2pdf` reads directly from `pdf_manifest.json`, respecting your customized list of files.

### 4. Resetting / Re-scanning Docs
To discover newly added folders and re-generate `pdf_manifest.json` from scratch:
```bash
docs2pdf --rescan
```

---

## 🛠️ CLI Options

```text
usage: docs2pdf [-h] [--docs DOCS] [--manifest MANIFEST] [--rescan]
                [--output OUTPUT] [--title TITLE] [--subtitle SUBTITLE]
                [--system SYSTEM] [--mermaid-js MERMAID_JS]
                [--chrome CHROME] [--no-prune]

options:
  -h, --help            Show help message and exit
  --docs, -d DOCS       Path to docs directory (default: ./docs)
  --manifest, -m PATH   Path to manifest JSON file (default: ./pdf_manifest.json)
  --rescan, -r          Re-scan docs folder and re-generate pdf_manifest.json
  --output, -o OUTPUT   Path to output PDF file (overrides manifest output_pdf)
  --title, -t TITLE     Document title for cover page (overrides manifest title)
  --subtitle, -s TEXT   Document subtitle for cover page
  --system SYSTEM       System/platform name for cover page
  --mermaid-js PATH     Custom path to mermaid.min.js
  --chrome PATH         Custom path to Chrome/Chromium executable
  --no-prune            Skip PyMuPDF blank page pruning
```

---

## 💻 Cross-Platform Compatibility

* **Google Chrome Auto-Detection**:
  * **macOS:** `/Applications/Google Chrome.app`, `/Applications/Chromium.app`
  * **Windows:** `%ProgramFiles%\Google\Chrome\Application\chrome.exe`, `%ProgramFiles(x86)%`, `%LocalAppData%`
  * Custom path can be set with `--chrome` or `CHROME_PATH` environment variable.
* **Mermaid.js**:
  * Automatically cached in `~/.cache/mermaid/mermaid.min.js`.
  * Auto-downloads from CDN on first run if missing.
