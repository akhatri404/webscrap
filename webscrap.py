"""
DataHarvest — Web & PDF Content Extractor
==========================================
Extract tables, text, links, images, and metadata from web pages and PDFs.
Developed by Er Ashish K.C. (Khatri)

Run:  streamlit run app.py
"""

import io
import json
import re
import zipfile
from urllib.parse import urljoin, urlparse

import pandas as pd
import pdfplumber
import fitz  # PyMuPDF
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DataHarvest — Web & PDF Extractor",
    page_icon="🌾",
    layout="wide",
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}
REQUEST_TIMEOUT = 15
MAX_IMAGE_DOWNLOADS = 30  # safety cap when zipping web images

WEB_CONTENT_TYPES = ["Tables", "Text", "Links", "Images", "Metadata"]
PDF_CONTENT_TYPES = ["Tables", "Text", "Images", "Metadata"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=600)
def fetch_url(url: str) -> tuple[bytes | None, str, str]:
    """Fetch a URL. Returns (content, content_type, error_message)."""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", ""), ""
    except requests.exceptions.MissingSchema:
        return None, "", "Invalid URL — it must start with http:// or https://"
    except requests.exceptions.Timeout:
        return None, "", "The request timed out. The site may be slow or blocking bots."
    except requests.exceptions.ConnectionError:
        return None, "", "Could not connect. Check the URL or your internet connection."
    except requests.exceptions.HTTPError as e:
        return None, "", f"HTTP error: {e}"
    except Exception as e:  # noqa: BLE001
        return None, "", f"Unexpected error: {e}"


def clean_sheet_name(name: str, index: int) -> str:
    """Excel sheet names: max 31 chars, no []:*?/\\ characters."""
    name = re.sub(r"[\[\]:*?/\\]", "_", name)[:28] or "Sheet"
    return f"{name}_{index + 1}"


def dfs_to_excel(dfs: list[pd.DataFrame], prefix: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for i, df in enumerate(dfs):
            df.to_excel(writer, index=False, sheet_name=clean_sheet_name(prefix, i))
    return buf.getvalue()


def dfs_to_csv_zip(dfs: list[pd.DataFrame], prefix: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, df in enumerate(dfs):
            zf.writestr(f"{prefix}_{i + 1}.csv", df.to_csv(index=False))
    return buf.getvalue()


def show_tables(dfs: list[pd.DataFrame], prefix: str):
    st.success(f"Found {len(dfs)} table(s).")
    for i, df in enumerate(dfs):
        with st.expander(f"Table {i + 1}  —  {df.shape[0]} rows × {df.shape[1]} cols",
                         expanded=(i == 0)):
            st.dataframe(df, use_container_width=True)
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ All tables — Excel (multi-sheet)",
        dfs_to_excel(dfs, prefix),
        file_name=f"{prefix}_tables.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    c2.download_button(
        "⬇️ All tables — CSV (ZIP)",
        dfs_to_csv_zip(dfs, prefix),
        file_name=f"{prefix}_tables_csv.zip",
        mime="application/zip",
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Web extractors
# ---------------------------------------------------------------------------

def web_extract_tables(html: bytes) -> list[pd.DataFrame]:
    try:
        return pd.read_html(io.BytesIO(html))
    except ValueError:
        return []


def web_extract_text(soup: BeautifulSoup) -> str:
    # Drop non-content elements, then keep a readable structure.
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()
    blocks = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name.startswith("h"):
            blocks.append(f"\n{'#' * int(el.name[1])} {txt}\n")
        elif el.name == "li":
            blocks.append(f"  • {txt}")
        else:
            blocks.append(txt)
    return "\n".join(blocks).strip()


def web_extract_links(soup: BeautifulSoup, base_url: str) -> pd.DataFrame:
    rows = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href.startswith(("http://", "https://")):
            rows.append({
                "text": a.get_text(" ", strip=True) or "(no text)",
                "url": href,
                "internal": urlparse(href).netloc == urlparse(base_url).netloc,
            })
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset="url") if not df.empty else df


def web_extract_images(soup: BeautifulSoup, base_url: str) -> pd.DataFrame:
    rows = []
    for img in soup.find_all("img", src=True):
        src = urljoin(base_url, img["src"])
        if src.startswith(("http://", "https://")):
            rows.append({"alt": img.get("alt", ""), "url": src})
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset="url") if not df.empty else df


