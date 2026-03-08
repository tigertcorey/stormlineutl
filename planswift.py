"""
PlanSwift 11 Pro integration via PowerShell COM bridge.
Runs inline PowerShell via subprocess — WSL2 calls powershell.exe directly.
"""

import subprocess
import logging
import csv
import io

logger = logging.getLogger(__name__)

TIMEOUT = 60
PS_FLAGS = [
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    "-NonInteractive",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command",
]


def _run_ps(script: str) -> tuple[bool, str, str]:
    """Run a PowerShell script. Returns (success, stdout, stderr)."""
    try:
        proc = subprocess.Popen(
            PS_FLAGS + [script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT)
            return proc.returncode == 0, stdout.strip(), stderr.strip()
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill.exe', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
            proc.kill()
            proc.communicate()
            return False, "", "PowerShell timed out after 60 seconds"
    except FileNotFoundError:
        return False, "", "powershell.exe not found at expected path"
    except Exception as e:
        return False, "", str(e)


def ps_status() -> dict:
    """Test COM connection, return current job name + page/takeoff counts."""
    script = """
try {
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $jobName = $ps.GetPropertyResultAsString('\\Job', 'Name', '(none)')
    $pageCount = $ps.GetPropertyResultAsString('\\Job\\Pages', 'ChildCount', '0')
    $takeoff = $root.GetItem('\\Job\\Takeoff')
    $takeoffCount = if ($takeoff) { $takeoff.ChildCount() } else { 0 }
    Write-Output "STATUS: CONNECTED"
    Write-Output "JOB: $jobName"
    Write-Output "PAGES: $pageCount"
    Write-Output "TAKEOFF_SECTIONS: $takeoffCount"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
} catch {
    Write-Output "STATUS: FAILED"
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err or "PowerShell execution failed"}

    lines = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in out.splitlines() if ":" in line)}

    if lines.get("STATUS") == "FAILED":
        return {"success": False, "error": lines.get("ERROR", "Unknown COM error")}

    return {
        "success": True,
        "data": {
            "status": "connected",
            "job": lines.get("JOB", "(none)"),
            "pages": int(lines.get("PAGES", "0")),
            "takeoff_sections": int(lines.get("TAKEOFF_SECTIONS", "0")),
        }
    }


def ps_get_takeoff(manifest: dict = None) -> dict:
    """
    Extract all quantities from current job using a section/item name manifest.
    manifest: {section_name: [item_name, ...]} — built by ps_create_takeoff_from_analysis.
    If no manifest provided, returns section count only.
    """
    if not manifest:
        # Just return section count without item details
        script = """
try {
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $takeoff = $root.GetItem('\\Job\\Takeoff')
    if (-not $takeoff) { Write-Output "SECTIONS: 0" }
    else { Write-Output "SECTIONS: $($takeoff.ChildCount())" }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
} catch { Write-Output "ERROR: $($_.Exception.Message)" }
"""
        ok, out, err = _run_ps(script)
        if not ok and not out:
            return {"success": False, "error": err}
        for line in out.splitlines():
            if line.startswith("SECTIONS:"):
                try:
                    count = int(line.split(":", 1)[1].strip())
                    return {"success": True, "data": {"sections": count, "items": []}}
                except ValueError:
                    pass
        return {"success": True, "data": {"sections": 0, "items": []}}

    # Build a single PS script that queries every known section+item by name
    queries = []
    for sec_name, item_names in manifest.items():
        safe_sec = sec_name.replace("'", "''")
        for item_name in item_names:
            safe_item = item_name.replace("'", "''")
            path = f"\\Job\\Takeoff\\{safe_sec}\\{safe_item}"
            queries.append(
                f"$item = $root.GetItem('{path}');"
                f"if ($item) {{"
                f"$qty=$item.GetPropertyResultAsString('Quantity','0');"
                f"$unit=$item.GetPropertyResultAsString('Unit','LF');"
                f"$len=$item.GetPropertyResultAsString('Length','0');"
                f"Write-Output \"`\"{safe_sec}`\",`\"{safe_item}`\",`\"Linear`\",`\"$unit`\",`\"$qty`\",`\"$len`\"\";"
                f"}}"
            )

    if not queries:
        return {"success": True, "data": {"sections": 0, "items": []}}

    body = "\n".join(queries)
    script = f"""
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    Write-Output "---CSV---"
    Write-Output "Section,Item,Type,Unit,Quantity,Length"
    {body}
    Write-Output "---END---"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out and "---CSV---" not in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}

    items = []
    in_csv = False
    for line in out.splitlines():
        if line == "---CSV---":
            in_csv = True
            continue
        if line == "---END---":
            break
        if not in_csv or line.startswith("Section,"):
            continue
        try:
            row = next(csv.reader(io.StringIO(line)))
            if len(row) >= 5:
                items.append({
                    "section": row[0], "item": row[1], "type": row[2],
                    "unit": row[3], "quantity": row[4],
                    "length": row[5] if len(row) > 5 else "0",
                })
        except Exception:
            pass

    sections = len(manifest)
    return {"success": True, "data": {"sections": sections, "items": items}}


