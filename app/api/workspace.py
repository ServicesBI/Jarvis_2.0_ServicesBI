"""Arquivos e contratos somente locais de memoria/Obsidian usados pelo cockpit."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.voice import _multipart_file
from app.core.config import PROJECT_ROOT, get_setting


router = APIRouter(prefix="/api", tags=["workspace"])
PROJECTS_DIR = PROJECT_ROOT / "Documents and Projects"
DELIVERABLES = {".pdf", ".md", ".txt", ".html", ".css", ".js", ".ts", ".py", ".json", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".xlsx", ".pptx", ".docx", ".zip", ".mp3", ".mp4", ".wav"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".js", ".ts", ".py", ".html", ".css", ".xml", ".sql", ".sh", ".bat", ".log", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _vault() -> Path:
    configured = get_setting("OBSIDIAN_VAULT")
    return Path(configured) if configured else PROJECT_ROOT / "obsidian-template"


@router.get("/files")
async def list_files() -> dict[str, list[dict[str, object]]]:
    roots = [PROJECTS_DIR] if PROJECTS_DIR.exists() else []
    files: list[dict[str, object]] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in DELIVERABLES:
                continue
            stat = path.stat()
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            project_parts = path.relative_to(root).parts
            files.append({
                "name": path.name,
                "path": rel,
                "project": project_parts[0] if len(project_parts) > 1 else "General",
                "ext": path.suffix.lower(),
                "size": stat.st_size,
                "createdAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "downloadUrl": f"/api/files/download?path={quote(rel)}",
            })
    files.sort(key=lambda item: str(item["createdAt"]), reverse=True)
    return {"files": files}


def _requested_file(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = (PROJECT_ROOT / raw_path).resolve()
    return candidate if _inside(PROJECT_ROOT, candidate) and candidate.is_file() else None


@router.get("/files/download")
async def download_file(path: str | None = None):
    candidate = _requested_file(path)
    if candidate is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(candidate, filename=candidate.name)


@router.get("/files/view")
async def view_file(path: str | None = None):
    candidate = _requested_file(path)
    if candidate is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(candidate)


@router.post("/attach")
async def attach(request: Request) -> JSONResponse:
    parsed = _multipart_file(request.headers.get("content-type", ""), await request.body(), "file")
    if parsed is None:
        return JSONResponse({"error": "No file uploaded"}, status_code=400)
    filename, mime, content = parsed
    attachment_id = f"att-{int(datetime.now().timestamp() * 1000)}"
    record: dict[str, object] = {"name": Path(filename).name, "mime": mime, "size": len(content)}
    if Path(filename).suffix.lower() in TEXT_EXTENSIONS:
        record["text"] = content.decode("utf-8", errors="replace")
    else:
        record["content"] = content
    request.app.state.attachments[attachment_id] = record
    return JSONResponse({"attachmentId": attachment_id, "name": record["name"], "size": len(content)})


def _obsidian_stats() -> dict[str, object]:
    vault = _vault()
    if not vault.exists():
        return {"connected": False, "name": vault.name, "notes": 0, "folders": 0, "links": 0, "brain": 0, "agents": 0}
    notes = list(vault.rglob("*.md"))
    folders = sum(1 for item in vault.rglob("*") if item.is_dir() and not item.name.startswith("."))
    links = 0
    for note in notes:
        try:
            links += len(re.findall(r"\[\[[^\]]+\]\]", note.read_text(encoding="utf-8")))
        except (OSError, UnicodeError):
            pass
    return {"connected": True, "name": vault.name, "notes": len(notes), "folders": folders, "links": links, "brain": len(notes), "agents": 0}


@router.get("/obsidian/stats")
async def obsidian_stats() -> dict[str, object]:
    return _obsidian_stats()


def _tree(directory: Path, vault: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    try:
        items = sorted((item for item in directory.iterdir() if not item.name.startswith(".")), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return result
    for item in items:
        if item.is_dir():
            result.append({"type": "folder", "name": item.name, "children": _tree(item, vault)})
        elif item.suffix.lower() == ".md":
            result.append({"type": "note", "name": item.stem, "path": item.relative_to(vault).as_posix()})
    return result


@router.get("/obsidian/tree")
async def obsidian_tree() -> dict[str, object]:
    vault = _vault()
    return {"tree": _tree(vault, vault) if vault.exists() else []}


_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def _normalize_link_target(raw: str) -> str:
    """Remove alias (|...) e heading (#...) de um wikilink, preservando o target."""

    return raw.split("|", 1)[0].split("#", 1)[0].strip()


def _strip_md_extension(value: str) -> str:
    return value[:-3] if value.lower().endswith(".md") else value


def _category_for(relative_path: str) -> str:
    parts = relative_path.split("/")
    return parts[0] if len(parts) > 1 else "root"


def _build_link_indexes(
    notes: list[Path], vault: Path
) -> tuple[dict[str, str], dict[str, str]]:
    """path_index cobre caminho explicito (com/sem .md); stem_index cobre nome puro.

    Em caso de stems duplicados entre pastas, a nota de caminho relativo
    alfabeticamente menor vence (ordem determinística, sem fuzzy matching).
    """

    path_index: dict[str, str] = {}
    stem_index: dict[str, str] = {}
    for note in sorted(notes, key=lambda p: p.relative_to(vault).as_posix().lower()):
        rel = note.relative_to(vault).as_posix()
        path_index.setdefault(_strip_md_extension(rel).lower(), rel)
        path_index.setdefault(rel.lower(), rel)
        stem_index.setdefault(note.stem.lower(), rel)
    return path_index, stem_index


def _resolve_link(
    target: str, path_index: dict[str, str], stem_index: dict[str, str]
) -> str | None:
    normalized = _strip_md_extension(target.strip().replace("\\", "/")).strip("/")
    if not normalized:
        return None
    if "/" in normalized:
        return path_index.get(normalized.lower())
    return stem_index.get(normalized.lower()) or path_index.get(normalized.lower())


def _build_graph(vault: Path) -> dict[str, Any]:
    """Deriva nodes/edges diretamente do vault: sem catalogo paralelo, sem
    consultar AgentRegistry. Leitura estritamente confinada a vault.rglob,
    sem nenhum path vindo do cliente."""

    if not vault.exists():
        return {"nodes": [], "edges": [], "count": 0, "edge_count": 0}

    notes = [path for path in vault.rglob("*.md") if path.is_file()]
    path_index, stem_index = _build_link_indexes(notes, vault)

    nodes: dict[str, dict[str, Any]] = {}
    for note in notes:
        rel = note.relative_to(vault).as_posix()
        nodes[rel] = {
            "id": rel,
            "title": note.stem,
            "relative_path": rel,
            "category": _category_for(rel),
            "exists": True,
        }

    edges: set[tuple[str, str]] = set()
    for note in notes:
        rel = note.relative_to(vault).as_posix()
        try:
            content = note.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for raw_match in _WIKILINK_PATTERN.findall(content):
            target = _normalize_link_target(raw_match)
            if not target:
                continue
            resolved = _resolve_link(target, path_index, stem_index)
            if resolved is None:
                unresolved_id = f"__unresolved__/{target.lower()}"
                if unresolved_id not in nodes:
                    nodes[unresolved_id] = {
                        "id": unresolved_id,
                        "title": target,
                        "relative_path": None,
                        "category": "unresolved",
                        "exists": False,
                    }
                resolved = unresolved_id
            if resolved == rel:
                continue
            edges.add((rel, resolved))

    node_list = sorted(nodes.values(), key=lambda item: str(item["id"]).lower())
    edge_list = [
        {"source": source, "target": target}
        for source, target in sorted(edges)
    ]
    return {
        "nodes": node_list,
        "edges": edge_list,
        "count": len(node_list),
        "edge_count": len(edge_list),
    }


@router.get("/obsidian/graph")
async def obsidian_graph() -> dict[str, object]:
    return _build_graph(_vault())


@router.get("/obsidian/note")
async def obsidian_note(path: str | None = None) -> JSONResponse:
    vault = _vault().resolve()
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    candidate = (vault / path).resolve()
    if not _inside(vault, candidate):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not candidate.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"path": path, "content": candidate.read_text(encoding="utf-8")})


