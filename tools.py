"""
Tool implementations for Stormline Management Bot.
Handles website, project, email, and approval operations.
"""

import json
import os
import logging
import re
import uuid
import subprocess
import fnmatch
from datetime import datetime
from typing import Any
from config import config
from planswift import (
    ps_status, ps_get_takeoff, ps_load_pdf, ps_list_jobs,
    ps_add_section, ps_add_item, ps_set_property, ps_delete_item,
    ps_get_current_page, ps_screenshot,
)

logger = logging.getLogger(__name__)


# ─── Filesystem ───────────────────────────────────────────────────────────────

def _fs_list_directory(path: str, **_) -> dict:
    try:
        entries = os.listdir(path)
        result = []
        for name in sorted(entries):
            full = os.path.join(path, name)
            kind = "dir" if os.path.isdir(full) else "file"
            try:
                size = os.path.getsize(full) if kind == "file" else None
            except OSError:
                size = None
            result.append({"name": name, "type": kind, "size": size})
        return {"success": True, "path": path, "count": len(result), "entries": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


_BLOCKED_READ_PATTERNS = (
    ".ssh", ".gnupg", ".gpg", "id_rsa", "id_ed25519", "id_ecdsa",
    "cookies", "keychain", "wallet", "password", "credential",
    "shadow", "passwd", ".netrc", "token", "secret",
)

def _fs_read_file(path: str, **_) -> dict:
    lower = path.lower()
    if any(p in lower for p in _BLOCKED_READ_PATTERNS):
        return {"success": False, "error": f"Access denied: sensitive path blocked — {path}"}
    try:
        with open(path, "r", errors="replace") as f:
            content = f.read(8000)
        truncated = os.path.getsize(path) > 8000
        return {"success": True, "path": path, "content": content, "truncated": truncated}
    except Exception as e:
        return {"success": False, "error": str(e)}


_WRITE_SAFE_PREFIXES = (
    "/home/corey_tigert/stormlineutl/data/",
    "/tmp/",
)

def _fs_write_file(path: str, content: str, **_) -> dict:
    abs_path = os.path.abspath(path)
    # Direct write only to bot data dir and /tmp — everything else needs approval
    if any(abs_path.startswith(p) for p in _WRITE_SAFE_PREFIXES):
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(content)
            return {"success": True, "path": abs_path, "bytes_written": len(content.encode())}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        preview = content[:300] + ("..." if len(content) > 300 else "")
        approval_id = queue_approval(
            action_type="file_write",
            description=f"Write file: {abs_path}\n\nPreview:\n{preview}",
            payload={"path": abs_path, "content": content}
        )
        return {
            "success": True, "queued": True, "approval_id": approval_id,
            "message": f"File write queued for approval. Corey must approve before it is written. ID: {approval_id}"
        }


def _fs_search(path: str, pattern: str, file_glob: str = "*", **_) -> dict:
    """Search file contents recursively for a pattern. Also matches filenames."""
    import time
    deadline = time.time() + 30  # 30 second hard limit
    try:
        matches = []
        # First pass: match by filename only (fast)
        name_matches = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            if time.time() > deadline:
                return {"success": True, "matches": name_matches + matches, "truncated": True, "note": "Search timed out — results may be partial"}
            for fname in files:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                if pattern.lower() in fname.lower():
                    fpath = os.path.join(root, fname)
                    name_matches.append({"file": fpath, "line": 0, "text": f"(filename match)"})
                    if len(name_matches) >= 20:
                        return {"success": True, "matches": name_matches, "count": len(name_matches), "truncated": True}

        # Second pass: search file contents (skip binaries and large files)
        if file_glob != "*":  # only search contents if specific file type requested
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                if time.time() > deadline:
                    break
                for fname in files:
                    if not fnmatch.fnmatch(fname, file_glob):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        if os.path.getsize(fpath) > 2_000_000:
                            continue
                        with open(fpath, "r", errors="replace") as f:
                            for i, line in enumerate(f, 1):
                                if pattern.lower() in line.lower():
                                    matches.append({"file": fpath, "line": i, "text": line.strip()[:200]})
                                    if len(matches) >= 30:
                                        return {"success": True, "matches": name_matches + matches, "truncated": True}
                    except OSError:
                        continue

        all_matches = name_matches + matches
        return {"success": True, "matches": all_matches, "count": len(all_matches), "truncated": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


_BLOCKED_SHELL_PATTERNS = (
    "curl ", "wget ", "nc ", "netcat", "ncat", " | mail", "sendmail",
    "scp ", "sftp ", "ftp ", "ssh ", "rsync ",
    "/dev/tcp", "/dev/udp", "base64 -d", "eval ",
)

def _shell_run(command: str, cwd: str = None, **_) -> dict:
    """Run a shell command and return output."""
    lower_cmd = command.lower()
    if any(p in lower_cmd for p in _BLOCKED_SHELL_PATTERNS):
        return {"success": False, "error": f"Command blocked: contains restricted operation. Use specific tools for network/transfer operations."}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=60, cwd=cwd
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:4000],
            "stderr": result.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 60 seconds"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _windows_open(path: str, **_) -> dict:
    """Open a file or folder in Windows using explorer.exe."""
    try:
        # Convert WSL path to Windows path if needed
        if path.startswith("/mnt/"):
            parts = path[5:].split("/", 1)
            win_path = parts[0].upper() + ":\\" + (parts[1].replace("/", "\\") if len(parts) > 1 else "")
        else:
            win_path = path
        result = subprocess.run(
            ["explorer.exe", win_path],
            capture_output=True, text=True, timeout=10
        )
        return {"success": True, "opened": win_path}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── PlanSwift AI Tracing ────────────────────────────────────────────────────

def _calibration_file() -> str:
    return os.path.join(config.data_dir, "ps_calibrations.json")

TAKEOFF_MANIFEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ps_takeoff_manifest.json")

def _load_takeoff_manifest() -> dict:
    if not os.path.exists(TAKEOFF_MANIFEST_FILE):
        return {}
    with open(TAKEOFF_MANIFEST_FILE) as f:
        return json.load(f)

def _save_takeoff_manifest(manifest: dict):
    with open(TAKEOFF_MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)


def _load_calibrations() -> dict:
    p = _calibration_file()
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)

