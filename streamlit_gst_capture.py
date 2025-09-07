# streamlit_gst_capture.py
import streamlit as st
from PIL import Image
import io
import re
import pandas as pd
from pyzbar.pyzbar import decode as qr_decode
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dateutil import parser as dateparser

# -------------------------
# Configuration (user must set)
# -------------------------
# 1) Path to Google Service Account JSON credentials:
SERVICE_ACCOUNT_JSON = "C:/Users/akash/Keys/Pullfile.json"
# 2) Google Spreadsheet ID (the file in Google Drive where sheets will be stored)
SPREADSHEET_ID = "1yoMudkAIJ8OravhwIt--zOejXxLsn9aN4QWKn21_J0M"
# -------------------------

# Sheet tab names used by app
TAX_INVOICE_SHEET = "Tax Invoices"
CREDIT_NOTE_SHEET = "Credit Notes"
DEBIT_NOTE_SHEET = "Debit Notes"
SELF_INVOICE_SHEET = "Self-Invoices (RCM)"
NO_QR_SHEET = "No-QR Invoices"
BILL_OF_ENTRY_SHEET = "Bill of Entry"
GSTR2B_SHEET = "GSTR2B"
VARIANCE_SHEET = "Variance Report"
PURCHASE_REGISTER_SHEET = "Purchase Register"

# Scopes for Google Sheets API
import os
print("File exists:", os.path.exists(SERVICE_ACCOUNT_JSON))
print("Full path being used:", SERVICE_ACCOUNT_JSON)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/drive.file',
          'https://www.googleapis.com/auth/drive']

st.set_page_config(page_title="GST Inward Capture & Reconcile", layout="wide")
st.title("GST Inward Capture — Phone-friendly UI 📱📋")

# -------------------------
# Google Sheets helper
# -------------------------
@st.cache_resource
def get_gspread_client(json_path):
    creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, SCOPES)
    client = gspread.authorize(creds)
    return client

def ensure_sheets_exist(ss, sheet_names):
    existing = [ws.title for ws in ss.worksheets()]
    for name in sheet_names:
        if name not in existing:
            ss.add_worksheet(title=name, rows="1000", cols="50")

def append_row_to_sheet(ss, sheet_name, row_dict):
    worksheet = ss.worksheet(sheet_name)
    # Ensure header exists
    headers = worksheet.row_values(1)
    if not headers:
        headers = list(row_dict.keys())
        worksheet.append_row(headers)
    # Align row values to headers
    row = [row_dict.get(h, "") for h in headers]
    worksheet.append_row(row)

def overwrite_sheet_from_df(ss, sheet_name, df):
    try:
        ss.del_worksheet(ss.worksheet(sheet_name))
    except Exception:
        pass
    ws = ss.add_worksheet(title=sheet_name, rows=str(max(1000, len(df)+5)), cols=str(len(df.columns)+3))
    ws.append_row(list(df.columns))
    if not df.empty:
        ws.append_rows(df.astype(str).values.tolist())

# -------------------------
# OCR and parsing helpers
# -------------------------
def image_to_text(image: Image.Image):
    # Convert to grayscale for better OCR in many cases
    gray = image.convert("L")
    text = "OCR not available in cloud version"
    return text

def detect_qr(image: Image.Image):
    decoded = qr_decode(image)
    return [d.data.decode('utf-8') for d in decoded]

