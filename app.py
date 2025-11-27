import re
import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional, Tuple, Dict

st.set_page_config(page_title="GPIRS Shortage Report Converter", layout="wide")
st.title("📄 GPIRS Shortage Report Converter (.TXT to .XLSX)")

# ------------------------------- Utilities ---------------------------------- #

def tokenize(line: str) -> List[str]:
    line = line.replace("\x0c", " ").strip()
    return [t for t in line.split() if t]

def extract_shipping_doc_number(txt: str) -> Optional[str]:
    m = re.search(r"Shipping\s+Document\s+No:\s*([A-Za-z0-9\-_/]+)", txt, re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"[^A-Za-z0-9\-_]", "_", m.group(1).strip()) or None

def normalize_date_str(s: str) -> Optional[str]:
    s = s.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None

def extract_received_or_created_date(txt: str) -> str:
    rec = re.search(r"Received\s+Date:\s*([0-9]{4}[/-][0-9]{2}[/-][0-9]{2}|[0-9]{2}/[0-9]{2}/[0-9]{4})",
                    txt, re.IGNORECASE)
    if rec:
        d = normalize_date_str(rec.group(1))
        if d:
            return d
    created = re.search(r"Date\s+Created:\s*([0-9]{4}[/-][0-9]{2}[/-][0-9]{2}|[0-9]{2}/[0-9]{2}/[0-9]{4})",
                        txt, re.IGNORECASE)
    if created:
        d = normalize_date_str(created.group(1))
        if d:
            return d
    return date.today().strftime("%Y-%m-%d")

def find_marker_idx(parts2: List[str]) -> Optional[int]:
    """
    Return index of the first marker token ('I' or 'S') that is followed by 'V'.
    This fixes '... I V ...' and '... S V ...' variants.
    """
    for tok in ("I", "S"):
        if tok in parts2:
            idx = parts2.index(tok)
            if idx + 1 < len(parts2) and parts2[idx + 1] == "V":
                return idx
    return None

# ------------------------------- Parsing ------------------------------------ #

def parse_one_text(txt_content: str, override_date: Optional[str]) -> Tuple[pd.DataFrame, Dict]:
    raw_lines = txt_content.splitlines()
    cleaned_lines = [ln.strip().replace("\x0c", "") for ln in raw_lines if ln.strip()]

    doc_no = extract_shipping_doc_number(txt_content)
    date_rcvd = override_date or extract_received_or_created_date(txt_content)

    entries = []
    i = 0
    while i < len(cleaned_lines) - 1:
        line1 = cleaned_lines[i]
        first_tokens = tokenize(line1)

        if first_tokens and first_tokens[0].isdigit():
            if i + 1 < len(cleaned_lines):
                line2 = cleaned_lines[i + 1]
                parts1 = first_tokens
                parts2 = tokenize(line2)

                if len(parts1) >= 8 and len(parts2) >= 5 and parts2[0].isdigit():
                    marker_idx = find_marker_idx(parts2)
                    if marker_idx is not None:
                        # Description is everything after the ticket up to marker ('I' or 'S')
                        description = " ".join(parts2[1:marker_idx])

                        # TAMS is token after 'V'
                        tams_idx = marker_idx + 2
                        tams = parts2[tams_idx] if tams_idx < len(parts2) else ""

                        # Additional Info: take last non-dot token
                        tail = [t for t in parts2[tams_idx + 1:] if t != "."]
                        additional_info = tail[-1] if tail else ""

                        entry = {
                            "Line": parts1[0],
                            "Date Rcvd": date_rcvd,
                            "Part Prefix": parts1[1],
                            "Part Base": parts1[2],
                            "Part Suffix": parts1[3],
                            "Description": description,          # ✅ no trailing ' S'
                            "Quantity": parts1[-4],
                            "UOM": parts1[-3],
                            "Unit Price ($)": parts1[-2],
                            "Total Price": parts1[-1],
                            "TAMS": tams,
                            "Ticket Number": parts2[0],         # second-from-last (reordered below)
                            "Additional Info": additional_info, # last
                            "Source Doc": doc_no or "",
                        }
                        entries.append(entry)
                        i += 2
                        continue
            i += 1
        else:
            i += 1

    df = pd.DataFrame(entries)

    if not df.empty:
        # Coerce numerics
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
        df["Unit Price ($)"] = pd.to_numeric(df["Unit Price ($)"], errors="coerce")
        df["Total Price"] = pd.to_numeric(df["Total Price"], errors="coerce")

        # Ensure order: Ticket Number second-from-last, Additional Info last
        cols = list(df.columns)
        cols.remove("Additional Info")
        cols.remove("Ticket Number")
        cols.append("Ticket Number")
        cols.append("Additional Info")
        df = df[cols]

    meta = {"doc_no": doc_no, "date_rcvd": date_rcvd}
    return df, meta