@router.post("/obsidian/ingest")
async def obsidian_ingest(request: Request) -> JSONResponse:
    vault = _vault()
    if not vault.exists():
        return JSONResponse({"error": "Obsidian vault is not configured"}, status_code=503)
    payload = await request.json()
    kind = payload.get("type")
    if kind == "text":
        content = str(payload.get("text", "")).strip()
        if not content:
            return JSONResponse({"error": "text required"}, status_code=400)
        title = re.sub(r"[^\w\- ]", "", content.splitlines()[0], flags=re.UNICODE).strip()[:60] or "Novo Conhecimento"
    elif kind == "file":
        content = str(payload.get("fileContent", ""))
        title = Path(str(payload.get("fileName", "Nota"))).stem
    elif kind == "session":
        return JSONResponse({"error": "Session history unavailable in FastAPI"}, status_code=503)
    else:
        return JSONResponse({"error": "type required: text, file, session"}, status_code=400)
    folder = re.sub(r"[^\w\- ]", "", str(payload.get("category", "geral")), flags=re.UNICODE).strip() or "geral"
    target_dir = vault / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{title}.md"
    if not _inside(vault, target):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target_dir, prefix=".jarvis-tmp-", suffix=".md", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return JSONResponse({"ok": True, "path": target.relative_to(vault).as_posix(), "title": title})


@router.get("/memory/status")
async def memory_status() -> dict[str, object]:
    stats = _obsidian_stats()
    history = PROJECT_ROOT / "system" / "JARVIS-HISTORY.json"
    embeddings = PROJECT_ROOT / "system" / "memory-embeddings.json"
    mega_index = PROJECT_ROOT / "system" / "mega-brain" / "index.json"
    local_available = history.exists() or embeddings.exists()
    mega_available = mega_index.exists()
    active = int(local_available) + int(bool(stats["connected"])) + int(mega_available)
    return {
        "status": "partial" if active else "unavailable",
        "activeLayers": active,
        "totalLayers": 3,
        "local": {"status": "available" if local_available else "unavailable", "historyEntries": 0, "embeddings": 0, "memorySize": history.stat().st_size if history.exists() else 0, "projectContexts": 0},
        "obsidian": {"status": "available" if stats["connected"] else "unavailable", "notes": stats["notes"], "folders": stats["folders"], "links": stats["links"]},
        "megaBrain": {"status": "available" if mega_available else "unavailable", "moduleLoaded": False, "indexAvailable": mega_available, "indexedItems": 0, "projects": 0},
    }