def ps_load_pdf(pdf_windows_path: str) -> dict:
    """Load a PDF plan file into the current PlanSwift job."""
    # Escape single quotes in path for PowerShell
    safe_path = pdf_windows_path.replace("'", "''")
    script = f"""
$PdfPath = '{safe_path}'
if (-not (Test-Path $PdfPath)) {{
    Write-Output "STATUS: FAILED"
    Write-Output "ERROR: File not found: $PdfPath"
    exit 1
}}
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $ps.AttachFile($PdfPath)
    Start-Sleep -Seconds 2
    $pageCount = $ps.GetPropertyResultAsString('\\Job\\Pages', 'ChildCount', '0')
    Write-Output "STATUS: OK"
    Write-Output "LOADED: $PdfPath"
    Write-Output "PAGES: $pageCount"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "STATUS: FAILED"
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err or "PowerShell execution failed"}

    lines = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in out.splitlines() if ":" in line)}

    if lines.get("STATUS") == "FAILED":
        return {"success": False, "error": lines.get("ERROR", "Unknown error")}

    return {
        "success": True,
        "data": {
            "loaded": lines.get("LOADED", pdf_windows_path),
            "pages": int(lines.get("PAGES", "0")),
        }
    }


def ps_list_jobs() -> dict:
    """List available job folders under \\Job\\Pages\\PROJECTS."""
    script = """
try {
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $projectsPath = '\\Job\\Pages\\PROJECTS'
    $pagesCount = [int]$ps.GetPropertyResultAsString('\\Job\\Pages', 'ChildCount', '0')
    if ($pagesCount -eq 0) {
        Write-Output "COUNT: 0"
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
        exit 0
    }
    $projects = $ps.GetItem($projectsPath)
    $count = $projects.ChildCount()
    Write-Output "COUNT: $count"
    for ($i = 0; $i -lt $count; $i++) {
        $child = $projects.ChildItem($i)
        $name = $child.GetPropertyResultAsString('Name', '(unnamed)')
        Write-Output "JOB: $name"
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($child) | Out-Null
    }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($projects) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err or "PowerShell execution failed"}

    if out.startswith("ERROR:"):
        return {"success": False, "error": out[6:].strip()}

    jobs = [line[5:].strip() for line in out.splitlines() if line.startswith("JOB:")]
    count_line = next((line for line in out.splitlines() if line.startswith("COUNT:")), None)
    count = int(count_line.split(":", 1)[1].strip()) if count_line else len(jobs)

    return {"success": True, "data": {"count": count, "jobs": jobs}}


# ─── Write / Control ──────────────────────────────────────────────────────────

def ps_add_section(name: str) -> dict:
    """Add a new takeoff section under \\Job\\Takeoff."""
    safe = name.replace("'", "''")
    script = f"""
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $takeoff = $root.GetItem('\\Job\\Takeoff')
    # Check if section already exists
    $existing = $takeoff.GetItem('{safe}')
    if ($existing) {{
        Write-Output "EXISTS: $($existing.FullPath())"
    }} else {{
        $sec = $takeoff.NewItemEx('', 'Section', '')
        $sec.SetPropertyFormula('Name', '{safe}')
        Write-Output "CREATED: $($sec.FullPath())"
    }}
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}
    existed = "EXISTS:" in out
    return {"success": True, "path": f"\\Job\\Takeoff\\{name}", "already_existed": existed}


def ps_add_item(section: str, name: str, item_type: str = "Linear", unit: str = "LF") -> dict:
    """Add a takeoff item to a section. item_type: Linear, Area, Count, Assembly."""
    safe_section = section.replace("'", "''")
    safe_name = name.replace("'", "''")
    safe_unit = unit.replace("'", "''")
    path = f"\\Job\\Takeoff\\{section}\\{name}"
    script = f"""
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $sec = $root.GetItem('\\Job\\Takeoff\\{safe_section}')
    if (-not $sec) {{ Write-Output "ERROR: Section not found: {safe_section}"; exit 1 }}
    $item = $sec.NewItemEx('', '{item_type}', '')
    $item.SetPropertyFormula('Name', '{safe_name}')
    $item.SetPropertyFormula('Unit', '{safe_unit}')
    Write-Output "CREATED: $($item.FullPath())"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}
    return {"success": True, "path": path, "type": item_type, "unit": unit}


