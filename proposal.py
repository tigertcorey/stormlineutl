"""
DOCX proposal generator for Stormline Utilities.
Fills STORMLINE_MASTER_PROPOSAL_v5.docx template with estimate data.
No unit prices shown to GC — quantities only, section subtotals + total bid.
"""

import os
import re
import copy
from datetime import datetime

TEMPLATE_PATH = "/mnt/c/Users/Corey Tigert/OneDrive/Desktop/STORMLINE_MASTER_PROPOSAL_v5.docx"
OUTPUT_DIR = "/mnt/c/Users/Corey Tigert/OneDrive/Desktop"

# Map section names → template table index
SECTION_TABLE = {
    "storm": 1,       # Storm Drain
    "water": 2,       # Water
    "sanitary": 3,    # Sanitary Sewer
    "sewer": 3,
    "fire": 4,        # Fire Line / FDC
    "fdc": 4,
}

# Data row start index per table (table 4 has no header row)
DATA_ROW_START = {1: 1, 2: 1, 3: 1, 4: 0}
DATA_ROW_COUNT = 6   # slots available per section


def _set_cell(cell, text: str):
    """Set cell text, preserving paragraph/run formatting from template."""
    para = cell.paragraphs[0]
    if para.runs:
        # Reuse first run's formatting
        run = para.runs[0]
        run.text = text
        for extra in para.runs[1:]:
            extra.text = ""
    else:
        para.add_run(text)


def generate_docx(estimate_data: dict, project_address: str = "",
                  gc_contact: str = "", engineer: str = "") -> dict:
    """
    Fill the v5 proposal template with estimate data and save to Desktop.
    Returns {"success": True, "path": "..."} or {"success": False, "error": "..."}.
    estimate_data: the 'data' dict from estimate_from_takeoff.
    """
    try:
        from docx import Document
    except ImportError:
        return {"success": False, "error": "python-docx not installed. Run: pip install python-docx"}

    if not os.path.exists(TEMPLATE_PATH):
        return {"success": False, "error": f"Template not found: {TEMPLATE_PATH}"}

    d = estimate_data.get("data", estimate_data)
    job_name    = d.get("job_name", "Project")
    gc_name     = d.get("gc_name", "")
    total_bid   = d.get("total_bid", 0)
    line_items  = d.get("line_items", [])
    mob         = d.get("mobilization", 0)
    testing     = d.get("testing", 0)
    sales_tax   = d.get("sales_tax", 0)
    today       = datetime.now().strftime("%B %d, %Y")

    doc = Document(TEMPLATE_PATH)

    # ── Table 0: Job header ────────────────────────────────────────────────
    hdr = doc.tables[0]
    field_map = {
        "JOB NAME:":       job_name,
        "DATE:":           today,
        "CITY:":           project_address,
        "GC / OWNER:":     f"{gc_name}  {gc_contact}".strip(),
        "CIVIL ENGINEER:": engineer,
    }
    for row in hdr.rows:
        key = row.cells[0].text.strip()
        if key in field_map:
            _set_cell(row.cells[1], field_map[key])

    # ── Group line items by utility type ──────────────────────────────────
    groups: dict[str, list] = {k: [] for k in ("storm", "water", "sanitary", "fire")}
    section_totals: dict[str, float] = {k: 0.0 for k in groups}

    for li in line_items:
        sec = li.get("section", "").lower()
        if any(w in sec for w in ("storm", "drain")):
            g = "storm"
        elif "water" in sec:
            g = "water"
        elif any(w in sec for w in ("sanitary", "sewer")):
            g = "sanitary"
        elif any(w in sec for w in ("fire", "fdc")):
            g = "fire"
        else:
            g = "storm"
        groups[g].append(li)
        section_totals[g] += li.get("extension", 0)

    # Add mob/testing/sales tax into storm subtotal for template display
    # (they show as line items in storm table if there's room, else just subtotal)

    # ── Fill scope tables ─────────────────────────────────────────────────
    for util_type, items in groups.items():
        tbl_idx = SECTION_TABLE[util_type]
        table = doc.tables[tbl_idx]
        start = DATA_ROW_START[tbl_idx]

        for slot in range(DATA_ROW_COUNT):
            row = table.rows[start + slot]
            if slot < len(items):
                li = items[slot]
                qty = li.get("qty", 0)
                qty_str = f"{qty:,.0f}" if qty == int(qty) else f"{qty:,.1f}"
                _set_cell(row.cells[0], str(slot + 1))
                _set_cell(row.cells[1], li.get("item", ""))
                _set_cell(row.cells[2], li.get("unit", "LF"))
                _set_cell(row.cells[3], qty_str)
                _set_cell(row.cells[4], "")   # no unit price to GC
                _set_cell(row.cells[5], "")   # no line totals to GC
            else:
                for c in row.cells:
                    _set_cell(c, "")

        # Subtotal row (second-to-last for table 4, last for tables 1-3)
        subtotal_row = table.rows[-2] if tbl_idx == 4 else table.rows[-1]
        _set_cell(subtotal_row.cells[5], f"${section_totals[util_type]:,.2f}")

    # ── Table 4 last row: total bid ───────────────────────────────────────
    total_row = doc.tables[4].rows[-1]
    # Build total label
    breakdown = (
        f"STORM: ${section_totals['storm']:,.0f}  |  "
        f"WATER: ${section_totals['water']:,.0f}  |  "
        f"SEWER: ${section_totals['sanitary']:,.0f}  |  "
        f"FIRE: ${section_totals['fire']:,.0f}  |  "
        f"MOB: ${mob:,.0f}  |  "
        f"TESTING: ${testing:,.0f}  |  "
        f"TAX: ${sales_tax:,.0f}"
    )
    # Merge cells already? Just set first cell as label and last as value
    _set_cell(total_row.cells[0], "TOTAL BASE BID:")
    for c in total_row.cells[1:-1]:
        _set_cell(c, breakdown)
    _set_cell(total_row.cells[-1], f"${total_bid:,.2f}")

    # ── Save ──────────────────────────────────────────────────────────────
    safe_name = re.sub(r"[^\w\s-]", "", job_name).strip().replace(" ", "_")
    date_str  = datetime.now().strftime("%Y%m%d")
    out_path  = os.path.join(OUTPUT_DIR, f"PROPOSAL_{safe_name}_{date_str}.docx")

    doc.save(out_path)
    return {"success": True, "path": out_path, "total_bid": total_bid}
