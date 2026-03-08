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
from planswift import ps_status, ps_get_takeoff, ps_load_pdf, ps_list_jobs

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
    "planswift_get_takeoff": lambda **_: ps_get_takeoff(),
    "planswift_load_pdf": lambda pdf_path, **_: ps_load_pdf(pdf_path),
    "planswift_list_jobs": lambda **_: ps_list_jobs(),
    "fs_list_directory": _fs_list_directory,
    "fs_read_file": _fs_read_file,
    "fs_write_file": _fs_write_file,
    "fs_search": _fs_search,
    "shell_run": _shell_run,
    "windows_open": _windows_open,
}