def download_images_as_zip(urls: list[str]) -> tuple[bytes, int]:
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, u in enumerate(urls[:MAX_IMAGE_DOWNLOADS]):
            try:
                r = requests.get(u, headers=REQUEST_HEADERS, timeout=10)
                r.raise_for_status()
                ext = (urlparse(u).path.rsplit(".", 1)[-1] or "img")[:4]
                if "/" in ext or not ext.isalnum():
                    ext = "img"
                zf.writestr(f"image_{i + 1}.{ext}", r.content)
                count += 1
            except Exception:  # noqa: BLE001
                continue
    return buf.getvalue(), count


def web_extract_metadata(soup: BeautifulSoup, url: str) -> dict:
    meta = {"url": url, "title": soup.title.get_text(strip=True) if soup.title else ""}
    for m in soup.find_all("meta"):
        key = m.get("name") or m.get("property")
        if key and m.get("content"):
            meta[key] = m["content"]
    return meta


# ---------------------------------------------------------------------------
# PDF extractors
# ---------------------------------------------------------------------------

def parse_page_range(spec: str, total: int) -> list[int]:
    """'1-3,5' -> [0,1,2,4] (0-based). Empty/'all' -> every page."""
    spec = spec.strip().lower()
    if not spec or spec == "all":
        return list(range(total))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a) - 1, int(b)))
        elif part.isdigit():
            pages.add(int(part) - 1)
    return sorted(p for p in pages if 0 <= p < total)


def pdf_extract_text(pdf_bytes: bytes, pages: list[int]) -> str:
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pages:
            txt = pdf.pages[p].extract_text() or ""
            parts.append(f"--- Page {p + 1} ---\n{txt}")
    return "\n\n".join(parts)


def pdf_extract_tables(pdf_bytes: bytes, pages: list[int]) -> list[pd.DataFrame]:
    dfs = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pages:
            for table in pdf.pages[p].extract_tables():
                if table and len(table) > 1:
                    df = pd.DataFrame(table[1:], columns=table[0])
                    dfs.append(df)
    return dfs


def pdf_extract_images(pdf_bytes: bytes, pages: list[int]) -> list[tuple[str, bytes]]:
    """Returns list of (filename, image_bytes)."""
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    seen: set[int] = set()
    for p in pages:
        for img in doc[p].get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            info = doc.extract_image(xref)
            images.append((f"page{p + 1}_img{xref}.{info['ext']}", info["image"]))
    doc.close()
    return images


def pdf_extract_metadata(pdf_bytes: bytes) -> dict:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    meta["page_count"] = doc.page_count
    meta["encrypted"] = doc.is_encrypted
    doc.close()
    return meta


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def render_header():
    st.title("🌾 DataHarvest — Web & PDF Content Extractor")
    st.caption("Developed by **Er Ashish K.C. (Khatri)** · "
               "Pick a source, choose what to extract, download in your preferred format.")
    st.divider()


def web_mode(selections: list[str]):
    url = st.text_input("Enter the webpage URL", placeholder="https://example.com/page")
    if not url:
        st.info("Enter a URL above to begin. Please respect each site's robots.txt and terms of use.")
        return
    if not st.button("🚀 Extract", type="primary"):
        return

    with st.spinner("Fetching page…"):
        content, ctype, err = fetch_url(url)
    if err:
        st.error(err)
        return
    if "text/html" not in ctype:
        st.error(f"URL did not return HTML (Content-Type: {ctype or 'unknown'}).")
        return

    soup = BeautifulSoup(content, "lxml")
    tabs = st.tabs(selections)

    for tab, kind in zip(tabs, selections):
        with tab:
            if kind == "Tables":
                dfs = web_extract_tables(content)
                if dfs:
                    show_tables(dfs, "web")
                else:
                    st.warning("No tables found on this page.")

            elif kind == "Text":
                text = web_extract_text(BeautifulSoup(content, "lxml"))
                if text:
                    st.text_area("Extracted text", text, height=350)
                    c1, c2 = st.columns(2)
                    c1.download_button("⬇️ Download as TXT", text,
                                       file_name="page_text.txt", use_container_width=True)
                    c2.download_button("⬇️ Download as Markdown", text,
                                       file_name="page_text.md", use_container_width=True)
                else:
                    st.warning("No readable text found.")

            elif kind == "Links":
                df = web_extract_links(soup, url)
                if not df.empty:
                    st.success(f"Found {len(df)} unique link(s).")
                    st.dataframe(df, use_container_width=True)
                    st.download_button("⬇️ Download links as CSV",
                                       df.to_csv(index=False),
                                       file_name="links.csv", mime="text/csv")
                else:
                    st.warning("No links found.")

            elif kind == "Images":
                df = web_extract_images(soup, url)
                if not df.empty:
                    st.success(f"Found {len(df)} unique image(s).")
                    st.dataframe(df, use_container_width=True)
                    c1, c2 = st.columns(2)
                    c1.download_button("⬇️ Image URL list (CSV)",
                                       df.to_csv(index=False),
                                       file_name="image_urls.csv", mime="text/csv",
                                       use_container_width=True)
                    with c2:
                        if st.button(f"📦 Download image files as ZIP (max {MAX_IMAGE_DOWNLOADS})",
                                     use_container_width=True):
                            with st.spinner("Downloading images…"):
                                zip_bytes, n = download_images_as_zip(df["url"].tolist())
                            if n:
                                st.download_button(f"⬇️ Save ZIP ({n} images)", zip_bytes,
                                                   file_name="images.zip", mime="application/zip",
                                                   use_container_width=True)
                            else:
                                st.warning("Could not download any of the images.")
                else:
                    st.warning("No images found.")

            elif kind == "Metadata":
                meta = web_extract_metadata(soup, url)
                st.json(meta)
                st.download_button("⬇️ Download metadata as JSON",
                                   json.dumps(meta, indent=2, ensure_ascii=False),
                                   file_name="metadata.json", mime="application/json")


