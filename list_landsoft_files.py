#!/usr/bin/env python3
"""
JASS Landsoft File Inventory
Lists every file under E:\\Landsoft, including subfolders.

Outputs:
  - landsoft_file_inventory.csv  : spreadsheet-friendly inventory
  - landsoft_file_inventory.json : structured inventory
  - landsoft_file_inventory.txt  : easy-to-read report

Run:
    py list_landsoft_files.py

Optional:
    py list_landsoft_files.py E:\\Landsoft
"""

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


DEFAULT_ROOT = Path(r"E:\Landsoft")

CATEGORIES = {
    "Images": {
        ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".bmp", ".tif", ".tiff",
        ".webp", ".ico", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
        ".dng", ".svg"
    },
    "PDF": {".pdf"},
    "Excel": {".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".csv"},
    "Word": {".doc", ".docx", ".docm", ".rtf", ".odt"},
    "Text": {".txt", ".log", ".md", ".xml", ".json", ".yaml", ".yml", ".ini"},
    "PowerPoint": {".ppt", ".pptx", ".pptm", ".pps", ".ppsx"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"},
    "Video": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
        ".3gp", ".mpeg", ".mpg"
    },
    "Audio": {
        ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma", ".opus"
    },
}


def category_for(suffix):
    suffix = suffix.lower()
    for category, extensions in CATEGORIES.items():
        if suffix in extensions:
            return category
    return "Other"


def human_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def timestamp(value):
    try:
        return datetime.fromtimestamp(value).isoformat(sep=" ", timespec="seconds")
    except (OSError, OverflowError, ValueError):
        return ""


def collect_files(root):
    records = []
    errors = []
    folder_count = 0

    # os.walk is used instead of Path.rglob so inaccessible directories can
    # be recorded and skipped without stopping the complete inventory.
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        folder_count += 1

        # Remove symlinked directories from traversal to avoid loops.
        real_dirs = []
        for dirname in dirs:
            path = Path(current) / dirname
            try:
                if path.is_symlink():
                    continue
            except OSError:
                continue
            real_dirs.append(dirname)
        dirs[:] = real_dirs

        for filename in files:
            path = Path(current) / filename

            try:
                stat = path.stat()
                suffix = path.suffix.lower()

                records.append({
                    "name": path.name,
                    "extension": suffix if suffix else "[no extension]",
                    "category": category_for(suffix),
                    "size_bytes": stat.st_size,
                    "size": human_size(stat.st_size),
                    "modified": timestamp(stat.st_mtime),
                    "created": timestamp(stat.st_ctime),
                    "relative_path": str(path.relative_to(root)),
                    "folder": str(path.parent.relative_to(root)),
                    "full_path": str(path),
                })
            except (OSError, PermissionError) as exc:
                errors.append({
                    "path": str(path),
                    "error": str(exc),
                })

    records.sort(key=lambda item: item["relative_path"].lower())
    return records, folder_count, errors


def write_csv(records, output):
    fields = [
        "name", "extension", "category", "size_bytes", "size",
        "modified", "created", "relative_path", "folder", "full_path"
    ]

    with output.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def write_json(records, root, folder_count, errors, output):
    data = {
        "root": str(root),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "folder_count": folder_count,
        "file_count": len(records),
        "error_count": len(errors),
        "files": records,
        "errors": errors,
    }

    with output.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_txt(records, root, folder_count, errors, output):
    category_counts = Counter(r["category"] for r in records)
    extension_counts = Counter(r["extension"] for r in records)
    total_bytes = sum(r["size_bytes"] for r in records)

    with output.open("w", encoding="utf-8") as f:
        f.write("JASS LANDSOFT FILE INVENTORY\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Root: {root}\n")
        f.write(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"Folders scanned: {folder_count:,}\n")
        f.write(f"Files found: {len(records):,}\n")
        f.write(f"Total size: {human_size(total_bytes)}\n")
        f.write(f"Files with errors: {len(errors):,}\n\n")

        f.write("CATEGORY SUMMARY\n")
        f.write("-" * 80 + "\n")
        for category, count in category_counts.most_common():
            f.write(f"{category:<18} {count:>10,}\n")

        f.write("\nEXTENSION SUMMARY\n")
        f.write("-" * 80 + "\n")
        for extension, count in extension_counts.most_common():
            f.write(f"{extension:<18} {count:>10,}\n")

        f.write("\nFILE LIST\n")
        f.write("=" * 80 + "\n")

        for i, record in enumerate(records, 1):
            f.write(
                f"{i:>7}. [{record['category']:<12}] "
                f"{record['size']:>10}  {record['relative_path']}\n"
            )

        if errors:
            f.write("\n\nSCAN ERRORS\n")
            f.write("=" * 80 + "\n")
            for error in errors:
                f.write(f"{error['path']}\n  {error['error']}\n")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOT
    root = root.expanduser()

    if not root.exists():
        print(f"ERROR: Folder does not exist: {root}")
        print("Use another folder as the command-line argument.")
        sys.exit(1)

    if not root.is_dir():
        print(f"ERROR: Not a folder: {root}")
        sys.exit(1)

    root = root.resolve()

    print(f"Scanning: {root}")
    print("Including subfolders...")
    print()

    records, folder_count, errors = collect_files(root)

    base = Path.cwd()
    csv_path = base / "landsoft_file_inventory.csv"
    json_path = base / "landsoft_file_inventory.json"
    txt_path = base / "landsoft_file_inventory.txt"

    write_csv(records, csv_path)
    write_json(records, root, folder_count, errors, json_path)
    write_txt(records, root, folder_count, errors, txt_path)

    total_bytes = sum(r["size_bytes"] for r in records)
    categories = Counter(r["category"] for r in records)

    print("SCAN COMPLETE")
    print("=" * 60)
    print(f"Root:             {root}")
    print(f"Folders scanned:  {folder_count:,}")
    print(f"Files found:      {len(records):,}")
    print(f"Total size:       {human_size(total_bytes)}")
    print(f"Scan errors:      {len(errors):,}")
    print()

    print("Categories:")
    for category, count in categories.most_common():
        print(f"  {category:<18} {count:,}")

    print()
    print("Created:")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    print(f"  {txt_path}")


if __name__ == "__main__":
    main()