# Primitive extraction — adjust regexes as needed for your invoice formats
def extract_invoice_fields(text):
    lines = text.splitlines()
    text_join = " ".join(lines)
    # Patterns
    patterns = {
        "invoice_number": r"(?:Invoice No|Inv No|Invoice #|Invoice No\.|Inv#|Bill No)[\s:]*([A-Za-z0-9\-\/]+)",
        "invoice_date": r"(?:Invoice Date|Inv Date|Date)[\s:]*([0-3]?\d[\/\-\.\s][0-1]?\d[\/\-\.\s]\d{2,4}|\d{4}-\d{2}-\d{2})",
        "supplier_name": r"(?:Supplier|From|Vendor)[:\s]*([A-Z][A-Za-z0-9 &,\.\-]{2,80})",
        "supplier_gstin": r"([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})", # GSTIN pattern
        "taxable_value": r"(?:Taxable Value|Taxable|Assessable Value|Value)[\s:]*([0-9\.,]+)",
        "tax_amount": r"(?:Total Tax|Tax Amount|GST)[\s:]*([0-9\.,]+)",
        "invoice_total": r"(?:Invoice Total|Total Amount|Total)[\s:]*([0-9\.,]+)",
    }
    results = {}
    for k, p in patterns.items():
        m = re.search(p, text_join, re.IGNORECASE)
        results[k] = m.group(1).strip() if m else ""
    # Normalise dates
    if results.get("invoice_date"):
        try:
            dt = dateparser.parse(results["invoice_date"], dayfirst=True, fuzzy=True)
            results["invoice_date"] = dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return results

# -------------------------
# UI: capture or upload image
# -------------------------
st.markdown("## 1) Capture / Upload Invoice / Credit / Debit / Bill of Entry")
col1, col2 = st.columns([1,2])
with col1:
    capture_mode = st.radio("Input method", ["Take Photo / Upload Image", "Manual Data Entry"], index=0)
    inv_type = st.selectbox("Document type", ["Tax Invoice", "Credit Note", "Debit Note", "Self-Invoice (RCM)", "Bill of Entry"])
    invoice_image = None
    uploaded_file = None
    if capture_mode == "Take Photo / Upload Image":
        uploaded_file = st.file_uploader("Upload invoice photo (camera captures preferred)", type=["png","jpg","jpeg"])
        if uploaded_file:
            image = Image.open(uploaded_file).convert("RGB")
            st.image(image, caption="Uploaded invoice image", use_column_width=True)
            invoice_image = image
    else:
        st.info("You selected manual entry — please fill fields below and click Preview / Approve.")

with col2:
    st.markdown("### OCR / Extracted fields (editable)")
    extracted = {}
    if invoice_image is not None:
        with st.spinner("Running OCR..."):
            ocr_text = image_to_text(invoice_image)
            extracted = extract_invoice_fields(ocr_text)
            qr_data = detect_qr(invoice_image)
            has_qr = len(qr_data) > 0
        st.write("Detected QR data:" if has_qr else "No QR detected")
        if has_qr:
            for q in qr_data:
                st.text(q)
    else:
        extracted = {"invoice_number":"", "invoice_date":"", "supplier_name":"", "supplier_gstin":"", "taxable_value":"", "tax_amount":"", "invoice_total":""}
        qr_data = []
        has_qr = False

    # Allow editing
    invoice_number = st.text_input("Invoice Number", value=extracted.get("invoice_number",""))
    invoice_date = st.text_input("Invoice Date (YYYY-MM-DD)", value=extracted.get("invoice_date",""))
    supplier_name = st.text_input("Supplier Name", value=extracted.get("supplier_name",""))
    supplier_gstin = st.text_input("Supplier GSTIN", value=extracted.get("supplier_gstin",""))
    invoice_value = st.text_input("Taxable Value", value=extracted.get("taxable_value",""))
    tax_amount = st.text_input("Tax Amount", value=extracted.get("tax_amount",""))
    invoice_total = st.text_input("Invoice Total", value=extracted.get("invoice_total",""))
    hsn_or_description = st.text_area("HSN / Description (optional)", height=80)
    place_of_supply = st.text_input("Place of Supply (State)", value="")
    import_be_number = st.text_input("Bill of Entry Number (if BE)", value="")
    import_be_date = st.text_input("Bill of Entry Date (YYYY-MM-DD)", value="")

    # Extra fields useful for reconciliation
    invoice_state_code = st.text_input("Supplier State Code (optional)", value="")

    # Review / Approve
    st.markdown("### Actions")
    approve = st.button("Approve & Push to Google Sheet ✅")
    save_draft = st.button("Save Draft Locally (CSV)")
    preview_row = {
        "capture_timestamp": datetime.datetime.utcnow().isoformat(),
        "document_type": inv_type,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "supplier_name": supplier_name,
        "supplier_gstin": supplier_gstin,
        "taxable_value": invoice_value,
        "tax_amount": tax_amount,
        "invoice_total": invoice_total,
        "hsn_description": hsn_or_description,
        "place_of_supply": place_of_supply,
        "has_qr": bool(qr_data),
        "qr_data": ";".join(qr_data) if qr_data else "",
        "import_be_number": import_be_number,
        "import_be_date": import_be_date,
        "state_code": invoice_state_code
    }
    st.write("Preview row to be saved:")
    st.json(preview_row)

