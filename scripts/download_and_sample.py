"""Download a file (local path or URL) and write a sampled subset.

Example:
  python scripts/download_and_sample.py \
    --input https://example.com/data.tsv.gz \
    --output samples/peregrine/PEREGRINEenhancershg38_sample.gz \
    --limit 100 
Supports gzipped or plain text; sampling preserves header unless --no-header.
"""
from __future__ import annotations

import argparse
import gzip
import io
import importlib
import inspect
import shutil
import sys
import json
import tarfile
import tempfile
import mimetypes
import zipfile
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Avoid importing adapters with heavy dependencies at module import time
TfbsAdapter = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download (or copy) and sample first N data rows")
    p.add_argument("--input", required=True, help="URL or local path to source file (tsv/csv, plain or .gz)")
    p.add_argument("--output", required=True, help="Destination path; .gz writes gzipped")
    p.add_argument("--limit", type=int, default=100, help="Number of data rows to keep (excluding header unless --no-header)")
    p.add_argument("--no-header", action="store_true", help="Treat input as headerless; sample first N lines")
    p.add_argument("--delimiter", default="\t", help="Field delimiter (unused for sampling but retained for clarity)")
    return p.parse_args()


def is_gzip_file(path: Path) -> bool:
    if path.suffix == ".gz":
        return True
    try:
        with path.open("rb") as f:
            magic = f.read(2)
            return magic == b"\x1f\x8b"
    except FileNotFoundError:
        return False


def open_maybe_gzip(path: Path, mode: str):
    if "b" in mode:
        return gzip.open(path, mode) if is_gzip_file(path) else open(path, mode)
    return gzip.open(path, mode) if is_gzip_file(path) else open(path, mode, encoding="utf-8")


def download_to_tmp(src: str, tmp_path: Path) -> Path:
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"}:
        suffix = Path(parsed.path).suffix
        target = tmp_path.with_suffix(suffix or "")
        with urllib.request.urlopen(src) as resp, target.open("wb") as out:
            shutil.copyfileobj(resp, out)
        return target
    src_path = Path(src)
    if not src_path.exists():
        raise FileNotFoundError(src)
    return src_path


