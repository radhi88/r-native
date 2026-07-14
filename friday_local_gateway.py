from __future__ import annotations

import json
import os
import tempfile
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


MT5_ROOT = Path(r"C:\Users\Radhi\MT5")
AGENTS_APP = MT5_ROOT / "mnt" / "agents" / "output" / "app"
LOG_DIR = MT5_ROOT / "gateway_dispatch_logs"

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
DB_NAME = os.getenv("DB_NAME", "agents_app")

app = FastAPI(title="FRIDAY Local Gateway", version="1.2.0")


class DispatchRequest(BaseModel):
    task: str
    max_agents: int = 3
    files_per_agent: int = 5
    chars_per_file: int = 2200
    ctx: int = 8192
    agent_roles: list[str] | None = None
    dispatch_model: str | None = None
    target_files: list[str] | None = None


def clean_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return value


def clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: clean_value(value) for key, value in row.items()} for row in rows]


def db_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def table_exists(cur, table_name: str) -> bool:
    cur.execute("SHOW TABLES LIKE %s", (table_name,))
    return cur.fetchone() is not None


def table_columns(cur, table_name: str) -> set[str]:
    cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
    return {row["Field"] for row in cur.fetchall()}


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "FRIDAY Local Gateway",
        "version": "1.2.0",
        "mt5_root": str(MT5_ROOT),
        "agents_app": str(AGENTS_APP),
    }