# ----------------------------- UI Controls ---------------------------------- #

st.sidebar.header("Options")
use_header_date = st.sidebar.toggle("Use date from shipping doc? (Received/Created)", value=True)
manual_date_value = st.sidebar.date_input("Override Date Rcvd", value=date.today(), disabled=use_header_date)

uploaded_files = st.file_uploader(
    "Upload one or more shortage report (.txt) files",
    type="txt",
    accept_multiple_files=True
)

# ------------------------------ Main Flow ----------------------------------- #

if uploaded_files:
    all_details = []
    doc_badges = []
    meta_dates = []

    for f in uploaded_files:
        raw = f.read()
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        override = None if use_header_date else manual_date_value.strftime("%Y-%m-%d")
        detail_df, meta = parse_one_text(txt, override_date=override)

        all_details.append(detail_df)
        doc_badges.append(meta.get("doc_no") or f.name)
        meta_dates.append(meta.get("date_rcvd"))

    details = pd.concat(all_details, ignore_index=True) if all_details else pd.DataFrame()

    # Badges
    st.markdown("<div style='margin:6px 0;'>", unsafe_allow_html=True)
    for d in sorted(set(doc_badges)):
        st.markdown(
            f"""<span style="
                display:inline-block; margin:4px 6px 0 0; padding:6px 10px;
                background:#E8F1FF; color:#1640D6; border-radius:999px;
                font-weight:600; font-size:0.90rem;">{d}</span>""",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Date caption
    if use_header_date and meta_dates:
        st.caption(f"Using Date Rcvd from headers. Range in files: **{', '.join(sorted(set(meta_dates)))}**")
    else:
        st.caption(f"Using overridden Date Rcvd: **{manual_date_value.strftime('%Y-%m-%d')}**")

    # Table only (Summary removed)
    st.subheader("😎 Here is your data! You can copy direct from here and paste into the Shortages Spreadsheet!")
    st.dataframe(details, width="stretch")

    # ----------------------------- Excel Export ------------------------------ #
    output = BytesIO()
    # Use openpyxl to avoid the xlsxwriter dependency
    details.to_excel(output, sheet_name="Detail", index=False, engine="openpyxl")
    output.seek(0)

    # Filename
    unique_docs = sorted(set(doc_badges))
    doc_part = unique_docs[0] if len(unique_docs) == 1 else "MULTI"
    date_part = (manual_date_value.strftime("%Y-%m-%d") if not use_header_date
                 else (",".join(sorted(set(meta_dates))) if meta_dates else date.today().strftime("%Y-%m-%d")))
    filename = f"shortage_report_{doc_part}_{date_part}.xlsx"

    st.download_button(
        label="📥 Download Excel File",
        data=output,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("Upload one or more **.txt** files to begin.")
    st.markdown(
    "<p style='text-align:center; color:gray; font-size:0.85rem; margin-top:40px;'>"
    "<b>NO ORGANISATIONAL DATA IS SHARED</b>"
    "</p>",
    unsafe_allow_html=True)