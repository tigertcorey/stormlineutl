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
    $jobName = $ps.GetPropertyResultAsString('\\Job', 'Name', '(none)')
    $pageCount = $ps.GetPropertyResultAsString('\\Job\\Pages', 'ChildCount', '0')
    $takeoffCount = $ps.GetPropertyResultAsString('\\Job\\Takeoff', 'ChildCount', '0')
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


def ps_get_takeoff() -> dict:
    """Extract all quantities from current job — sections, items, qty, unit."""
    script = """
try {
    $ps = New-Object -ComObject PlanSwift9.PlanSwift
    $toCount = [int]$ps.GetPropertyResultAsString('\\Job\\Takeoff', 'ChildCount', '0')

    if ($toCount -eq 0) {
        Write-Output "NO_TAKEOFF_DATA"
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
        exit 0
    }

    Write-Output "SECTIONS: $toCount"
    Write-Output "---CSV---"
    Write-Output "Section,Item,Type,Unit,Quantity,Length,Area,Volume"

    $takeoff = $ps.GetItem('\\Job\\Takeoff')
    for ($s = 0; $s -lt $toCount; $s++) {
        $section = $takeoff.ChildItem($s)
        $sName = $section.GetPropertyResultAsString('Name', '')
        $sChildCount = $section.ChildCount()

        for ($i = 0; $i -lt $sChildCount; $i++) {
            $item = $section.ChildItem($i)
            $iName  = $item.GetPropertyResultAsString('Name', '')
            $iType  = $item.GetPropertyResultAsString('Type', '')
            $iUnit  = $item.GetPropertyResultAsString('Unit', '')
            $iQty   = $item.GetPropertyResultAsString('Quantity', '0')
            $iLen   = $item.GetPropertyResultAsString('Length', '0')
            $iArea  = $item.GetPropertyResultAsString('Area', '0')
            $iVol   = $item.GetPropertyResultAsString('Volume', '0')
            Write-Output "`"$sName`",`"$iName`",`"$iType`",`"$iUnit`",`"$iQty`",`"$iLen`",`"$iArea`",`"$iVol`""
            [System.Runtime.InteropServices.Marshal]::ReleaseComObject($item) | Out-Null
        }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($section) | Out-Null
    }

    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($takeoff) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ps) | Out-Null
    Write-Output "---END---"
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
"""
    ok, out, err = _run_ps(script)
    if not ok and not out:
        return {"success": False, "error": err or "PowerShell execution failed"}

    if "NO_TAKEOFF_DATA" in out:
        return {"success": True, "data": {"sections": 0, "items": []}}

    if out.startswith("ERROR:"):
        return {"success": False, "error": out[6:].strip()}

    # Parse CSV block
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
                    "section": row[0],
                    "item": row[1],
                    "type": row[2],
                    "unit": row[3],
                    "quantity": row[4],
                    "length": row[5] if len(row) > 5 else "0",
                    "area": row[6] if len(row) > 6 else "0",
                    "volume": row[7] if len(row) > 7 else "0",
                })
        except Exception:
            pass

    # Extract section count from header
    section_count = 0
    for line in out.splitlines():
        if line.startswith("SECTIONS:"):
            try:
                section_count = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            break

    return {"success": True, "data": {"sections": section_count, "items": items}}


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