@app.get("/system/mesh")
def system_mesh(refresh: bool = False) -> dict[str, Any]:
    mesh_file = MT5_ROOT / ".jarvis_agents" / "friday_system_mesh.json"
    mesh_script = MT5_ROOT / "friday_system_mesh.py"

    if refresh and mesh_script.exists():
        subprocess.run(
            [sys.executable, str(mesh_script), "--refresh-genomes"],
            cwd=str(MT5_ROOT),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    if not mesh_file.exists() and mesh_script.exists():
        subprocess.run(
            [sys.executable, str(mesh_script)],
            cwd=str(MT5_ROOT),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    if not mesh_file.exists():
        return {
            "status": "missing",
            "detail": f"System mesh file not found: {mesh_file}",
        }

    try:
        return json.loads(mesh_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
            "file": str(mesh_file),
        }


@app.get("/debug/db")
def debug_db():
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                tables = clean_rows(cur.fetchall())

                return {
                    "status": "ok",
                    "database": DB_NAME,
                    "tables": tables,
                }

    except Exception as e:
        return {
            "status": "error",
            "detail": str(e),
        }


@app.get("/dispatch/jobs")
def list_dispatch_jobs(limit: int = 10):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                if not table_exists(cur, "dispatch_jobs"):
                    return {
                        "rows": [],
                        "note": "dispatch_jobs table not found",
                    }

                cols = table_columns(cur, "dispatch_jobs")

                wanted = [
                    "id",
                    "objective",
                    "user_task",
                    "status",
                    "model",
                    "mt5_path",
                    "report_path",
                    "patch_json_path",
                    "created_at",
                    "updated_at",
                ]

                selected = [column for column in wanted if column in cols]

                if not selected:
                    return {
                        "rows": [],
                        "note": "no expected columns found",
                        "columns": sorted(cols),
                    }

                sql = f"""
                    SELECT {", ".join(f"`{column}`" for column in selected)}
                    FROM `dispatch_jobs`
                    ORDER BY `id` DESC
                    LIMIT %s
                """

                cur.execute(sql, (int(limit),))
                rows = clean_rows(cur.fetchall())

                return {
                    "table": "dispatch_jobs",
                    "columns": selected,
                    "rows": rows,
                }

    except Exception as e:
        return {
            "error": "dispatch_jobs_failed",
            "detail": str(e),
        }


@app.get("/dispatch/patches")
def list_patches(limit: int = 20):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                if not table_exists(cur, "dispatch_patch_proposals"):
                    return {
                        "rows": [],
                        "note": "dispatch_patch_proposals table not found",
                    }

                cols = table_columns(cur, "dispatch_patch_proposals")

                wanted = [
                    "id",
                    "job_id",
                    "agent_id",
                    "agent_name",
                    "agent_role",
                    "target_file",
                    "reason",
                    "risk",
                    "approved",
                    "applied",
                    "created_at",
                ]

                selected = [column for column in wanted if column in cols]

                if not selected:
                    return {
                        "rows": [],
                        "note": "no expected columns found",
                        "columns": sorted(cols),
                    }

                sql = f"""
                    SELECT {", ".join(f"`{column}`" for column in selected)}
                    FROM `dispatch_patch_proposals`
                    ORDER BY `id` DESC
                    LIMIT %s
                """

                cur.execute(sql, (int(limit),))
                rows = clean_rows(cur.fetchall())

                return {
                    "table": "dispatch_patch_proposals",
                    "columns": selected,
                    "rows": rows,
                }

    except Exception as e:
        return {
            "error": "dispatch_patches_failed",
            "detail": str(e),
        }



# -----------------------------
# Patch Review Gate endpoints
# -----------------------------

@app.get("/patches")
def review_patches(
    limit: int = 50,
    risk: str | None = None,
    approved: int | None = None,
    applied: int | None = None,
):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                if not table_exists(cur, "dispatch_patch_proposals"):
                    return {
                        "rows": [],
                        "note": "dispatch_patch_proposals table not found",
                    }

                where = []
                params = []

                if risk:
                    where.append("LOWER(`risk`) = LOWER(%s)")
                    params.append(risk)

                if approved is not None:
                    where.append("`approved` = %s")
                    params.append(int(approved))

                if applied is not None:
                    where.append("`applied` = %s")
                    params.append(int(applied))

                where_sql = ("WHERE " + " AND ".join(where)) if where else ""
                safe_limit = max(1, min(int(limit), 200))

                sql = f"""
                    SELECT
                        id,
                        job_id,
                        agent_id,
                        agent_name,
                        agent_role,
                        target_file,
                        reason,
                        risk,
                        approved,
                        applied,
                        created_at
                    FROM `dispatch_patch_proposals`
                    {where_sql}
                    ORDER BY
                        CASE
                            WHEN risk = 'High' THEN 1
                            WHEN risk = 'Medium' THEN 2
                            WHEN risk = 'Low' THEN 3
                            ELSE 4
                        END,
                        id DESC
                    LIMIT %s
                """

                params.append(safe_limit)
                cur.execute(sql, tuple(params))
                rows = clean_rows(cur.fetchall())

                return {
                    "table": "dispatch_patch_proposals",
                    "rows": rows,
                }

    except Exception as e:
        return {
            "error": "patch_review_failed",
            "detail": str(e),
        }


@app.get("/patches/{patch_id}")
def patch_details(patch_id: int):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                if not table_exists(cur, "dispatch_patch_proposals"):
                    raise HTTPException(
                        status_code=404,
                        detail="dispatch_patch_proposals table not found",
                    )

                cur.execute(
                    """
                    SELECT
                        id,
                        job_id,
                        agent_id,
                        agent_name,
                        agent_role,
                        target_file,
                        reason,
                        risk,
                        patch,
                        approved,
                        applied,
                        created_at
                    FROM `dispatch_patch_proposals`
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (patch_id,),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Patch #{patch_id} not found",
                    )

                return {
                    "row": {key: clean_value(value) for key, value in row.items()}
                }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": "patch_details_failed",
            "detail": str(e),
        }


@app.post("/patches/{patch_id}/approve")
def approve_patch(patch_id: int):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, patch, applied
                    FROM `dispatch_patch_proposals`
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (patch_id,),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Patch #{patch_id} not found",
                    )

                if int(row.get("applied") or 0) == 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Patch #{patch_id} is already applied",
                    )

                patch_text = str(row.get("patch") or "").strip()

                if not patch_text:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Patch #{patch_id} is empty and cannot be approved",
                    )

                cur.execute(
                    """
                    UPDATE `dispatch_patch_proposals`
                    SET approved = 1,
                        applied = 0
                    WHERE id = %s
                    """,
                    (patch_id,),
                )

                return {
                    "status": "approved",
                    "patch_id": patch_id,
                    "note": "Patch approved only. It was not applied.",
                }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": "patch_approve_failed",
            "detail": str(e),
        }


@app.post("/patches/{patch_id}/reject")
def reject_patch(patch_id: int):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM `dispatch_patch_proposals`
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (patch_id,),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Patch #{patch_id} not found",
                    )

                cur.execute(
                    """
                    UPDATE `dispatch_patch_proposals`
                    SET approved = 0,
                        applied = 0
                    WHERE id = %s
                    """,
                    (patch_id,),
                )

                return {
                    "status": "rejected",
                    "patch_id": patch_id,
                    "note": "Patch rejected. It was not applied.",
                }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": "patch_reject_failed",
            "detail": str(e),
        }




# -----------------------------
# Patch Apply Gate endpoints
# -----------------------------

SAFE_PATCH_ALLOWLIST = {
    "friday_chat_app.py",
    "friday_local_gateway.py",
    "friday_brain.py",
    "friday_genome_status_export.py",
    "mnt/agents/output/app/scripts/agent-dispatch-v3.mjs",
}

PATCH_BACKUP_DIR = MT5_ROOT / "patch_backups"


def normalize_patch_path(value: str) -> str:
    value = str(value or "").strip().replace("\\", "/")

    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]

    try:
        p = Path(value)

        if p.is_absolute():
            value = p.relative_to(MT5_ROOT).as_posix()
    except Exception:
        pass

    return value.strip("/")


def extract_unified_diff(raw_patch: str) -> str:
    text = str(raw_patch or "").strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


def is_unified_diff(diff_text: str) -> bool:
    text = str(diff_text or "")

    return (
        "diff --git" in text
        or ("--- " in text and "+++ " in text and "@@" in text)
    )


def touched_paths_from_diff(diff_text: str) -> set[str]:
    paths = set()

    for line in str(diff_text or "").splitlines():
        line = line.rstrip()

        if line.startswith("diff --git "):
            parts = line.split()

            for part in parts[2:4]:
                paths.add(normalize_patch_path(part))

        elif line.startswith("--- ") or line.startswith("+++ "):
            part = line[4:].strip().split("\t")[0].strip()

            if part != "/dev/null":
                paths.add(normalize_patch_path(part))

    return {p for p in paths if p}


def validate_patch_scope(target_file: str, diff_text: str) -> dict[str, Any]:
    target = normalize_patch_path(target_file)
    touched = touched_paths_from_diff(diff_text)

    issues = []

    if not target:
        issues.append("missing_target_file")

    if target not in SAFE_PATCH_ALLOWLIST:
        issues.append(f"target_not_allowed:{target}")

    if not diff_text.strip():
        issues.append("empty_patch")

    if not is_unified_diff(diff_text):
        issues.append("not_unified_diff")

    if not touched:
        issues.append("diff_paths_not_found")

    for path_item in touched:
        if path_item not in SAFE_PATCH_ALLOWLIST:
            issues.append(f"diff_path_not_allowed:{path_item}")

    if target and touched and target not in touched:
        issues.append("target_file_not_in_diff")

    return {
        "ok": len(issues) == 0,
        "target": target,
        "touched": sorted(touched),
        "issues": issues,
    }


def ensure_apply_audit_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS patch_apply_audit (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patch_id INT NOT NULL,
            target_file TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            status VARCHAR(30) NOT NULL,
            test_command TEXT NULL,
            output LONGTEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def run_syntax_test(rel_path: str) -> tuple[bool, str, str]:
    path_obj = MT5_ROOT / rel_path
    suffix = path_obj.suffix.lower()

    if suffix == ".py":
        cmd = [
            str(MT5_ROOT / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "py_compile",
            str(path_obj),
        ]

        if not Path(cmd[0]).exists():
            cmd = ["python", "-m", "py_compile", str(path_obj)]

    elif suffix in {".js", ".mjs"}:
        cmd = ["node", "--check", str(path_obj)]

    elif suffix == ".json":
        cmd = ["python", "-m", "json.tool", str(path_obj)]

    else:
        return True, "no_syntax_test_available", "No syntax test configured for this file type."

    proc = subprocess.run(
        cmd,
        cwd=str(MT5_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = (proc.stdout or "") + (proc.stderr or "")

    return proc.returncode == 0, " ".join(cmd), output.strip()


def apply_diff_with_git(diff_text: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".patch", delete=False) as tmp:
        tmp.write(str(diff_text).rstrip() + "\n")
        tmp_path = tmp.name

    try:
        check = subprocess.run(
            ["git", "apply", "--check", tmp_path],
            cwd=str(MT5_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if check.returncode != 0:
            return False, ((check.stdout or "") + (check.stderr or "")).strip()

        apply_proc = subprocess.run(
            ["git", "apply", tmp_path],
            cwd=str(MT5_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = ((apply_proc.stdout or "") + (apply_proc.stderr or "")).strip()

        return apply_proc.returncode == 0, output

    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/patches/{patch_id}/apply")
def apply_patch(patch_id: int):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                ensure_apply_audit_table(cur)

                cur.execute(
                    """
                    SELECT id, target_file, patch, approved, applied
                    FROM dispatch_patch_proposals
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (patch_id,),
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Patch #{patch_id} not found",
                    )

                if int(row.get("approved") or 0) != 1:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Patch #{patch_id} is not approved",
                    )

                if int(row.get("applied") or 0) == 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Patch #{patch_id} is already applied",
                    )

                diff_text = extract_unified_diff(row.get("patch") or "")
                validation = validate_patch_scope(row.get("target_file") or "", diff_text)

                if not validation["ok"]:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "Patch failed Apply Gate validation",
                            "issues": validation["issues"],
                            "touched": validation["touched"],
                        },
                    )

                rel_target = validation["target"]
                target_path = MT5_ROOT / rel_target

                if not target_path.exists():
                    raise HTTPException(
                        status_code=404,
                        detail=f"Target file not found: {rel_target}",
                    )

                PATCH_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = rel_target.replace("/", "__").replace("\\", "__")
                backup_path = PATCH_BACKUP_DIR / f"patch_{patch_id}_{stamp}_{safe_name}.bak"

                shutil.copy2(target_path, backup_path)

                ok, apply_output = apply_diff_with_git(diff_text)

                if not ok:
                    cur.execute(
                        """
                        INSERT INTO patch_apply_audit
                        (patch_id, target_file, backup_path, status, output)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (patch_id, rel_target, str(backup_path), "apply_failed", apply_output),
                    )

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "git apply failed",
                            "output": apply_output,
                            "backup_path": str(backup_path),
                        },
                    )

                test_ok, test_command, test_output = run_syntax_test(rel_target)

                if not test_ok:
                    shutil.copy2(backup_path, target_path)

                    cur.execute(
                        """
                        INSERT INTO patch_apply_audit
                        (patch_id, target_file, backup_path, status, test_command, output)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            patch_id,
                            rel_target,
                            str(backup_path),
                            "test_failed_rollback_done",
                            test_command,
                            test_output,
                        ),
                    )

                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "Syntax test failed. Rollback completed.",
                            "test_command": test_command,
                            "test_output": test_output,
                            "backup_path": str(backup_path),
                        },
                    )

                cur.execute(
                    """
                    UPDATE dispatch_patch_proposals
                    SET applied = 1
                    WHERE id = %s
                    """,
                    (patch_id,),
                )

                cur.execute(
                    """
                    INSERT INTO patch_apply_audit
                    (patch_id, target_file, backup_path, status, test_command, output)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        patch_id,
                        rel_target,
                        str(backup_path),
                        "applied",
                        test_command,
                        test_output,
                    ),
                )

                return {
                    "status": "applied",
                    "patch_id": patch_id,
                    "target_file": rel_target,
                    "backup_path": str(backup_path),
                    "test_command": test_command,
                    "test_output": test_output,
                    "note": "Patch applied after backup and syntax test.",
                }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": "patch_apply_failed",
            "detail": str(e),
        }


@app.post("/patches/{patch_id}/rollback")
def rollback_patch(patch_id: int):
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                ensure_apply_audit_table(cur)

                cur.execute(
                    """
                    SELECT id, target_file, backup_path
                    FROM patch_apply_audit
                    WHERE patch_id = %s
                      AND status = 'applied'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (patch_id,),
                )

                audit = cur.fetchone()

                if not audit:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No applied backup found for Patch #{patch_id}",
                    )

                rel_target = normalize_patch_path(audit.get("target_file") or "")
                backup_path = Path(audit.get("backup_path") or "")
                target_path = MT5_ROOT / rel_target

                if rel_target not in SAFE_PATCH_ALLOWLIST:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Rollback target is not allowed: {rel_target}",
                    )

                if not backup_path.exists():
                    raise HTTPException(
                        status_code=404,
                        detail=f"Backup not found: {backup_path}",
                    )

                shutil.copy2(backup_path, target_path)

                test_ok, test_command, test_output = run_syntax_test(rel_target)

                if not test_ok:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "Rollback restored backup, but syntax test failed.",
                            "test_command": test_command,
                            "test_output": test_output,
                        },
                    )

                cur.execute(
                    """
                    UPDATE dispatch_patch_proposals
                    SET applied = 0
                    WHERE id = %s
                    """,
                    (patch_id,),
                )

                cur.execute(
                    """
                    INSERT INTO patch_apply_audit
                    (patch_id, target_file, backup_path, status, test_command, output)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        patch_id,
                        rel_target,
                        str(backup_path),
                        "rollback_done",
                        test_command,
                        test_output,
                    ),
                )

                return {
                    "status": "rollback_done",
                    "patch_id": patch_id,
                    "target_file": rel_target,
                    "backup_path": str(backup_path),
                    "test_command": test_command,
                    "test_output": test_output,
                }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "error": "patch_rollback_failed",
            "detail": str(e),
        }



@app.get("/openjarvis/context")
def openjarvis_context():
    return {
        "arabic_instruction": "تحدث مع المستخدم بالعربية. لا تعدل ملفات ولا تشغل أوامر خطرة بدون موافقة.",
        "project": "FRIDAY MT5",
        "mt5_root": str(MT5_ROOT),
        "dispatch_app": str(AGENTS_APP),
        "ollama_model": "qwen2.5:3b-instruct",
        "safe_rules": [
            "No live trading",
            "No deleting files",
            "No file edits without approval",
            "No long-running scripts without approval",
            "Patch proposals before apply",
        ],
    }


@app.post("/dispatch/run")
def run_dispatch(req: DispatchRequest):
    if not AGENTS_APP.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Agents app not found: {AGENTS_APP}",
        )

    dangerous_phrases = [
        "execute real trade",
        "live trading on real account",
        "remove-item",
        "format disk",
        "rm -rf",
        "delete all",
        "حساب حقيقي",
        "تداول حقيقي",
        "احذف الملفات",
        "احذف المشروع",
    ]

    lower_task = req.task.lower()

    if any(phrase in lower_task for phrase in dangerous_phrases):
        raise HTTPException(
            status_code=403,
            detail="Blocked by FRIDAY safety gate. This task may be dangerous.",
        )

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"dispatch_{stamp}.log"

    env = os.environ.copy()
    env["DISPATCH_MAX_AGENTS"] = str(req.max_agents)
    env["DISPATCH_FILES_PER_AGENT"] = str(req.files_per_agent)
    env["DISPATCH_CHARS_PER_FILE"] = str(req.chars_per_file)
    env["DISPATCH_CTX"] = str(req.ctx)
    env["PYTHONUTF8"] = "1"

    if req.agent_roles:
        clean_roles = [
            str(role).strip()
            for role in req.agent_roles
            if str(role).strip()
        ]

        if clean_roles:
            env["DISPATCH_AGENT_ROLES"] = ",".join(clean_roles)

    if req.dispatch_model:
        env["OLLAMA_MODEL"] = str(req.dispatch_model).strip()

    if req.target_files:
        clean_files = [
            str(file).strip()
            for file in req.target_files
            if str(file).strip()
        ]

        if clean_files:
            env["DISPATCH_TARGET_FILES"] = ",".join(clean_files)

    cmd = [
        "cmd.exe",
        "/c",
        "npm",
        "run",
        "dispatch:v3",
        "--",
        req.task,
    ]

    log_file = open(log_path, "w", encoding="utf-8", errors="replace")

    process = subprocess.Popen(
        cmd,
        cwd=str(AGENTS_APP),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )

    return {
        "status": "started",
        "pid": process.pid,
        "task": req.task,
        "agent_roles": req.agent_roles,
        "dispatch_model": req.dispatch_model,
        "target_files": req.target_files,
        "log_path": str(log_path),
        "note": "Dispatch started in background. Check /dispatch/jobs after it finishes.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "friday_local_gateway:app",
        host="127.0.0.1",
        port=8799,
        reload=False,
    )