# -------------------------
# Save locally option
# -------------------------
if 'drafts' not in st.session_state:
    st.session_state.drafts = []

if save_draft:
    st.session_state.drafts.append(preview_row)
    st.success("Saved to local session drafts (not yet uploaded). You can Approve later.")

# -------------------------
# Approve & push to Google Sheets
# -------------------------
if not SERVICE_ACCOUNT_JSON or not SPREADSHEET_ID:
    st.error("Please set SERVICE_ACCOUNT_JSON and SPREADSHEET_ID at top of script before pushing.")
else:
    try:
        client = get_gspread_client(SERVICE_ACCOUNT_JSON)
        ss = client.open_by_key(SPREADSHEET_ID)
        # Ensure necessary sheets exist
        ensure_sheets_exist(
            ss,
            [
                TAX_INVOICE_SHEET,
                CREDIT_NOTE_SHEET,
                DEBIT_NOTE_SHEET,
                SELF_INVOICE_SHEET,
                NO_QR_SHEET,
                BILL_OF_ENTRY_SHEET,
                GSTR2B_SHEET,
                VARIANCE_SHEET,
                PURCHASE_REGISTER_SHEET,
            ]
        )

        # Choose destination sheet based on doc type
        dest = TAX_INVOICE_SHEET
        if inv_type == "Credit Note":
            dest = CREDIT_NOTE_SHEET
        elif inv_type == "Debit Note":
            dest = DEBIT_NOTE_SHEET
        elif inv_type == "Self-Invoice (RCM)":
            dest = SELF_INVOICE_SHEET
        elif inv_type == "Bill of Entry":
            dest = BILL_OF_ENTRY_SHEET

        # If no QR, also add to No-QR sheet
        if st.button("Approve & Push"):
            append_row_to_sheet(ss, dest, preview_row)
            st.success(f"Pushed row to Google Sheet tab: {dest}")
        
        if not preview_row.get("has_qr"):
            append_row_to_sheet(ss, NO_QR_SHEET, preview_row)

        st.success(f"Pushed row to Google Sheet tab: {dest} (and to No-QR if applicable).")
    except Exception as e:
        st.error(f"Failed to push to Google Sheets: {e}")


# -------------------------
# 2) Monthly GSTR-2B Upload & Reconcile
# -------------------------
st.markdown("---")
st.header("2) Monthly Reconciliation — Upload Form GSTR-2B (Excel/CSV) and run compare")

uploaded_gstr2b = st.file_uploader("Upload GSTR-2B (Excel or CSV)", type=["xlsx","xls","csv"])
reconcile_btn = st.button("Run Reconciliation Against Captured Invoices")

if uploaded_gstr2b:
    try:
        if uploaded_gstr2b.name.lower().endswith(".csv"):
            gstr2b_df = pd.read_csv(uploaded_gstr2b)
        else:
            gstr2b_df = pd.read_excel(uploaded_gstr2b, engine="openpyxl")
        st.write("Preview GSTR-2B uploaded (first 10 rows):")
        st.dataframe(gstr2b_df.head(10))
        st.session_state.gstr2b_df = gstr2b_df
    except Exception as e:
        st.error(f"Unable to read GSTR-2B file: {e}")

