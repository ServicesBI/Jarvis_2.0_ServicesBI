#!/usr/bin/env python3
"""
JARVIS File Intelligence System
Indexes, searches, and organizes files on the PC.

Usage:
    python file-index.py index C:\\Users\\Gamer
    python file-index.py search "PDF de impostos"
    python file-index.py recent 7
    python file-index.py large 100
    python file-index.py organize C:\\Users\\Gamer\\Downloads
"""

import os
import sys
import json
import time
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from math import log

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ---------- Config ----------
INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_file_index.json")

SKIP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery",
    "node_modules", ".git", ".svn", "__pycache__", ".tox", ".venv",
    "venv", "env", ".env", ".cache", ".tmp", "appdata",
    "perflogs", "msocache", "config.msi",
}

SKIP_PREFIXES = ("$", ".")

# Extension-to-category mapping for organize
ORGANIZE_MAP = {
    # Documents
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".txt": "Documents", ".rtf": "Documents", ".odt": "Documents",
    ".md": "Documents", ".tex": "Documents",
    # Spreadsheets
    ".xlsx": "Spreadsheets", ".xls": "Spreadsheets", ".csv": "Spreadsheets",
    ".tsv": "Spreadsheets", ".ods": "Spreadsheets",
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".svg": "Images", ".webp": "Images", ".ico": "Images",
    ".tiff": "Images", ".tif": "Images", ".heic": "Images", ".raw": "Images",
    # Videos
    ".mp4": "Videos", ".avi": "Videos", ".mkv": "Videos", ".mov": "Videos",
    ".wmv": "Videos", ".flv": "Videos", ".webm": "Videos", ".m4v": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio", ".aac": "Audio",
    ".ogg": "Audio", ".wma": "Audio", ".m4a": "Audio",
    # Archives
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
    ".tar": "Archives", ".gz": "Archives", ".bz2": "Archives",
    # Installers
    ".exe": "Installers", ".msi": "Installers", ".dmg": "Installers",
    ".deb": "Installers", ".rpm": "Installers", ".appimage": "Installers",
    # Presentations
    ".pptx": "Presentations", ".ppt": "Presentations", ".odp": "Presentations",
    # Code
    ".py": "Code", ".js": "Code", ".ts": "Code", ".jsx": "Code",
    ".tsx": "Code", ".java": "Code", ".c": "Code", ".cpp": "Code",
    ".h": "Code", ".cs": "Code", ".go": "Code", ".rs": "Code",
    ".rb": "Code", ".php": "Code", ".html": "Code", ".css": "Code",
    ".sql": "Code", ".sh": "Code", ".bat": "Code", ".ps1": "Code",
}


def emit(data: dict):
    """Write JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def should_skip(dirname: str) -> bool:
    """Check if directory should be skipped."""
    lower = dirname.lower()
    if lower in SKIP_DIRS:
        return True
    if any(lower.startswith(p) for p in SKIP_PREFIXES):
        return True
    return False


def crawl(root: str) -> list[dict]:
    """Crawl filesystem and collect file metadata."""
    files = []
    root = os.path.abspath(root)
    count = 0
    errors = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Filter out skip dirs in-place (modifying dirnames prunes os.walk)
        dirnames[:] = [d for d in dirnames if not should_skip(d)]

        for fname in filenames:
            try:
                fpath = os.path.join(dirpath, fname)
                stat = os.stat(fpath)
                ext = os.path.splitext(fname)[1].lower()
                files.append({
                    "path": fpath,
                    "name": fname,
                    "ext": ext,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "modified_ts": stat.st_mtime,
                    "parent": dirpath,
                })
                count += 1
                if count % 10000 == 0:
                    print(f"  ... indexed {count} files", file=sys.stderr)
            except (PermissionError, OSError):
                errors += 1
                continue

    return files


def save_index(files: list[dict]):
    """Save index to JSON file."""
    data = {
        "indexed_at": datetime.now().isoformat(),
        "total_files": len(files),
        "files": files,
    }
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def load_index() -> list[dict]:
    """Load index from JSON file."""
    if not os.path.exists(INDEX_PATH):
        emit({"error": "No index found. Run: python file-index.py index <path>"})
        sys.exit(1)

    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("files", [])


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens for matching."""
    return re.findall(r"[a-zA-Z0-9\u00C0-\u024F]+", text.lower())


def search_files(query: str, max_results: int = 20) -> list[dict]:
    """Search indexed files using TF-IDF-like scoring."""
    files = load_index()
    query_tokens = tokenize(query)

    if not query_tokens:
        return []

    # Build a simple document-frequency map across filenames
    doc_count = len(files)
    df = defaultdict(int)
    for f in files:
        name_tokens = set(tokenize(f["name"]))
        folder_tokens = set(tokenize(os.path.basename(f["parent"])))
        all_tokens = name_tokens | folder_tokens
        for t in all_tokens:
            df[t] += 1

    scored = []
    now = time.time()

    for f in files:
        score = 0.0
        name_lower = f["name"].lower()
        name_tokens = tokenize(f["name"])
        folder_tokens = tokenize(os.path.basename(f["parent"]))
        ext_clean = f["ext"].lstrip(".").lower()

        for qt in query_tokens:
            # Exact filename match (highest weight)
            if qt in name_lower:
                idf = log((doc_count + 1) / (df.get(qt, 0) + 1))
                if qt == name_lower.replace(f["ext"], ""):
                    score += 10.0 * idf  # Exact full name match
                else:
                    score += 5.0 * idf  # Partial name match

            # Token match in name
            for nt in name_tokens:
                if qt == nt:
                    idf = log((doc_count + 1) / (df.get(qt, 0) + 1))
                    score += 3.0 * idf
                elif qt in nt or nt in qt:
                    score += 1.0

            # Extension match
            if qt == ext_clean:
                score += 4.0

            # Folder match
            for ft in folder_tokens:
                if qt == ft:
                    score += 2.0
                elif qt in ft:
                    score += 0.5

        # Recency boost: files modified in last 30 days get a bonus
        modified_ts = f.get("modified_ts", 0)
        age_days = (now - modified_ts) / 86400
        if age_days < 30:
            score *= 1.0 + (30 - age_days) / 30 * 0.5  # Up to 50% boost

        if score > 0:
            scored.append({
                "path": f["path"],
                "name": f["name"],
                "size": f["size"],
                "modified": f["modified"],
                "score": round(score, 4),
            })

    # Sort by score descending, then by modified date descending
    scored.sort(key=lambda x: (-x["score"], x["modified"]), reverse=False)
    return scored[:max_results]


