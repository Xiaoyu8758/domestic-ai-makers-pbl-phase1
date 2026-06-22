#!/usr/bin/env python3
"""arXiv paper fetching + PDF figure extraction + key term extraction."""
import hashlib
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests


# ── arXiv API ──

ARXIV_API = "http://export.arxiv.org/api/query"


def _clean_tag(tag: str) -> str:
    """Strip XML namespace from tag name."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _safe_text(elem, tag: str, ns: dict) -> str:
    el = elem.find(tag, ns)
    return (el.text or "").strip() if el is not None and el.text else ""


def _arxiv_get(url: str, timeout: int = 30) -> requests.Response:
    """GET request to arXiv with SSL/network fallbacks."""
    session = requests.Session()
    session.trust_env = False  # bypass system proxy
    # Try HTTPS with verify=True, then verify=False
    for verify in [True, False]:
        try:
            return session.get(url, timeout=timeout, verify=verify,
                             proxies={"http": "", "https": ""})
        except (requests.exceptions.SSLError, requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError):
            continue
    return session.get(url, timeout=timeout, verify=False,
                     proxies={"http": "", "https": ""})


def fetch_arxiv_metadata(arxiv_id: str, timeout: int = 30) -> dict:
    """Fetch paper metadata from arXiv API.

    Args:
        arxiv_id: e.g. "2506.06689" or "2506.06689v1"

    Returns:
        dict with keys: arxiv_id, title, abstract, authors, pdf_url,
                        categories, published
    """
    import urllib3
    urllib3.disable_warnings()
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
    resp = _arxiv_get(url, timeout)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError(f"No entry found for arXiv ID: {arxiv_id}")

    title = _safe_text(entry, "atom:title", ns)
    abstract = _safe_text(entry, "atom:summary", ns)
    abstract = re.sub(r"\s+", " ", abstract).strip()

    authors = []
    for author in entry.findall("atom:author", ns):
        name = _safe_text(author, "atom:name", ns)
        if name:
            authors.append(name)

    pdf_url = ""
    for link in entry.findall("atom:link", ns):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url:
        aid = entry.find("atom:id", ns)
        if aid is not None and aid.text:
            pdf_url = aid.text.strip().replace("http://arxiv.org/abs/", "https://arxiv.org/pdf/") + ".pdf"

    categories = [cat.get("term", "") for cat in entry.findall("atom:category", ns)
                  if cat.get("term")]

    published = _safe_text(entry, "atom:published", ns)

    print(f"[arXiv] Title: {title[:100]}...")
    print(f"[arXiv] Authors: {', '.join(authors[:3])}{'...' if len(authors) > 3 else ''}")
    print(f"[arXiv] PDF: {pdf_url}")

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "pdf_url": pdf_url,
        "categories": categories,
        "published": published,
    }


# ── PDF download ──

def download_pdf(pdf_url: str, output_dir: Path, timeout: int = 120) -> Path:
    """Download PDF from arXiv. Returns path to saved file."""
    import urllib3
    urllib3.disable_warnings()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "paper.pdf"

    print(f"[PDF] Downloading from {pdf_url}...")
    resp = _arxiv_get(pdf_url, timeout)
    resp.raise_for_status()

    path.write_bytes(resp.content)
    size_kb = len(resp.content) / 1024
    print(f"[PDF] Saved: {path} ({size_kb:.0f} KB)")
    return path


# ── Figure extraction ──

def extract_figures(
    pdf_path: Path,
    output_dir: Path,
    max_figures: int = 6,
    max_pages: int = 20,
    min_size_kb: int = 5,
) -> list[Path]:
    """Extract embedded images from PDF using PyMuPDF.

    Deduplicates by image byte hash. Only processes first max_pages.
    Skips images smaller than min_size_kb.

    Returns list of saved image paths.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[FIGURES] PyMuPDF not installed. pip install PyMuPDF")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    seen_hashes = set()
    saved = []

    pages_to_check = min(len(doc), max_pages)
    print(f"[FIGURES] Scanning {pages_to_check} pages for images...")

    for page_idx in range(pages_to_check):
        if len(saved) >= max_figures:
            break
        page = doc[page_idx]
        images = page.get_images(full=True)
        for img_info in images:
            if len(saved) >= max_figures:
                break
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]
                ext = base_image["ext"]

                # Skip small images (logos, icons)
                if len(img_bytes) < min_size_kb * 1024:
                    continue

                # Deduplicate by hash
                img_hash = hashlib.md5(img_bytes).hexdigest()
                if img_hash in seen_hashes:
                    continue
                seen_hashes.add(img_hash)

                fname = f"figure_{len(saved) + 1:03d}.{ext}"
                out_path = output_dir / fname
                out_path.write_bytes(img_bytes)
                saved.append(out_path)
                print(f"[FIGURES] Extracted: {fname} (page {page_idx + 1}, {len(img_bytes) / 1024:.0f} KB)")
            except Exception as e:
                print(f"[FIGURES] Skipped image xref={xref}: {e}")

    doc.close()
    print(f"[FIGURES] Done: {len(saved)} figures extracted")
    return saved