def _save_calibrations(data: dict):
    with open(_calibration_file(), "w") as f:
        json.dump(data, f, indent=2)


def _ps_vision_analyze(image_path: str, prompt: str) -> str:
    """Send a screenshot to Claude Vision and return the text response."""
    import anthropic, base64
    with open(image_path, "rb") as f:
        img_data = base64.standard_b64encode(f.read()).decode()
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_data}},
                {"type": "text", "text": prompt},
            ]
        }]
    )
    return msg.content[0].text


def ps_calibrate_page(**_) -> dict:
    """
    Screenshot the current PlanSwift page, use Vision to find the scale bar,
    compute pixels-per-foot, and store it for this page.
    """
    # Get screenshot
    shot = ps_screenshot()
    if not shot["success"]:
        return {"success": False, "error": f"Screenshot failed: {shot['error']}"}

    # Get current page info
    page_info = ps_get_current_page()
    page_name = page_info.get("data", {}).get("page_name", "unknown") if page_info["success"] else "unknown"

    prompt = f"""This is a screenshot of a construction plan page in PlanSwift software (page: "{page_name}").

Your job is to find the graphic scale bar on this plan sheet and calibrate it.

Please analyze the image and return a JSON object with these exact fields:
{{
  "found_scale_bar": true/false,
  "scale_bar_length_feet": <the labeled length in feet, e.g. 50 or 100>,
  "scale_bar_pixel_length": <estimated length of that bar in pixels>,
  "scale_bar_location": "<describe where it is, e.g. 'bottom left corner'>",
  "pixels_per_foot": <scale_bar_pixel_length / scale_bar_length_feet>,
  "image_width_px": {shot['width']},
  "image_height_px": {shot['height']},
  "view_type": "<'plan' or 'profile' or 'detail' or 'other'>",
  "sheet_title": "<sheet title or number if visible>",
  "confidence": "<high/medium/low>",
  "notes": "<anything that might affect accuracy>"
}}

Return ONLY the JSON object, no other text."""

    try:
        raw = _ps_vision_analyze(shot["wsl_path"], prompt)
        # Extract JSON from response
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return {"success": False, "error": "Vision did not return valid JSON", "raw": raw}
        cal = json.loads(match.group())

        if not cal.get("found_scale_bar"):
            return {"success": False, "error": "No scale bar found on this page", "vision_notes": cal.get("notes")}

        # Store calibration
        calibrations = _load_calibrations()
        calibrations[page_name] = {
            "page_name": page_name,
            "pixels_per_foot": cal["pixels_per_foot"],
            "scale_bar_feet": cal["scale_bar_length_feet"],
            "scale_bar_px": cal["scale_bar_pixel_length"],
            "image_width": shot["width"],
            "image_height": shot["height"],
            "view_type": cal.get("view_type", "plan"),
            "sheet_title": cal.get("sheet_title", ""),
            "confidence": cal.get("confidence", "medium"),
            "notes": cal.get("notes", ""),
            "calibrated_at": datetime.now().isoformat(),
            "screenshot": shot["wsl_path"],
        }
        _save_calibrations(calibrations)

        return {
            "success": True,
            "page": page_name,
            "pixels_per_foot": cal["pixels_per_foot"],
            "scale_bar": f"{cal['scale_bar_length_feet']} ft = {cal['scale_bar_pixel_length']} px",
            "view_type": cal.get("view_type"),
            "confidence": cal.get("confidence"),
            "notes": cal.get("notes"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def ps_manual_calibrate(page_name: str, pixels_per_foot: float, note: str = "", **_) -> dict:
    """Manually set calibration for a page if Vision can't find the scale bar."""
    calibrations = _load_calibrations()
    calibrations[page_name] = {
        "page_name": page_name,
        "pixels_per_foot": pixels_per_foot,
        "confidence": "manual",
        "notes": note,
        "calibrated_at": datetime.now().isoformat(),
    }
    _save_calibrations(calibrations)
    return {"success": True, "page": page_name, "pixels_per_foot": pixels_per_foot}


def ps_analyze_pipes(**_) -> dict:
    """
    Screenshot current PlanSwift page, use Vision to identify all pipe runs,
    sizes, materials, and approximate lengths. Returns structured pipe inventory
    with confidence scores. Does NOT create items — use ps_create_takeoff after reviewing.
    """
    shot = ps_screenshot()
    if not shot["success"]:
        return {"success": False, "error": f"Screenshot failed: {shot['error']}"}

    page_info = ps_get_current_page()
    page_name = page_info.get("data", {}).get("page_name", "unknown") if page_info["success"] else "unknown"

    # Get stored calibration
    calibrations = _load_calibrations()
    cal = calibrations.get(page_name)
    cal_info = f"Calibration: {cal['pixels_per_foot']:.2f} px/ft ({cal['scale_bar_feet']} ft scale bar)" if cal else "No calibration stored for this page — lengths will be estimated only."

    prompt = f"""This is a construction plan sheet (page: "{page_name}") shown in PlanSwift software.
{cal_info}
Image size: {shot['width']} x {shot['height']} pixels.

You are a professional underground utility takeoff estimator. Analyze this plan and identify ALL pipe runs and structures visible.

Return ONLY a JSON object in this exact format — no markdown, no explanation:
{{
  "view_type": "plan",
  "sheet_title": "<title if visible>",
  "pipes": [
    {{
      "id": "pipe_001",
      "type": "storm|sanitary|water|fire|FDC",
      "size": "18",
      "material": "RCP|PVC SDR26|C900|DI|HDPE",
      "from_structure": "<start>",
      "to_structure": "<end>",
      "estimated_lf": <number>,
      "size_label_text": "<label if visible>",
      "confidence": "high|medium|low",
      "notes": "<slope, invert, special conditions>"
    }}
  ],
  "structures": [
    {{
      "id": "str_001",
      "type": "manhole|inlet|junction_box|headwall|cleanout|hydrant|valve",
      "label": "<label if shown>",
      "count": 1,
      "confidence": "high|medium|low"
    }}
  ],
  "flags": ["<anything uncertain or needs field verification>"]
}}

Group identical pipe sizes/types into single entries with total estimated_lf.
For estimated_lf: visually estimate pipe length using the scale bar, or use {cal.get('pixels_per_foot', 1.56):.2f} px/ft calibration.
Return ONLY the JSON object."""

    try:
        raw = _ps_vision_analyze(shot["wsl_path"], prompt)
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return {"success": False, "error": "Vision did not return parseable JSON", "raw": raw[:500]}
        result = json.loads(match.group())

        # Enrich with calibration data
        if cal and cal.get("pixels_per_foot"):
            ppf = cal["pixels_per_foot"]
            for pipe in result.get("pipes", []):
                if pipe.get("pixel_length") and not pipe.get("estimated_lf"):
                    pipe["estimated_lf"] = round(pipe["pixel_length"] / ppf, 1)

        result["page_name"] = page_name
        result["calibrated"] = cal is not None
        result["screenshot"] = shot["wsl_path"]

        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ps_create_takeoff_from_analysis(analysis: dict, section_name: str = "", **_) -> dict:
    """
    Take the output from ps_analyze_pipes and create the actual takeoff items
    in PlanSwift. Groups pipes by type/size into sections.
    Only creates items with confidence >= medium unless force=True.
    """
    pipes = analysis.get("pipes", [])
    structures = analysis.get("structures", [])
    page_name = analysis.get("page_name", "unknown")

    if not pipes and not structures:
        return {"success": False, "error": "No pipes or structures in analysis data"}

    created = []
    skipped = []
    errors = []

    # Group pipes by utility type → section
    type_map = {
        "storm": section_name or "Storm Drainage",
        "sanitary": section_name or "Sanitary Sewer",
        "water": section_name or "Water",
        "fire": section_name or "Fire/FDC",
        "fdc": section_name or "Fire/FDC",
    }

    sections_needed = set()
    for pipe in pipes:
        if pipe.get("confidence", "low") == "low":
            skipped.append({"id": pipe["id"], "reason": "low confidence"})
            continue
        ptype = pipe.get("type", "storm").lower()
        sections_needed.add(type_map.get(ptype, section_name or "Utilities"))

    # Count structures by type for sections
    structure_types = set(s.get("type", "").lower() for s in structures)
    if any(t in structure_types for t in ["manhole", "inlet", "junction box", "headwall"]):
        sections_needed.add(section_name or "Storm Drainage")

    # Create sections
    for sec in sections_needed:
        r = ps_add_section(sec)
        if not r["success"] and not r.get("already_existed"):
            errors.append(f"Section '{sec}': {r.get('error')}")

    # Create pipe items
    for pipe in pipes:
        if pipe.get("confidence", "low") == "low":
            continue
        ptype = pipe.get("type", "storm").lower()
        sec = type_map.get(ptype, section_name or "Utilities")
        size = pipe.get("size", "unknown")
        mat = pipe.get("material", "")
        item_name = f"{size} {mat}".strip() if mat else size
        lf = pipe.get("estimated_lf")

        r = ps_add_item(sec, item_name, "Linear", "LF")
        if r["success"]:
            if lf:
                ps_set_property(r["path"], "Quantity", str(lf))
                ps_set_property(r["path"], "Length", str(lf))
            ps_set_property(r["path"], "Description",
                f"Page: {page_name} | From: {pipe.get('from_structure','')} To: {pipe.get('to_structure','')}")
            created.append({"name": item_name, "section": sec, "lf": lf, "confidence": pipe["confidence"]})
        else:
            errors.append(f"Item '{item_name}': {r.get('error')}")

    # Create structure count items
    struct_counts: dict[str, int] = {}
    for s in structures:
        if s.get("confidence", "low") == "low":
            continue
        stype = s.get("type", "unknown")
        struct_counts[stype] = struct_counts.get(stype, 0) + 1

    for stype, count in struct_counts.items():
        ptype = "storm"  # default — improve with smarter detection if needed
        sec = type_map.get(ptype, section_name or "Storm Drainage")
        r = ps_add_item(sec, stype.title(), "Count", "EA")
        if r["success"]:
            ps_set_property(r["path"], "Quantity", str(count))
            created.append({"name": stype.title(), "section": sec, "count": count, "type": "structure"})
        else:
            errors.append(f"Structure '{stype}': {r.get('error')}")

    # Save manifest so ps_get_takeoff can enumerate by name
    if created:
        manifest = _load_takeoff_manifest()
        for item in created:
            sec = item["section"]
            name = item["name"]
            if sec not in manifest:
                manifest[sec] = []
            if name not in manifest[sec]:
                manifest[sec].append(name)
        _save_takeoff_manifest(manifest)

    return {
        "success": True,
        "created": created,
        "skipped_low_confidence": skipped,
        "errors": errors,
        "summary": f"{len(created)} items created, {len(skipped)} skipped (low confidence), {len(errors)} errors",
    }


# ─── Pricing Engine ──────────────────────────────────────────────────────────
# At-cost installed rates (Corey + Jarvis, March 2026). Apply O&P after.

PRICING_DB = {
    "storm_pipe": {  # $/LF by size (inches)
        "10": 145, "12": 145, "15": 165, "18": 195,
        "24": 240, "27": 275, "30": 310, "36": 365,
    },
    "storm_struct": {  # $/EA
        "inlet": 6500, "curb_inlet": 6500, "area_inlet": 6000,
        "junction_box": 7500, "catch_basin": 6000,
        "manhole": 8000, "headwall": 9000,
    },
    "water_pipe": {  # $/LF
        "2": 55, "3": 65, "4": 85, "6": 110, "8": 155, "12": 210,
    },
    "water_struct": {  # $/EA
        "gate_valve": 1200, "valve": 1200,
        "gate_valve_12": 2500,
        "fire_hydrant": 8500, "hydrant": 8500,
        "dcva": 14000, "backflow": 14000,
        "tapping_sleeve": 5500,
        "service": 1800,
        "meter": 1800,
    },
    "sewer_pipe": {  # $/LF
        "4": 55, "6": 135, "8": 175, "10": 210,
    },
    "sewer_struct": {  # $/EA
        "manhole": 7500, "drop_mh": 11000,
        "connect_existing": 5000,
        "cleanout": 750,
        "service": 1200,
    },
    "fire_pipe": {  # $/LF — DI, same general range as water
        "4": 85, "6": 110, "8": 155,
    },
}

OAP_RATES = {
    "competitive": 0.20,
    "standard": 0.25,
    "negotiated": 0.30,
    "emergency": 0.40,
    "floor": 0.15,
}


def _lookup_pipe_rate(util_type: str, size: str, material: str = "") -> float:
    size_str = str(size).replace('"', '').replace("inch", "").strip()
    mat = material.lower()
    if util_type in ("fire", "fdc"):
        db = PRICING_DB["fire_pipe"]
    elif util_type == "water":
        db = PRICING_DB["water_pipe"]
    elif util_type in ("sanitary", "sewer"):
        db = PRICING_DB["sewer_pipe"]
    else:
        db = PRICING_DB["storm_pipe"]
    if size_str in db:
        return float(db[size_str])
    try:
        n = int(size_str)
        candidates = [(abs(int(k) - n), float(v)) for k, v in db.items() if k.isdigit()]
        return sorted(candidates)[0][1] if candidates else 0.0
    except (ValueError, TypeError):
        return 0.0


def _lookup_struct_rate(name: str, util_type: str = "storm") -> float:
    t = name.lower().replace(" ", "_").replace("-", "_")
    if util_type in ("water", "fire", "fdc"):
        db = PRICING_DB["water_struct"]
    elif util_type in ("sanitary", "sewer"):
        db = PRICING_DB["sewer_struct"]
    else:
        db = PRICING_DB["storm_struct"]
    if t in db:
        return float(db[t])
    for key in db:
        if key in t or t.startswith(key[:4]):
            return float(db[key])
    return 0.0


def estimate_from_takeoff(job_name: str = "", gc_name: str = "",
                           job_type: str = "standard", is_private: bool = True, **_) -> dict:
    """
    Pull current PlanSwift takeoff quantities, apply at-cost rates + O&P, and
    return a full cost breakdown with profit analysis.
    job_type: competitive | standard | negotiated | emergency
    """
    manifest = _load_takeoff_manifest()
    takeoff = ps_get_takeoff(manifest if manifest else None)
    if not takeoff["success"]:
        return {"success": False, "error": f"PlanSwift error: {takeoff.get('error')}"}

    items = takeoff["data"].get("items", [])
    if not items:
        return {"success": False, "error": "No takeoff items in PlanSwift. Run the takeoff first."}

    oap_rate = OAP_RATES.get(job_type.lower(), OAP_RATES["standard"])
    line_items = []
    section_totals = {}

    for item in items:
        section = item.get("section", "General")
        name = item.get("item", "")
        unit = item.get("unit", "LF").upper()
        try:
            qty = float(item.get("quantity") or item.get("length") or 0)
        except (ValueError, TypeError):
            qty = 0.0
        if qty <= 0:
            continue

        sec_lower = section.lower()
        if any(w in sec_lower for w in ("storm", "drain")):
            util_type = "storm"
        elif "water" in sec_lower:
            util_type = "water"
        elif any(w in sec_lower for w in ("sanitary", "sewer")):
            util_type = "sewer"
        elif any(w in sec_lower for w in ("fire", "fdc")):
            util_type = "fire"
        else:
            util_type = "storm"

        size_m = re.search(r'(\d+)', name)
        size = size_m.group(1) if size_m else "0"
        material = next((m for m in ("RCP", "C900", "SDR26", "SDR-26", "HDPE", "DI", "PVC")
                         if m.lower() in name.lower()), "")

        is_struct = unit == "EA" or any(w in name.lower() for w in
            ("manhole", "inlet", "junction", "headwall", "hydrant",
             "valve", "cleanout", "service", "dcva", "backflow", "meter"))

        unit_cost = _lookup_struct_rate(name, util_type) if is_struct else _lookup_pipe_rate(util_type, size, material)
        extension = round(qty * unit_cost, 2)

        line_items.append({
            "section": section, "item": name, "qty": qty,
            "unit": unit, "unit_cost": unit_cost, "extension": extension,
        })
        section_totals[section] = section_totals.get(section, 0) + extension

    direct_cost = sum(li["extension"] for li in line_items)
    mob = max(7000, round(direct_cost * 0.04))
    testing = 3500
    total_direct = direct_cost + mob + testing
    oap_amount = round(total_direct * oap_rate)
    subtotal = total_direct + oap_amount
    sales_tax = round(direct_cost * 0.50 * 0.0825) if is_private else 0
    total_bid = subtotal + sales_tax
    # Overhead ~15% of direct, profit = remainder of O&P
    overhead = round(total_direct * 0.15)
    profit = oap_amount - overhead
    margin_pct = round((profit / total_bid) * 100, 1) if total_bid > 0 else 0
    unpriced = [li["item"] for li in line_items if li["unit_cost"] == 0]

    return {
        "success": True,
        "data": {
            "job_name": job_name,
            "gc_name": gc_name,
            "job_type": job_type,
            "oap_rate_pct": int(oap_rate * 100),
            "line_items": line_items,
            "section_totals": section_totals,
            "direct_cost": direct_cost,
            "mobilization": mob,
            "testing": testing,
            "total_direct_cost": total_direct,
            "oap_amount": oap_amount,
            "subtotal_with_oap": subtotal,
            "sales_tax": sales_tax,
            "total_bid": total_bid,
            "estimated_profit": profit,
            "estimated_margin_pct": margin_pct,
            "unpriced_items": unpriced,
        }
    }


def queue_purchase(vendor: str, amount: float, description: str,
                   justification: str = "", **_) -> dict:
    """Queue a purchase or supplier order for Corey's approval. Never commits money automatically."""
    approval_id = queue_approval(
        action_type="purchase",
        description=(f"PURCHASE REQUEST\nVendor: {vendor}\n"
                     f"Amount: ${amount:,.2f}\nDescription: {description}\n"
                     f"Justification: {justification}"),
        payload={"vendor": vendor, "amount": amount,
                 "description": description, "justification": justification},
    )
    return {
        "success": True, "queued": True, "approval_id": approval_id,
        "message": f"Purchase queued for your approval — ${amount:,.2f} to {vendor}. ID: {approval_id}",
    }


def generate_proposal(estimate_data: dict, project_address: str = "",
                       scope_notes: str = "", **_) -> dict:
    """
    Build a bid proposal from an estimate and queue the file write for Corey's approval.
    estimate_data: the full dict from estimate_from_takeoff (pass the whole result or just 'data').
    """
    d = estimate_data.get("data", estimate_data)
    job_name = d.get("job_name", "Project")
    gc_name = d.get("gc_name", "General Contractor")
    total_bid = d.get("total_bid", 0)
    section_totals = d.get("section_totals", {})
    mob = d.get("mobilization", 0)
    testing = d.get("testing", 0)
    sales_tax = d.get("sales_tax", 0)
    oap_pct = d.get("oap_rate_pct", 25)
    profit = d.get("estimated_profit", 0)
    margin = d.get("estimated_margin_pct", 0)
    today = datetime.now().strftime("%B %d, %Y")

    lines = [
        "STORMLINE UTILITIES, LLC",
        "(469) 732-1133  |  corey@stormlineutilities.com  |  stormlineutilities.com",
        "",
        "PROPOSAL",
        f"Date:         {today}",
        f"Project:      {job_name}",
    ]
    if project_address:
        lines.append(f"Location:     {project_address}")
    lines += [
        f"Submitted to: {gc_name}",
        "",
        "=" * 64,
        "SCOPE OF WORK",
        "=" * 64,
        "Stormline Utilities, LLC proposes to furnish all labor,",
        "materials, and equipment for the underground utility work",
        "described below, per the referenced plans and specifications.",
        "",
    ]
    if scope_notes:
        lines += [scope_notes, ""]

    lines += ["=" * 64, "PRICE SUMMARY", "=" * 64, ""]
    for section, sub in sorted(section_totals.items()):
        lines.append(f"  {section:<40} ${sub:>12,.2f}")
    if mob:
        lines.append(f"  {'Mobilization':<40} ${mob:>12,.2f}")
    if testing:
        lines.append(f"  {'Testing & Startup':<40} ${testing:>12,.2f}")
    if sales_tax:
        lines.append(f"  {'Sales Tax (8.25% materials)':<40} ${sales_tax:>12,.2f}")
    lines += [
        "",
        "  " + "-" * 58,
        f"  {'TOTAL BASE BID':<40} ${total_bid:>12,.2f}",
        "  " + "-" * 58,
        "",
        "* Rock excavation, dewatering, and utility conflict resolution",
        "  are excluded and quoted as Additional Pricing if required.",
        "* Prevailing/Davis-Bacon wage does not apply unless stated.",
        "* Quote valid 30 days. Payment terms: Net 30.",
        "",
        "=" * 64,
        "Respectfully submitted,",
        "",
        "Corey Tigert",
        "Owner, Stormline Utilities, LLC",
        "(469) 732-1133",
    ]
    proposal_text = "\n".join(lines)

    safe_name = re.sub(r'[^\w\s-]', '', job_name).strip().replace(' ', '_')
    out_path = (f"/mnt/c/Users/Corey Tigert/OneDrive/Desktop/"
                f"PROPOSAL_{safe_name}_{datetime.now().strftime('%Y%m%d')}.txt")

    approval_id = queue_approval(
        action_type="file_write",
        description=(f"Generate proposal: {job_name}\n"
                     f"Total bid: ${total_bid:,.2f}  |  Est. profit: ${profit:,.0f} ({margin}%)\n"
                     f"GC: {gc_name}\nSave to Desktop as PROPOSAL_{safe_name}_...txt"),
        payload={"path": out_path, "content": proposal_text},
    )
    return {
        "success": True, "queued": True, "approval_id": approval_id,
        "preview": "\n".join(lines[:30]),
        "total_bid": total_bid,
        "estimated_profit": profit,
        "estimated_margin_pct": margin,
        "message": (f"Proposal ready — ${total_bid:,.2f} total bid, "
                    f"${profit:,.0f} profit ({margin}%). Queued for your approval. ID: {approval_id}"),
    }


# ─── Projects ────────────────────────────────────────────────────────────────

def _load_projects() -> list:
    if not os.path.exists(config.projects_file):
        return []
    with open(config.projects_file) as f:
        return json.load(f)

def _save_projects(projects: list):
    with open(config.projects_file, 'w') as f:
        json.dump(projects, f, indent=2)

def list_projects(status_filter: str = None) -> dict:
    """List projects, optionally filtered by status."""
    projects = _load_projects()
    if status_filter:
        projects = [p for p in projects if p.get('status', '').lower() == status_filter.lower()]
    return {"projects": projects, "count": len(projects)}

def add_project(name: str, gc_name: str, status: str, bid_amount: float = None,
                address: str = None, notes: str = None) -> dict:
    """Add a new project to the pipeline."""
    projects = _load_projects()
    project = {
        "id": f"proj-{uuid.uuid4().hex[:8]}",
        "name": name,
        "gc_name": gc_name,
        "status": status,
        "bid_amount": bid_amount,
        "address": address,
        "notes": notes,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    projects.append(project)
    _save_projects(projects)
    return {"success": True, "project": project}

def update_project(project_id: str, **updates) -> dict:
    """Update an existing project."""
    projects = _load_projects()
    for p in projects:
        if p['id'] == project_id:
            p.update(updates)
            p['updated_at'] = datetime.now().isoformat()
            _save_projects(projects)
            return {"success": True, "project": p}
    return {"success": False, "error": f"Project {project_id} not found"}


# ─── Website ─────────────────────────────────────────────────────────────────

def read_website_section(section: str) -> dict:
    """
    Read a section of the website HTML.
    section: 'hero', 'services', 'about', 'contact', 'full'
    """
    if not os.path.exists(config.website_path):
        return {"error": f"Website file not found at {config.website_path}"}

    with open(config.website_path) as f:
        html = f.read()

    if section == 'full':
        # Return just the text content, stripped of most tags
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return {"section": "full", "content": text[:3000]}

    # Extract specific sections
    section_patterns = {
        'hero': r'<section[^>]*(?:hero|banner)[^>]*>(.*?)</section>',
        'services': r'<section[^>]*(?:service)[^>]*>(.*?)</section>',
        'about': r'<section[^>]*(?:about)[^>]*>(.*?)</section>',
        'contact': r'<section[^>]*(?:contact)[^>]*>(.*?)</section>',
    }

    pattern = section_patterns.get(section.lower())
    if not pattern:
        return {"error": f"Unknown section: {section}. Use: hero, services, about, contact, full"}

    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
    if match:
        raw = match.group(1)
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        return {"section": section, "content": text[:2000], "found": True}

    return {"section": section, "content": "", "found": False,
            "note": f"Section '{section}' not found in HTML — may use different class/id names"}

def update_website_text(old_text: str, new_text: str) -> dict:
    """
    Replace specific text in the website HTML file.
    Queues as approval — does NOT write directly.
    """
    if not os.path.exists(config.website_path):
        return {"error": f"Website file not found at {config.website_path}"}

    with open(config.website_path) as f:
        html = f.read()

    if old_text not in html:
        return {"error": f"Text not found in website: '{old_text[:80]}'"}

    new_html = html.replace(old_text, new_text, 1)
    approval_id = queue_approval(
        action_type="website_update",
        description=f"Replace website text:\nOLD: {old_text[:120]}\nNEW: {new_text[:120]}",
        payload={"website_path": config.website_path, "new_html": new_html}
    )
    return {"success": True, "queued": True, "approval_id": approval_id,
            "message": f"Website update queued for approval. ID: {approval_id}"}


# ─── Approvals ───────────────────────────────────────────────────────────────

def _load_approvals() -> list:
    if not os.path.exists(config.approvals_file):
        return []
    with open(config.approvals_file) as f:
        return json.load(f)

def _save_approvals(approvals: list):
    with open(config.approvals_file, 'w') as f:
        json.dump(approvals, f, indent=2)

def queue_approval(action_type: str, description: str, payload: Any) -> str:
    """Queue an action for approval. Returns the approval ID."""
    approvals = _load_approvals()
    approval_id = f"appr-{uuid.uuid4().hex[:8]}"
    approvals.append({
        "id": approval_id,
        "type": action_type,
        "description": description,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    })
    _save_approvals(approvals)
    return approval_id

def list_pending_approvals() -> dict:
    approvals = _load_approvals()
    pending = [a for a in approvals if a['status'] == 'pending']
    return {"approvals": pending, "count": len(pending)}

def process_approval(approval_id: str, approved: bool) -> dict:
    """Approve or reject a queued action. If approved, executes it."""
    approvals = _load_approvals()
    for a in approvals:
        if a['id'] == approval_id and a['status'] == 'pending':
            if approved:
                result = _execute_approval(a)
                a['status'] = 'approved'
                a['executed_at'] = datetime.now().isoformat()
                a['result'] = result
            else:
                a['status'] = 'rejected'
                a['rejected_at'] = datetime.now().isoformat()
                result = {"rejected": True}
            _save_approvals(approvals)
            return {"success": True, "approval": a, "result": result}
    return {"success": False, "error": f"Approval {approval_id} not found or not pending"}

def _execute_approval(approval: dict) -> dict:
    """Execute an approved action."""
    action_type = approval['type']
    payload = approval['payload']

    if action_type == 'website_update':
        try:
            with open(payload['website_path'], 'w') as f:
                f.write(payload['new_html'])
            return {"success": True, "message": "Website updated"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action_type == 'email_draft':
        try:
            from gmail import send_email
            result = send_email(payload['to'], payload['subject'], payload['body'])
            return {"success": True, "message": f"Email sent to {payload['to']}", **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action_type == 'file_write':
        try:
            os.makedirs(os.path.dirname(os.path.abspath(payload['path'])), exist_ok=True)
            with open(payload['path'], "w") as f:
                f.write(payload['content'])
            return {"success": True, "message": f"File written: {payload['path']}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action_type == 'purchase':
        # Purchase approvals are manual — bot can't execute the payment
        return {
            "success": True,
            "message": (f"Purchase approved: ${payload.get('amount', 0):,.2f} to "
                        f"{payload.get('vendor')}. Proceed manually."),
        }

    return {"success": False, "error": f"Unknown action type: {action_type}"}


# ─── Email ───────────────────────────────────────────────────────────────────

def read_emails(max_results: int = 20, query: str = "") -> dict:
    """Read recent emails from Gmail, filtered and classified."""
    try:
        from gmail import list_emails
        emails = list_emails(max_results=max_results, query=query)
        return {"emails": emails, "count": len(emails)}
    except Exception as e:
        logger.error(f"Gmail read error: {e}")
        return {"error": str(e)}

def queue_email_draft(to: str, subject: str, body: str) -> dict:
    """Queue an email for approval before sending. NEVER sends automatically."""
    approval_id = queue_approval(
        action_type="email_draft",
        description=f"Send email to {to}\nSubject: {subject}\n\n{body[:300]}",
        payload={"to": to, "subject": subject, "body": body}
    )
    return {"success": True, "queued": True, "approval_id": approval_id,
            "message": f"Email draft queued for approval. ID: {approval_id}"}


# ─── Tool registry ────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_projects",
        "description": "List projects in the Stormline bid/job pipeline. Can filter by status: bid_invited, estimating, submitted, won, lost, active, completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Optional status filter (e.g. 'estimating', 'submitted', 'won')"
                }
            }
        }
    },
    {
        "name": "add_project",
        "description": "Add a new project/bid to the pipeline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name/description"},
                "gc_name": {"type": "string", "description": "General contractor name"},
                "status": {"type": "string", "description": "Status: bid_invited, estimating, submitted, won, lost"},
                "bid_amount": {"type": "number", "description": "Bid amount in dollars"},
                "address": {"type": "string", "description": "Project address"},
                "notes": {"type": "string", "description": "Additional notes"},
            },
            "required": ["name", "gc_name", "status"]
        }
    },
    {
        "name": "update_project",
        "description": "Update an existing project's status, bid amount, or notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "status": {"type": "string"},
                "bid_amount": {"type": "number"},
                "notes": {"type": "string"},
                "gc_name": {"type": "string"},
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "read_website_section",
        "description": "Read the current content of a section of the Stormline website.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section to read: 'hero', 'services', 'about', 'contact', or 'full'"
                }
            },
            "required": ["section"]
        }
    },
    {
        "name": "update_website_text",
        "description": "Replace specific text in the website. Queues as an approval — will NOT go live until Corey approves.",
        "input_schema": {
            "type": "object",
            "properties": {
                "old_text": {"type": "string", "description": "Exact text to replace"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["old_text", "new_text"]
        }
    },
    {
        "name": "read_emails",
        "description": "Read recent emails from Gmail. Filters out noise. Returns classified emails (BID_INVITE, SUPPLIER_QUOTE, PLAN_DELIVERY, CHANGE_ORDER, INVOICE, GC_COMMUNICATION, GENERAL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Max emails to fetch (default 20)"},
                "query": {"type": "string", "description": "Gmail search query e.g. 'is:unread', 'from:tanner@gmail.com', 'subject:bid'"},
            }
        }
    },
    {
        "name": "queue_email_draft",
        "description": "Create an email draft for Corey's approval before sending. NEVER sends automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "list_pending_approvals",
        "description": "List all pending approval items (website updates, emails, etc.)",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_status",
        "description": "Test PlanSwift COM connection and return the current job name, page count, and takeoff section count. Use this first to verify PlanSwift is open.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_get_takeoff",
        "description": "Extract all takeoff quantities from the currently open PlanSwift job. Returns sections, items, quantities, units, lengths, areas, and volumes.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_load_pdf",
        "description": "Load a PDF plan set into the current PlanSwift job. Requires the full Windows file path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Full Windows path to the PDF, e.g. C:\\Users\\Corey Tigert\\OneDrive\\Desktop\\PROJECTS\\plans.pdf"
                }
            },
            "required": ["pdf_path"]
        }
    },
    {
        "name": "planswift_list_jobs",
        "description": "List all available job folders under \\Job\\Pages\\PROJECTS in PlanSwift.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_add_section",
        "description": "Add a new takeoff section in PlanSwift (e.g. 'Storm Drainage', 'Water', 'Sanitary Sewer').",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Section name"}},
            "required": ["name"]
        }
    },
    {
        "name": "planswift_add_item",
        "description": "Add a takeoff item to a section. Types: Linear (pipes, conduit), Area (paving, seeding), Count (manholes, inlets, valves).",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Section name (must exist)"},
                "name": {"type": "string", "description": "Item name, e.g. '18-inch RCP'"},
                "item_type": {"type": "string", "description": "Linear, Area, or Count"},
                "unit": {"type": "string", "description": "LF, SF, EA, CY, etc."},
            },
            "required": ["section", "name"]
        }
    },
    {
        "name": "planswift_set_property",
        "description": "Set a property on a PlanSwift takeoff item. Use for setting Quantity, Length, Unit, Description, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": r"Full item path e.g. \Job\Takeoff\Storm Drainage\18-inch RCP"},
                "prop": {"type": "string", "description": "Property name: Quantity, Length, Unit, Description"},
                "value": {"type": "string", "description": "Value to set"},
            },
            "required": ["path", "prop", "value"]
        }
    },
    {
        "name": "planswift_delete_item",
        "description": "Delete a takeoff item or section from PlanSwift.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Full path of item to delete"}},
            "required": ["path"]
        }
    },
    {
        "name": "planswift_get_current_page",
        "description": "Get the name, index, and scale of the currently active page in PlanSwift.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_calibrate_page",
        "description": "Screenshot the current PlanSwift page, use AI Vision to find the scale bar, and store the calibration (pixels-per-foot) for this page. Must be done before tracing pipes on a new page.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_manual_calibrate",
        "description": "Manually set the calibration for a page if auto-calibration fails. Provide page name and pixels-per-foot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_name": {"type": "string"},
                "pixels_per_foot": {"type": "number", "description": "How many pixels equal one foot on this page"},
                "note": {"type": "string", "description": "How you determined this"},
            },
            "required": ["page_name", "pixels_per_foot"]
        }
    },
    {
        "name": "planswift_analyze_pipes",
        "description": "Screenshot the current PlanSwift page and use AI Vision to identify all pipe runs, sizes, materials, structures, and estimated lengths. Returns analysis for review — does NOT create takeoff items yet.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "planswift_create_takeoff_from_analysis",
        "description": "Take the pipe analysis data and create actual takeoff items in PlanSwift with correct quantities. Run planswift_analyze_pipes first and review results before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis": {"type": "object", "description": "The data.pipes/structures from planswift_analyze_pipes result"},
                "section_name": {"type": "string", "description": "Override section name (optional — auto-detected from pipe types if blank)"},
            },
            "required": ["analysis"]
        }
    },
    {
        "name": "estimate_from_takeoff",
        "description": (
            "Pull current PlanSwift takeoff quantities, apply Stormline at-cost rates + O&P, "
            "and return a full cost estimate with line items, section totals, profit, and margin. "
            "Run after takeoff items are in PlanSwift. job_type controls O&P: "
            "competitive=20%, standard=25%, negotiated=30%, emergency=40%."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Project name"},
                "gc_name": {"type": "string", "description": "General contractor name"},
                "job_type": {"type": "string", "description": "competitive | standard | negotiated | emergency (default: standard)"},
                "is_private": {"type": "boolean", "description": "True = private work (add 8.25% sales tax on materials), False = public"},
            }
        }
    },
    {
        "name": "generate_proposal",
        "description": (
            "Build a bid proposal from an estimate and queue the file write for Corey's approval. "
            "Takes the full output from estimate_from_takeoff. "
            "Does NOT include unit prices in the proposal (GC rule). Saves to Desktop as a .txt. "
            "Requires approval before writing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "estimate_data": {"type": "object", "description": "Full result from estimate_from_takeoff"},
                "project_address": {"type": "string", "description": "Project address / city"},
                "scope_notes": {"type": "string", "description": "Additional scope description to include"},
            },
            "required": ["estimate_data"]
        }
    },
    {
        "name": "queue_purchase",
        "description": (
            "Queue a purchase or supplier order for Corey's approval. "
            "NEVER commits money automatically — all purchases require explicit approval. "
            "Use for material orders, equipment rentals, subcontractor POs, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Vendor / supplier name"},
                "amount": {"type": "number", "description": "Dollar amount"},
                "description": {"type": "string", "description": "What is being purchased"},
                "justification": {"type": "string", "description": "Why this purchase is needed"},
            },
            "required": ["vendor", "amount", "description"]
        }
    },
    {
        "name": "fs_list_directory",
        "description": "List files and directories at a given path. Use WSL paths (e.g. /home/corey_tigert/... or /mnt/c/Users/...).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_read_file",
        "description": "Read the contents of a file. Use WSL paths. Truncates at 8000 characters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "fs_write_file",
        "description": "Write content to a file. Direct write only to /home/corey_tigert/stormlineutl/data/ and /tmp/ — all other paths are queued for Corey's approval before writing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "fs_search",
        "description": "Search for text inside files recursively. Good for finding PDFs, locating project files, or searching code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Root directory to search from"},
                "pattern": {"type": "string", "description": "Text to search for (case-insensitive)"},
                "file_glob": {"type": "string", "description": "File name pattern, e.g. '*.pdf', '*.txt', '*' (default all)"}
            },
            "required": ["path", "pattern"]
        }
    },
    {
        "name": "shell_run",
        "description": "Run a shell command on the Linux/WSL system. Returns stdout and stderr. 60 second timeout. Use for running scripts, checking services, git, npm, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Working directory (optional)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "windows_open",
        "description": "Open a file or folder in Windows using Explorer (or default app). Good for opening PDFs, Word docs, folders. Accepts WSL paths (/mnt/c/...) or Windows paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or folder path to open in Windows"}
            },
            "required": ["path"]
        }
    },
]