def recent_files(days: int, max_results: int = 50) -> list[dict]:
    """Find files modified within the last N days."""
    files = load_index()
    cutoff = time.time() - (days * 86400)

    recent = []
    for f in files:
        if f.get("modified_ts", 0) >= cutoff:
            recent.append({
                "path": f["path"],
                "name": f["name"],
                "size": f["size"],
                "modified": f["modified"],
            })

    # Sort by modified date descending (most recent first)
    recent.sort(key=lambda x: x["modified"], reverse=True)
    return recent[:max_results]


def large_files(min_mb: float, max_results: int = 50) -> list[dict]:
    """Find files larger than min_mb megabytes."""
    files = load_index()
    threshold = min_mb * 1024 * 1024

    large = []
    for f in files:
        if f["size"] >= threshold:
            large.append({
                "path": f["path"],
                "name": f["name"],
                "size": f["size"],
                "size_mb": round(f["size"] / (1024 * 1024), 2),
                "modified": f["modified"],
            })

    # Sort by size descending
    large.sort(key=lambda x: -x["size"])
    return large[:max_results]


def organize_suggest(directory: str) -> list[dict]:
    """Suggest file organization for a directory."""
    directory = os.path.abspath(directory)

    if not os.path.isdir(directory):
        emit({"error": f"Directory not found: {directory}"})
        sys.exit(1)

    suggestions = []
    category_counts = defaultdict(int)

    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue

        ext = os.path.splitext(fname)[1].lower()
        category = ORGANIZE_MAP.get(ext)

        if category:
            dest = os.path.join(directory, category, fname)
            suggestions.append({
                "file": fname,
                "current": fpath,
                "suggested_folder": category,
                "suggested_path": dest,
                "ext": ext,
            })
            category_counts[category] += 1

    summary = {
        "directory": directory,
        "total_files_to_organize": len(suggestions),
        "categories": dict(category_counts),
    }

    return {"summary": summary, "suggestions": suggestions}


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def cmd_index(args):
    """Index command handler."""
    root = args.path
    if not os.path.isdir(root):
        emit({"error": f"Directory not found: {root}"})
        sys.exit(1)

    print(f"Indexing {root} ...", file=sys.stderr)
    start = time.time()
    files = crawl(root)
    elapsed = time.time() - start
    save_index(files)

    emit({
        "cmd": "index",
        "root": root,
        "total_files": len(files),
        "index_path": INDEX_PATH,
        "elapsed_seconds": round(elapsed, 2),
    })


def cmd_search(args):
    """Search command handler."""
    query = args.query
    results = search_files(query, max_results=args.limit)
    emit({
        "cmd": "search",
        "query": query,
        "results": results,
        "total_results": len(results),
    })


def cmd_recent(args):
    """Recent files command handler."""
    days = args.days
    results = recent_files(days, max_results=args.limit)
    emit({
        "cmd": "recent",
        "days": days,
        "results": results,
        "total_results": len(results),
    })


def cmd_large(args):
    """Large files command handler."""
    min_mb = args.min_mb
    results = large_files(min_mb, max_results=args.limit)
    emit({
        "cmd": "large",
        "min_mb": min_mb,
        "results": results,
        "total_results": len(results),
    })


def cmd_organize(args):
    """Organize command handler."""
    directory = args.path
    result = organize_suggest(directory)
    emit({
        "cmd": "organize",
        **result,
    })


def main():
    parser = argparse.ArgumentParser(
        description="JARVIS File Intelligence System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index
    p_index = subparsers.add_parser("index", help="Crawl and index files")
    p_index.add_argument("path", help="Root directory to index")
    p_index.set_defaults(func=cmd_index)

    # search
    p_search = subparsers.add_parser("search", help="Search indexed files")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p_search.set_defaults(func=cmd_search)

    # recent
    p_recent = subparsers.add_parser("recent", help="Files modified in last N days")
    p_recent.add_argument("days", type=int, help="Number of days")
    p_recent.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    p_recent.set_defaults(func=cmd_recent)

    # large
    p_large = subparsers.add_parser("large", help="Files larger than N MB")
    p_large.add_argument("min_mb", type=float, help="Minimum size in MB")
    p_large.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    p_large.set_defaults(func=cmd_large)

    # organize
    p_organize = subparsers.add_parser("organize", help="Suggest file organization")
    p_organize.add_argument("path", help="Directory to organize")
    p_organize.set_defaults(func=cmd_organize)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