def pdf_mode(selections: list[str]):
    uploaded = st.file_uploader("Upload a PDF file", type="pdf")
    page_spec = st.text_input("Page range (e.g. `1-3,5` — leave empty for all pages)", "")
    if uploaded is None:
        return
    if not st.button("🚀 Extract", type="primary"):
        return

    pdf_bytes = uploaded.getvalue()
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages = len(pdf.pages)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not open PDF: {e}")
        return

    try:
        pages = parse_page_range(page_spec, total_pages)
    except ValueError:
        st.error("Invalid page range. Use formats like `1-3,5` or leave empty.")
        return
    if not pages:
        st.error(f"Page range is out of bounds — this PDF has {total_pages} page(s).")
        return

    st.caption(f"Processing {len(pages)} of {total_pages} page(s).")
    tabs = st.tabs(selections)

    for tab, kind in zip(tabs, selections):
        with tab:
            if kind == "Tables":
                with st.spinner("Extracting tables…"):
                    dfs = pdf_extract_tables(pdf_bytes, pages)
                if dfs:
                    show_tables(dfs, "pdf")
                else:
                    st.warning("No tables detected. Scanned (image-only) PDFs need OCR first.")

            elif kind == "Text":
                with st.spinner("Extracting text…"):
                    text = pdf_extract_text(pdf_bytes, pages)
                if text.strip():
                    st.text_area("Extracted text", text, height=350)
                    st.download_button("⬇️ Download as TXT", text,
                                       file_name=f"{uploaded.name}_text.txt")
                else:
                    st.warning("No text layer found — this is likely a scanned PDF (needs OCR).")

            elif kind == "Images":
                with st.spinner("Extracting images…"):
                    images = pdf_extract_images(pdf_bytes, pages)
                if images:
                    st.success(f"Found {len(images)} embedded image(s).")
                    cols = st.columns(4)
                    for i, (name, data) in enumerate(images):
                        cols[i % 4].image(data, caption=name, use_container_width=True)
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for name, data in images:
                            zf.writestr(name, data)
                    st.download_button("⬇️ Download all images (ZIP)", buf.getvalue(),
                                       file_name="pdf_images.zip", mime="application/zip")
                else:
                    st.warning("No embedded images found in the selected pages.")

            elif kind == "Metadata":
                meta = pdf_extract_metadata(pdf_bytes)
                st.json(meta)
                st.download_button("⬇️ Download metadata as JSON",
                                   json.dumps(meta, indent=2, ensure_ascii=False, default=str),
                                   file_name="pdf_metadata.json", mime="application/json")


def main():
    render_header()

    with st.sidebar:
        st.header("⚙️ Extraction settings")
        source = st.radio("Data source", ["Web Page (URL)", "PDF File"])
        options = WEB_CONTENT_TYPES if source == "Web Page (URL)" else PDF_CONTENT_TYPES
        selections = st.multiselect("What do you want to extract?",
                                    options, default=["Tables"])
        st.divider()
        st.caption("💡 Tip: scanned PDFs have no text layer — run OCR first "
                   "(e.g. `ocrmypdf`) before extracting text or tables.")

    if not selections:
        st.info("Select at least one content type in the sidebar to get started.")
        return

    if source == "Web Page (URL)":
        web_mode(selections)
    else:
        pdf_mode(selections)


if __name__ == "__main__":
    main()