TOOL_MAP = {
    "list_projects": list_projects,
    "add_project": add_project,
    "update_project": update_project,
    "read_website_section": read_website_section,
    "update_website_text": update_website_text,
    "read_emails": read_emails,
    "queue_email_draft": queue_email_draft,
    "list_pending_approvals": list_pending_approvals,
    "planswift_status": lambda **_: ps_status(),
    "planswift_get_takeoff": lambda **_: ps_get_takeoff(_load_takeoff_manifest() or None),
    "planswift_load_pdf": lambda pdf_path, **_: ps_load_pdf(pdf_path),
    "planswift_list_jobs": lambda **_: ps_list_jobs(),
    "planswift_add_section": lambda name, **_: ps_add_section(name),
    "planswift_add_item": lambda section, name, item_type="Linear", unit="LF", **_: ps_add_item(section, name, item_type, unit),
    "planswift_set_property": lambda path, prop, value, **_: ps_set_property(path, prop, value),
    "planswift_delete_item": lambda path, **_: ps_delete_item(path),
    "planswift_get_current_page": lambda **_: ps_get_current_page(),
    "planswift_calibrate_page": ps_calibrate_page,
    "planswift_manual_calibrate": ps_manual_calibrate,
    "planswift_analyze_pipes": ps_analyze_pipes,
    "planswift_create_takeoff_from_analysis": lambda analysis, section_name="", **_: ps_create_takeoff_from_analysis(analysis, section_name),
    "estimate_from_takeoff": estimate_from_takeoff,
    "generate_proposal": generate_proposal,
    "queue_purchase": queue_purchase,
    "fs_list_directory": _fs_list_directory,
    "fs_read_file": _fs_read_file,
    "fs_write_file": _fs_write_file,
    "fs_search": _fs_search,
    "shell_run": _shell_run,
    "windows_open": _windows_open,
}