# ── Page rendering (captures vector figures) ──

def extract_figure_regions(
    pdf_path: Path,
    output_dir: Path,
    zoom: float = 3.0,
) -> list[Path]:
    """Extract architecture diagrams by locating figure captions in the PDF.

    Searches each page for "Figure N" / "Fig. N" captions, finds the
    drawings and images above the caption, then renders just that region
    at high resolution. This captures vector graphics (architecture diagrams,
    flowcharts) that PyMuPDF's extract_image() misses.

    Returns list of saved figure image paths.
    """
    try:
        import fitz
    except ImportError:
        print("[FIG-REGION] PyMuPDF not installed. pip install PyMuPDF")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    saved = []

    print(f"[FIG-REGION] Scanning {len(doc)} pages for figure captions...")

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        drawings = page.get_drawings()

        # Find figure caption blocks
        for b in blocks:
            text = b[4]
            # Match "Figure N" or "Fig. N" or "Fig N"
            is_caption = False
            for pattern in ["Figure ", "Fig. ", "Fig "]:
                if text.strip().startswith(pattern) and len(text) > 10:
                    is_caption = True
                    break
            if not is_caption:
                continue

            caption_bbox = fitz.Rect(b[:4])
            # Figure is above the caption — search a generous area above it
            # (from top of page to bottom of caption + some margin)
            fig_top = 30  # near top of page
            fig_bottom = caption_bbox.y0 - 5  # just above caption
            fig_left = caption_bbox.x0
            fig_right = caption_bbox.x1

            # Expand search region using drawings above the caption
            drawing_rects = []
            for d in drawings:
                dr = d["rect"]
                # Drawing is above the caption and within page width
                if dr.y1 < caption_bbox.y0 and dr.y0 > 20:
                    drawing_rects.append(fitz.Rect(dr))

            if drawing_rects:
                # Union of all drawing bounding boxes above caption
                combined = drawing_rects[0]
                for r in drawing_rects[1:]:
                    combined |= r
                fig_top = combined.y0 - 10
                fig_bottom = max(combined.y1, caption_bbox.y0) + 5
                fig_left = min(combined.x0, caption_bbox.x0) - 10
                fig_right = max(combined.x1, caption_bbox.x1) + 10

            # Clamp to page bounds
            fig_top = max(0, fig_top)
            fig_bottom = min(page.rect.y1, fig_bottom)
            fig_left = max(0, fig_left)
            fig_right = min(page.rect.x1, fig_right)

            # Skip if region is too small
            if fig_bottom - fig_top < 80 or fig_right - fig_left < 100:
                continue

            # Render just this region at high zoom
            clip = fitz.Rect(fig_left, fig_top, fig_right, fig_bottom)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=clip)

            # Name by figure number extracted from caption
            import re as _re
            fm = _re.match(r"(?:Figure|Fig\.?)\s*(\d+)", text.strip())
            fig_num = fm.group(1) if fm else str(len(saved) + 1)

            fname = f"figure_{fig_num}_arch.png"
            out_path = output_dir / fname
            pix.save(str(out_path))
            saved.append(out_path)
            kbytes = out_path.stat().st_size / 1024
            print(f"[FIG-REGION] {fname}: page {page_idx+1}, "
                  f"{pix.width}x{pix.height}px, {kbytes:.0f} KB — {text.strip()[:80]}")

    doc.close()
    print(f"[FIG-REGION] Done: {len(saved)} architecture figures extracted")
    return saved


