#!/usr/bin/env python3
"""Prepare Markdown documents for knowledge ingestion.

职责：从 URL 或本地目录收集 Markdown，保留原文，输出轻量清洗后的副本和清单。
边界：本脚本不调用后端 API、不生成 chunk、不写数据库；后续入库仍由知识库上传链路完成。
副作用：在输出目录下创建按 source 和日期版本分组的 raw/prepared/manifest 文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

DEFAULT_OUTPUT_ROOT = Path("data/knowledge")
MARKDOWN_SUFFIXES = {".md", ".markdown"}
FASTAPI_INCLUDE_RE = re.compile(r"^\s*\{\*\s+[^{}]+?\s+\*\}\s*$")
HTML_IMAGE_RE = re.compile(r"^\s*<img\b[^>]*>\s*$", re.IGNORECASE)
EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class PreparedDocument:
    url: str | None
    language: str
    raw_path: Path
    prepared_path: Path
    raw_sha256: str
    prepared_sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare Markdown files under data/knowledge/{source}/{date_NNN}."
    )
    parser.add_argument("--source", required=True, help="Source folder name.")
    parser.add_argument("--language", required=True, help="Language folder, e.g. zh.")
    parser.add_argument("--url", help="Single Markdown URL to download.")
    parser.add_argument("--input-dir", type=Path, help="Local Markdown directory.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    if bool(args.url) == bool(args.input_dir):
        parser.error("provide exactly one of --url or --input-dir")
    if args.input_dir and not args.input_dir.is_dir():
        parser.error(
            f"--input-dir does not exist or is not a directory: {args.input_dir}"
        )
    return args


def next_version_dir(output_root: Path, source: str, run_date: str) -> Path:
    source_root = output_root / source
    source_root.mkdir(parents=True, exist_ok=True)
    prefix = f"{run_date}_"
    indexes = []
    for child in source_root.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            suffix = child.name.removeprefix(prefix)
            if suffix.isdigit():
                indexes.append(int(suffix))
    return source_root / f"{run_date}_{max(indexes, default=0) + 1:03d}"


def prepare_markdown(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        line for line in normalized.split("\n") if not should_drop_markdown_line(line)
    ]
    compacted = EXCESS_BLANK_LINES_RE.sub("\n\n", "\n".join(lines))
    return compacted.strip() + "\n"


def should_drop_markdown_line(line: str) -> bool:
    return bool(HTML_IMAGE_RE.match(line) or FASTAPI_INCLUDE_RE.match(line))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def convert_github_blob_url(url: str) -> str:
    parsed = urlparse(url)
    parts = PurePosixPath(parsed.path).parts
    if parsed.netloc != "github.com" or len(parts) < 6 or parts[3] != "blob":
        return url
    owner, repo, ref = parts[1], parts[2], parts[4]
    file_path = "/".join(parts[5:])
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{file_path}"


def relative_path_for_url(url: str, language: str) -> Path:
    parsed = urlparse(convert_github_blob_url(url))
    parts = list(PurePosixPath(parsed.path).parts)
    if parsed.netloc == "raw.githubusercontent.com" and len(parts) >= 5:
        source_parts = parts[4:]
    else:
        source_parts = [Path(parsed.path).name or "document.md"]

    if len(source_parts) >= 2 and source_parts[0] == "docs":
        source_parts = source_parts[1:]
    if not source_parts or source_parts[0] != language:
        source_parts = [language, *source_parts]
    return Path(*source_parts)


def download_text(url: str) -> str:
    request = urllib.request.Request(
        convert_github_blob_url(url),
        headers={"User-Agent": "dewflow-knowledge-preparer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def write_document(
    *,
    version_dir: Path,
    language: str,
    relative_path: Path,
    raw_text: str,
    url: str | None,
) -> PreparedDocument:
    raw_path = version_dir / "raw" / relative_path
    prepared_path = version_dir / "prepared" / relative_path
    prepared_text = prepare_markdown(raw_text)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw_text, encoding="utf-8")
    prepared_path.write_text(prepared_text, encoding="utf-8")
    return PreparedDocument(
        url=url,
        language=language,
        raw_path=raw_path,
        prepared_path=prepared_path,
        raw_sha256=sha256_text(raw_text),
        prepared_sha256=sha256_text(prepared_text),
    )


def iter_local_markdown(input_dir: Path, language: str) -> list[tuple[Path, str]]:
    files = sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES
    )
    return [
        (Path(language) / path.relative_to(input_dir), path.read_text("utf-8"))
        for path in files
    ]


def write_manifest(version_dir: Path, documents: list[PreparedDocument]) -> None:
    manifest_path = version_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for document in documents:
            payload = {
                "url": document.url,
                "language": document.language,
                "raw_path": str(document.raw_path.relative_to(version_dir)),
                "prepared_path": str(document.prepared_path.relative_to(version_dir)),
                "raw_sha256": document.raw_sha256,
                "prepared_sha256": document.prepared_sha256,
            }
            manifest_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    version_dir = next_version_dir(args.out, args.source, args.date)
    documents: list[PreparedDocument] = []

    if args.url:
        raw_text = download_text(args.url)
        documents.append(
            write_document(
                version_dir=version_dir,
                language=args.language,
                relative_path=relative_path_for_url(args.url, args.language),
                raw_text=raw_text,
                url=args.url,
            )
        )
    else:
        for relative_path, raw_text in iter_local_markdown(
            args.input_dir, args.language
        ):
            documents.append(
                write_document(
                    version_dir=version_dir,
                    language=args.language,
                    relative_path=relative_path,
                    raw_text=raw_text,
                    url=None,
                )
            )

    write_manifest(version_dir, documents)
    print(f"Prepared {len(documents)} Markdown file(s): {version_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