def stream_sample_http(src: str, out_path: Path, limit: int, no_header: bool) -> int:
    parsed = urlparse(src)
    assert parsed.scheme in {"http", "https"}

    is_gz = parsed.path.endswith(".gz")
    is_zip = parsed.path.endswith(".zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data_rows = 0
    
    if is_zip:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_zip = Path(tmpdir) / Path(parsed.path).name
            with urllib.request.urlopen(src) as resp, tmp_zip.open("wb") as outb:
                shutil.copyfileobj(resp, outb)

            with zipfile.ZipFile(tmp_zip, "r") as zf:
                candidate = None
                for name in zf.namelist():
                    # skip directories
                    if name.endswith("/"):
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix in {".txt", ".tsv", ".csv", ".gtf", ".gff", ".gff3", ".bed"} or True:
                        candidate = name
                        break

                if not candidate:
                    print("[ERROR] No suitable file found inside ZIP archive.")
                    return 0

                with zf.open(candidate) as member:
                    # If the member is gzipped inside the zip, handle that
                    if Path(candidate).suffix.lower() == ".gz":
                        with gzip.GzipFile(fileobj=io.BytesIO(member.read())) as gf:
                            reader = io.TextIOWrapper(gf, encoding="utf-8", errors="replace")
                            with open_maybe_gzip(out_path, "wt") as out:
                                if not no_header:
                                    try:
                                        header = next(reader)
                                    except StopIteration:
                                        return 0
                                    out.write(header)
                                for line in reader:
                                    if data_rows >= limit:
                                        break
                                    out.write(line)
                                    data_rows += 1
                    else:
                        reader = io.TextIOWrapper(member, encoding="utf-8", errors="replace")
                        with open_maybe_gzip(out_path, "wt") as out:
                            if not no_header:
                                try:
                                    header = next(reader)
                                except StopIteration:
                                    return 0
                                out.write(header)
                            for line in reader:
                                if data_rows >= limit:
                                    break
                                out.write(line)
                                data_rows += 1

        return data_rows

    with urllib.request.urlopen(src) as resp:
        if is_gz:
            reader: io.TextIOBase = io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8", errors="replace")
        else:
            reader = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")

        with open_maybe_gzip(out_path, "wt") as out:
            if not no_header:
                try:
                    header = next(reader)
                except StopIteration:
                    return 0
                out.write(header)
            for line in reader:
                if data_rows >= limit:
                    break
                out.write(line)
                data_rows += 1
    return data_rows


def iter_lines(path: Path) -> Iterator[str]:
    with open_maybe_gzip(path, "rt") as f:
        for line in f:
            yield line


def main() -> None:
    args = parse_args()

    print(f"[DEBUG] Starting main() with args: {args}")
    parsed = urlparse(args.input)
    out_path = Path(args.output)
    input_is_dir = False
    if parsed.scheme == '' and Path(args.input).is_dir():
        input_is_dir = True

    print(f"[DEBUG] About to process input: {args.input}")
    is_tar = args.input.endswith('.tar') or args.input.endswith('.tar.gz')
    if is_tar:
        print(f"[DEBUG] Detected archive input (.tar/.tar.gz), will extract and sample from first text file.")
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = Path(tmpdir) / Path(args.input).name
            if parsed.scheme in {"http", "https"}:
                print(f"[DEBUG] Downloading archive from remote URL...")
                with urllib.request.urlopen(args.input) as resp, open(archive_path, "wb") as out:
                    shutil.copyfileobj(resp, out)
            else:
                print(f"[DEBUG] Copying archive from local path...")
                shutil.copy(args.input, archive_path)

            extract_dir = Path(tmpdir) / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, "r:*") as tar:
                tar.extractall(path=extract_dir)
            text_file = None
            for f in extract_dir.rglob("*"):
                if f.is_file():
                    mime, _ = mimetypes.guess_type(str(f))
                    if mime and (mime.startswith("text") or mime == "application/octet-stream"):
                        text_file = f
                        break
            if not text_file:
                print("[ERROR] No text file found in archive.")
                return
            print(f"[DEBUG] Sampling from extracted file: {text_file}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            data_rows = 0
            with open(text_file, "rt", encoding="utf-8", errors="replace") as src, open(out_path, "wt", encoding="utf-8") as out:
                for line in src:
                    if data_rows >= args.limit:
                        break
                    out.write(line)
                    data_rows += 1
            print(f"[DEBUG] Finished writing sampled lines from archive. data_rows={data_rows}")
        print(f"Wrote {data_rows} rows to {out_path}")
    else:
        if parsed.scheme in {"http", "https"}:
            print(f"[DEBUG] Detected HTTP/HTTPS input")
            data_rows = stream_sample_http(args.input, out_path, args.limit, args.no_header)
            print(f"[DEBUG] stream_sample_http returned: {data_rows}")
        else:
            print(f"[DEBUG] Detected local file input")
            tmp = Path("/tmp/download_and_sample")
            src_path = download_to_tmp(args.input, tmp)

            out_path.parent.mkdir(parents=True, exist_ok=True)
            data_rows = 0
            with open_maybe_gzip(out_path, "wt") as out:
                lines = iter_lines(src_path)
                if args.no_header:
                    pass
                else:
                    try:
                        header = next(lines)
                    except StopIteration:
                        print("[DEBUG] StopIteration: No lines in input file.")
                        return
                    out.write(header)
                for line in lines:
                    if data_rows >= args.limit:
                        break
                    out.write(line)
                    data_rows += 1
            print(f"[DEBUG] Finished writing sampled lines. data_rows={data_rows}")
        print(f"Wrote {data_rows} rows to {out_path}")



if __name__ == "__main__":
    main()