# ── Page rendering (legacy, kept for full-page reference) ──

def render_page_snapshots(
    pdf_path: Path,
    output_dir: Path,
    max_pages: int = 16,
    zoom: float = 2.0,
) -> list[Path]:
    """Render PDF pages as high-res PNG images (full page, no cropping)."""
    try:
        import fitz
    except ImportError:
        print("[RENDER] PyMuPDF not installed. pip install PyMuPDF")
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    pages_to_render = min(len(doc), max_pages)
    saved = []
    print(f"[RENDER] Rendering {pages_to_render} pages at {zoom}x zoom...")
    for page_idx in range(pages_to_render):
        page = doc[page_idx]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        fname = f"page_{page_idx + 1:03d}.png"
        out_path = output_dir / fname
        pix.save(str(out_path))
        saved.append(out_path)
        if (page_idx + 1) % 4 == 0:
            print(f"[RENDER] Page {page_idx + 1}/{pages_to_render}...")
    doc.close()
    print(f"[RENDER] Done: {len(saved)} page snapshots saved to {output_dir}")
    return saved


# ── Key term extraction ──

def extract_key_terms(abstract: str) -> list[str]:
    """Extract important technical terms from paper abstract.

    Uses regex to find:
    1. Capitalized multi-word named entities (e.g. "Swift-Net", "LightVid Block")
    2. Acronyms in parentheses (e.g. "FTGS", "SAF")
    3. Dataset/benchmark names (e.g. "LRS2", "LRS3")
    """
    terms = set()

    # Acronyms in parentheses: (FTGS), (SAF), (SRU)
    for m in re.finditer(r"\(([A-Z][A-Z0-9]{1,8})\)", abstract):
        terms.add(m.group(1))

    # Capitalized compound names: Swift-Net, LightVid Block, power-guided grouped SRU
    # Match patterns like "Xxx-Yyy" or "Xxx Yyy Zzz" where first letter is uppercase
    for m in re.finditer(r"\b[A-Z][a-z]+(?:-[A-Z][a-z]+)+\b", abstract):
        terms.add(m.group(0))

    # Multi-word capitalized phrases (2-3 words): "LightVid Block", "Selective Audio-Visual Fusion"
    for m in re.finditer(r"\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+\b", abstract):
        phrase = m.group(0).strip()
        if len(phrase) > 5 and not phrase.startswith("We ") and not phrase.startswith("The "):
            terms.add(phrase)

    # Dataset names: LRS2, LRS3, ImageNet, etc. (capitalized + digits)
    for m in re.finditer(r"\b[A-Z]+\d+\b", abstract):
        terms.add(m.group(0))

    # GPU, CPU, etc. (common hardware terms)
    for m in re.finditer(r"\b(GPU|CPU|TPU|NPU)\b", abstract):
        terms.add(m.group(1))

    # Deduplicate: remove overlapping terms (keep longer)
    result = sorted(terms, key=len, reverse=True)
    filtered = []
    for term in result:
        if not any(term != other and term.lower() in other.lower() for other in filtered):
            filtered.append(term)

    # Return sorted by first occurrence in abstract
    lower_abs = abstract.lower()
    filtered.sort(key=lambda t: lower_abs.index(t.lower()) if t.lower() in lower_abs else 999)

    print(f"[TERMS] Extracted {len(filtered)} key terms: {filtered[:10]}{'...' if len(filtered) > 10 else ''}")
    return filtered


# ── Quick test ──

if __name__ == "__main__":
    # Test with Swift-Net paper
    arxiv_id = sys.argv[1] if len(sys.argv) > 1 else "2506.06689"
    meta = fetch_arxiv_metadata(arxiv_id)
    terms = extract_key_terms(meta["abstract"])

    if meta["pdf_url"]:
        out_dir = Path(__file__).resolve().parent / "outputs-binyu"
        pdf_path = download_pdf(meta["pdf_url"], out_dir)
        figures = extract_figures(pdf_path, out_dir / "figures")
        print(f"\nFigures: {len(figures)}")
        for f in figures:
            print(f"  {f}")
    print(f"\nKey terms ({len(terms)}):")
    for t in terms[:15]:
        print(f"  - {t}")