if reconcile_btn:
    if SERVICE_ACCOUNT_JSON == "C:/Users/akash/Keys/Pullfile.json" or SPREADSHEET_ID == "1yoMudkAIJ8OravhwIt--zOejXxLsn9aN4QWKn21_J0M":
        st.error("Please set SERVICE_ACCOUNT_JSON and SPREADSHEET_ID at top of script before reconciling.")
    else:
        try:
            client = get_gspread_client(SERVICE_ACCOUNT_JSON)
            ss = client.open_by_key(SPREADSHEET_ID)
            # Load captured invoices into DataFrame by reading the Tax Invoices and other tabs
            def sheet_to_df(ss, name):
                try:
                    ws = ss.worksheet(name)
                    data = ws.get_all_values()
                    if not data:
                        return pd.DataFrame()
                    df = pd.DataFrame(data[1:], columns=data[0])
                    return df
                except Exception:
                    return pd.DataFrame()

            inv_df = sheet_to_df(ss, TAX_INVOICE_SHEET)
            cn_df = sheet_to_df(ss, CREDIT_NOTE_SHEET)
            dn_df = sheet_to_df(ss, DEBIT_NOTE_SHEET)
            selfinv_df = sheet_to_df(ss, SELF_INVOICE_SHEET)
            be_df = sheet_to_df(ss, BILL_OF_ENTRY_SHEET)

            captured_all = pd.concat([d for d in [inv_df, cn_df, dn_df, selfinv_df, be_df] if not d.empty], ignore_index=True, sort=False)
            if captured_all.empty:
                st.warning("No captured invoices found in Google Sheet. Capture some invoices first.")
            else:
                st.write("Captured invoices loaded from Google Sheet (preview):")
                st.dataframe(captured_all.head(10))

                # Use columns supplier_gstin and invoice_number and taxable_value to match
                # Normalize columns
                def normalize_df(df):
                    df = df.copy()
                    for c in df.columns:
                        df[c] = df[c].astype(str)
                    # Attempt to standardize column names
                    colmap = {}
                    for c in df.columns:
                        lc = c.strip().lower()
                        if "gstin" in lc: colmap[c] = "supplier_gstin"
                        if "invoice" in lc and ("no" in lc or "number" in lc) and "invoice_number" not in colmap.values(): colmap[c] = "invoice_number"
                        if "taxable" in lc or "assessable" in lc: colmap[c] = "taxable_value"
                        if "tax amount" in lc or ("tax" in lc and "amount" in lc): colmap[c] = "tax_amount"
                        if "total" == lc or "invoice_total" in lc or "total amount" in lc: colmap[c] = "invoice_total"
                    df = df.rename(columns=colmap)
                    if "supplier_gstin" not in df.columns:
                        df["supplier_gstin"] = ""
                    if "invoice_number" not in df.columns:
                        df["invoice_number"] = ""
                    if "taxable_value" not in df.columns:
                        df["taxable_value"] = ""
                    # Clean numeric values
                    df["taxable_value_num"] = df["taxable_value"].str.replace(r"[^\d\.]", "", regex=True).replace("", "0").astype(float)
                    return df
                cap = normalize_df(captured_all)
                # Load GSTR2B from session or uploaded file if present
                if 'gstr2b_df' in st.session_state:
                    gstr2b_raw = st.session_state.gstr2b_df
                else:
                    st.error("Please upload a GSTR-2B file before reconciling.")
                    gstr2b_raw = pd.DataFrame()
                if gstr2b_raw.empty:
                    st.error("GSTR-2B appears empty or not uploaded properly.")
                else:
                    # Attempt normalization of GSTR-2B
                    g2 = gstr2b_raw.copy()
                    # Try common column names in GSTR-2B exports: 'GSTIN/UIN of Supplier','Invoice No','Invoice Date','Taxable Value'
                    # We'll standardize heuristically
                    g2_cols = {c: c for c in g2.columns}
                    for c in g2.columns:
                        lc = c.lower()
                        if "gstin" in lc or "supplier" in lc:
                            g2_cols[c] = "supplier_gstin"
                        if "invoice" in lc and ("no" in lc or "number" in lc):
                            g2_cols[c] = "invoice_number"
                        if "taxable" in lc:
                            g2_cols[c] = "taxable_value"
                        if "tax amount" in lc and "tax" in lc:
                            g2_cols[c] = "tax_amount"
                    g2 = g2.rename(columns=g2_cols)
                    if "supplier_gstin" not in g2.columns:
                        g2["supplier_gstin"] = ""
                    if "invoice_number" not in g2.columns:
                        g2["invoice_number"] = ""
                    if "taxable_value" not in g2.columns:
                        g2["taxable_value"] = ""
                    g2["taxable_value_num"] = g2["taxable_value"].astype(str).str.replace(r"[^\d\.]", "", regex=True).replace("", "0").astype(float)

                    # Merge captured vs GSTR2B on supplier_gstin + invoice_number
                    merged = pd.merge(cap, g2, how="outer",
                                      left_on=["supplier_gstin","invoice_number","taxable_value_num"],
                                      right_on=["supplier_gstin","invoice_number","taxable_value_num"],
                                      indicator=True,
                                      suffixes=("_captured","_gstr2b"))
                    # Identify differences:
                    missing_in_gstr2b = merged[merged["_merge"]=="left_only"]  # captured but not in GSTR2B
                    missing_in_captured = merged[merged["_merge"]=="right_only"]  # in GSTR2B but not captured
                    matched = merged[merged["_merge"]=="both"]

                    # Create variance report
                    var_list = []
                    for df_variant, reason in [(missing_in_gstr2b, "Captured not in GSTR-2B"),
                                               (missing_in_captured, "In GSTR-2B not captured")]:
                        if not df_variant.empty:
                            # keep useful cols
                            small = df_variant[["supplier_gstin","invoice_number","taxable_value_num"]].copy()
                            small = small.rename(columns={"taxable_value_num":"taxable_value"})
                            small["issue"] = reason
                            var_list.append(small)
                    if var_list:
                        variance_df = pd.concat(var_list, ignore_index=True)
                    else:
                        variance_df = pd.DataFrame(columns=["supplier_gstin","invoice_number","taxable_value","issue"])

                    st.write("Matched rows count:", len(matched))
                    st.write("Captured but not in GSTR-2B (need follow-up):", len(missing_in_gstr2b))
                    st.write("In GSTR-2B but not captured in system (may be missed):", len(missing_in_captured))
                    st.dataframe(variance_df.head(50))

                    # Save variance & purchase register to Google Sheets
                    overwrite_sheet_from_df(ss, VARIANCE_SHEET, variance_df)
                    # Construct a purchase register: group captured by month, supplier, sum taxable and tax
                    if not cap.empty:
                        cap["invoice_date_parsed"] = pd.to_datetime(cap.get("invoice_date", pd.Series([""]*len(cap))), errors="coerce")
                        cap["month"] = cap["invoice_date_parsed"].dt.to_period("M").astype(str)
                        pr = cap.groupby(["month","supplier_gstin"], as_index=False).agg(
                            total_taxable = ("taxable_value_num","sum")
                        )
                    else:
                        pr = pd.DataFrame()
                    overwrite_sheet_from_df(ss, PURCHASE_REGISTER_SHEET, pr)
                    st.success("Reconciliation complete. Variance report and Purchase Register written to Google Sheet.")
        except Exception as e:
            st.error(f"Reconciliation failed: {e}")

# -------------------------
# Utility: show existing drafts
# -------------------------
st.markdown("---")
st.header("Local Drafts (session only)")
if st.session_state.drafts:
    st.write(pd.DataFrame(st.session_state.drafts))
    if st.button("Clear Drafts"):
        st.session_state.drafts = []
        st.success("Cleared.")
else:
    st.info("No local drafts in this session.")

st.markdown("----")
st.caption("Tip: OCR + regex is a helper — always review before approving. Keep system credentials secure. Deploy on an internal server or Streamlit Cloud for phone access. 👔📱")