def ps_set_property(path: str, prop: str, value: str) -> dict:
    """Set any property on a PlanSwift item via SetPropertyFormula."""
    safe_path = path.replace("'", "''")
    safe_prop = prop.replace("'", "''")
    safe_val = value.replace("'", "''")
    script = f"""
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $item = $root.GetItem('{safe_path}')
    if (-not $item) {{ Write-Output "ERROR: Item not found: {safe_path}"; exit 1 }}
    $item.SetPropertyFormula('{safe_prop}', '{safe_val}')
    Write-Output "SET: {safe_path} | {safe_prop} = {safe_val}"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}
    return {"success": True, "path": path, "property": prop, "value": value}


def ps_delete_item(path: str) -> dict:
    """Delete an item or section from the takeoff."""
    safe_path = path.replace("'", "''")
    script = f"""
try {{
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $root = $ps.Root()
    $item = $root.GetItem('{safe_path}')
    if (-not $item) {{ Write-Output "ERROR: Item not found: {safe_path}"; exit 1 }}
    $item.Delete()
    Write-Output "DELETED: {safe_path}"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
}} catch {{
    Write-Output "ERROR: $($_.Exception.Message)"
}}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}
    return {"success": True, "deleted": path}


def ps_get_current_page() -> dict:
    """Get the name and index of the currently active page in PlanSwift."""
    script = """
try {
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $pageName = $ps.GetPropertyResultAsString('\\Job', 'CurrentPageName', '')
    $pageIndex = $ps.GetPropertyResultAsString('\\Job', 'CurrentPageIndex', '-1')
    $scale = $ps.GetPropertyResultAsString('\\Job', 'CurrentPageScale', '')
    Write-Output "PAGE: $pageName"
    Write-Output "INDEX: $pageIndex"
    Write-Output "SCALE: $scale"
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}
    lines = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in out.splitlines() if ":" in line)}
    return {
        "success": True,
        "data": {
            "page_name": lines.get("PAGE", ""),
            "page_index": lines.get("INDEX", "-1"),
            "scale": lines.get("SCALE", ""),
        }
    }


def ps_screenshot() -> dict:
    """Capture the PlanSwift window as a PNG. Returns the WSL path to the saved image."""
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinCapture {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
[WinCapture]::SetProcessDPIAware() | Out-Null
$procs = Get-Process | Where-Object { $_.MainWindowTitle -like "*PlanSwift*" -or $_.ProcessName -like "*planswift*" }
if ($procs.Count -eq 0) { Write-Output "ERROR: PlanSwift window not found"; exit 1 }
$hwnd = $procs[0].MainWindowHandle
[WinCapture]::ShowWindow($hwnd, 3) | Out-Null
[WinCapture]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 1000
$rect = New-Object WinCapture+RECT
[WinCapture]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$w = $rect.Right - $rect.Left
$h = $rect.Bottom - $rect.Top
if ($w -le 0 -or $h -le 0) {
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $w = $screen.Width; $h = $screen.Height
    $rect.Left = 0; $rect.Top = 0
    Write-Output "WARN: Using full screen fallback"
}
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bmp.Size)
$outPath = "$env:TEMP\ps_screenshot.png"
$bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()
Write-Output "SAVED: $outPath"
Write-Output "WIDTH: $w"
Write-Output "HEIGHT: $h"
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err}
    if "ERROR:" in out:
        return {"success": False, "error": out.split("ERROR:", 1)[1].strip()}

    lines = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in out.splitlines() if ":" in line)}
    win_path = lines.get("SAVED", "")
    if not win_path:
        return {"success": False, "error": "Screenshot path not returned"}

    # Convert Windows temp path to WSL path
    # e.g. C:\Users\...\AppData\Local\Temp\ps_screenshot.png
    # → /mnt/c/Users/.../AppData/Local/Temp/ps_screenshot.png
    wsl_path = win_path.replace("\\", "/")
    if wsl_path[1] == ":":
        wsl_path = "/mnt/" + wsl_path[0].lower() + wsl_path[2:]

    return {
        "success": True,
        "win_path": win_path,
        "wsl_path": wsl_path,
        "width": int(lines.get("WIDTH", "0")),
        "height": int(lines.get("HEIGHT", "0")),
    }
