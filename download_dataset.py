"""
DataverseNL Dataset Downloader
Iterates through all pages of a Dataverse dataset (e.g. Eindhoven Wildflower Dataset)
and downloads files in batches (pages of 10) into the target folder.

Bypasses Anubis bot protection automatically via proof-of-work solving.
Supports resuming, checksum verification, atomic downloads, and page ranges.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request


DEFAULT_DOI = "doi:10.34894/U4VQJ6"
DEFAULT_HOST = "https://dataverse.nl"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class DataverseClient:
    """HTTP client with automatic Anubis challenge solving and cookie management."""

    def __init__(self, base_host: str = DEFAULT_HOST):
        self.base_host = base_host.rstrip("/")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT)]

    def _solve_anubis(self, html: str, original_url: str) -> None:
        """Solves Xe Iaso's Anubis proof-of-work challenge and passes it."""
        print("  [*] Anubis anti-bot challenge detected. Solving proof-of-work...")
        start_tag = '<script id="anubis_challenge" type="application/json">'
        idx_start = html.find(start_tag)
        if idx_start == -1:
            raise RuntimeError("Could not find anubis_challenge script tag in HTML.")

        idx_start += len(start_tag)
        idx_end = html.find("</script>", idx_start)
        chal_json = html[idx_start:idx_end].strip()
        chal_data = json.loads(chal_json)

        chal = chal_data["challenge"]
        rules = chal_data["rules"]
        diff = rules["difficulty"]
        random_data = chal["randomData"]
        chal_id = chal["id"]

        prefix = "0" * diff
        r_bytes = random_data.encode("ascii")
        t0 = time.time()
        nonce = 0
        found_hash = ""

        # Solve PoW: find nonce where sha256(randomData + nonce) starts with '0' * difficulty
        while True:
            candidate = r_bytes + str(nonce).encode("ascii")
            h = hashlib.sha256(candidate).hexdigest()
            if h.startswith(prefix):
                found_hash = h
                break
            nonce += 1

        elapsed = int((time.time() - t0) * 1000)
        print(f"  [+] Solved PoW in {elapsed}ms! (Nonce: {nonce})")

        # Submit response to get authorization cookie
        pass_url = f"{self.base_host}/.within.website/x/cmd/anubis/api/pass-challenge?" + urllib.parse.urlencode({
            "id": chal_id,
            "response": found_hash,
            "nonce": nonce,
            "redir": original_url,
            "elapsedTime": elapsed,
        })

        resp = self.opener.open(pass_url)
        resp.read()  # Drain response body to complete redirection

    def open(self, url: str, stream: bool = False):
        """Opens a URL, handling Anubis challenges transparently if encountered."""
        resp = self.opener.open(url)
        content_type = resp.headers.get("Content-Type", "")

        # Check if we were served the Anubis challenge HTML instead of the expected resource
        if "text/html" in content_type:
            # Peek without consuming entire stream if stream=True
            sample = resp.peek(2048) if hasattr(resp, "peek") else resp.read(2048)
            sample_str = sample.decode("utf-8", errors="ignore") if isinstance(sample, bytes) else sample
            if "anubis_challenge" in sample_str:
                # Read full html to solve challenge
                full_html = sample_str + resp.read().decode("utf-8", errors="ignore")
                self._solve_anubis(full_html, url)
                # Re-issue original request with the newly acquired cookie
                resp = self.opener.open(url)

        return resp

    def get_dataset_metadata(self, persistent_id: str) -> dict:
        """Retrieves dataset metadata from Dataverse REST API."""
        api_url = f"{self.base_host}/api/datasets/:persistentId/?persistentId={urllib.parse.quote(persistent_id)}"
        resp = self.open(api_url)
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "OK":
            raise RuntimeError(f"Dataverse API error: {data}")
        return data["data"]


def format_bytes(num_bytes: int | float) -> str:
    """Formats bytes into human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def download_file(
    client: DataverseClient,
    file_id: int,
    filename: str,
    target_path: Path,
    expected_size: int,
    expected_checksum: str | None,
    verify_checksum: bool = True,
    chunk_size: int = 256 * 1024,
) -> bool:
    """
    Downloads a single file from Dataverse with resume support, streaming,
    and SHA-1 checksum verification. Returns True if downloaded, False if skipped.
    """
    # Check if file already exists and is complete
    if target_path.exists():
        actual_size = target_path.stat().st_size
        if actual_size == expected_size:
            print(f"    [Skipped] {filename} already exists ({format_bytes(expected_size)}).")
            return False
        else:
            print(f"    [Notice] {filename} exists but size mismatch ({actual_size} != {expected_size}). Re-downloading...")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(target_path.name + ".part")

    download_url = f"{client.base_host}/api/access/datafile/{file_id}"
    resp = client.open(download_url)

    sha1_hasher = hashlib.sha1() if verify_checksum else None
    downloaded_bytes = 0
    t0 = time.time()
    last_print = t0

    with open(temp_path, "wb") as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded_bytes += len(chunk)
            if sha1_hasher:
                sha1_hasher.update(chunk)

            # Update progress line periodically for larger files
            now = time.time()
            if expected_size > 5 * 1024 * 1024 and (now - last_print > 0.5 or downloaded_bytes == expected_size):
                speed = downloaded_bytes / max(now - t0, 0.001)
                percent = (downloaded_bytes / expected_size * 100) if expected_size > 0 else 0
                print(
                    f"\r    -> {filename}: {percent:.1f}% ({format_bytes(downloaded_bytes)}/{format_bytes(expected_size)}) "
                    f"at {format_bytes(speed)}/s",
                    end="",
                    flush=True,
                )
                last_print = now

    if expected_size > 5 * 1024 * 1024:
        print()  # newline after progress bar

    # Verify SHA-1 if available
    if sha1_hasher and expected_checksum:
        calculated_sha1 = sha1_hasher.hexdigest().lower()
        if calculated_sha1 != expected_checksum.lower():
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(
                f"Checksum mismatch for {filename}! Expected {expected_checksum}, calculated {calculated_sha1}"
            )

    # Rename .part to final destination
    if temp_path.exists():
        temp_path.replace(target_path)

    elapsed = max(time.time() - t0, 0.001)
    speed = downloaded_bytes / elapsed
    print(
        f"    [Done] {filename} ({format_bytes(downloaded_bytes)}) in {elapsed:.1f}s ({format_bytes(speed)}/s)"
    )
    return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download files from a Dataverse dataset, page by page (default: 10 files per page)."
    )
    parser.add_argument(
        "--url",
        default="https://dataverse.nl/dataset.xhtml?persistentId=doi:10.34894/U4VQJ6",
        help="Dataset web page URL or persistentId (default: doi:10.34894/U4VQJ6)",
    )
    parser.add_argument(
        "--target-dir",
        "-d",
        default=".",
        help="Target folder to save downloaded files into (default: current directory)",
    )
    parser.add_argument(
        "--page-size",
        "-s",
        type=int,
        default=10,
        help="Number of files per page/batch (default: 10, matching the web interface pagination)",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="1-based page number to start from (default: 1)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="1-based page number to stop at (default: all pages)",
    )
    parser.add_argument(
        "--file-type",
        choices=["all", "jpg", "xml"],
        default="all",
        help="Filter downloads by file extension (all, jpg, xml). Default: all",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Seconds of delay between file downloads to respect the server (default: 0.2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect dataset and list pages without actually downloading files.",
    )
    parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="Skip SHA-1 integrity verification.",
    )
    return parser.parse_args()


def extract_persistent_id(url_or_id: str) -> str:
    """Extracts persistentId (doi:...) from URL or returns raw ID."""
    if "persistentId=" in url_or_id:
        parsed = urllib.parse.urlparse(url_or_id)
        params = urllib.parse.parse_qs(parsed.query)
        if "persistentId" in params:
            return params["persistentId"][0]
    return url_or_id


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    persistent_id = extract_persistent_id(args.url)
    print(f"Connecting to Dataverse for dataset: {persistent_id}")
    print(f"Destination folder: {target_dir}")

    client = DataverseClient(base_host=DEFAULT_HOST)

    # 1. Fetch dataset metadata
    print("Fetching dataset metadata...")
    dataset_info = client.get_dataset_metadata(persistent_id)
    latest_version = dataset_info.get("latestVersion", {})
    files_list = latest_version.get("files", [])

    total_files_in_dataset = len(files_list)
    print(f"Dataset title: {latest_version.get('citationDate', '')} - {latest_version.get('datasetPersistentId', '')}")
    print(f"Total files available: {total_files_in_dataset}")

    # 2. Filter files if requested
    if args.file_type != "all":
        target_ext = f".{args.file_type.lower()}"
        files_list = [f for f in files_list if f.get("dataFile", {}).get("filename", "").lower().endswith(target_ext)]
        print(f"Filtered to {len(files_list)} files matching *{target_ext}")

    total_files = len(files_list)
    if total_files == 0:
        print("No files to download.")
        return 0

    page_size = max(1, args.page_size)
    total_pages = (total_files + page_size - 1) // page_size

    start_page = max(1, args.start_page)
    end_page = min(total_pages, args.end_page) if args.end_page else total_pages

    print(f"\nConfiguration:")
    print(f"  - Page size: {page_size} files per page")
    print(f"  - Total pages: {total_pages}")
    print(f"  - Processing pages: {start_page} to {end_page}")
    print(f"  - Checksum verification: {'Disabled' if args.skip_checksum else 'Enabled (SHA-1)'}")
    if args.dry_run:
        print("  - Mode: DRY RUN (no files will be written)")

    total_downloaded = 0
    total_bytes_downloaded = 0
    total_skipped = 0

    # 3. Iterate through pages
    for page_num in range(start_page, end_page + 1):
        idx_start = (page_num - 1) * page_size
        idx_end = min(idx_start + page_size, total_files)
        page_files = files_list[idx_start:idx_end]

        print("\n" + "=" * 80)
        print(f"Page {page_num}/{total_pages} (Items {idx_start + 1} to {idx_end} of {total_files})")
        print("=" * 80)

        for i, item in enumerate(page_files, 1):
            data_file = item.get("dataFile", {})
            file_id = data_file.get("id")
            filename = data_file.get("filename")
            filesize = data_file.get("filesize", 0)
            checksum_info = data_file.get("checksum", {})
            sha1_hash = checksum_info.get("value") if checksum_info.get("type") == "SHA-1" else None

            print(f"  [{i}/{len(page_files)}] {filename} (ID: {file_id}, {format_bytes(filesize)})")

            if args.dry_run:
                continue

            dest_path = target_dir / filename
            try:
                downloaded = download_file(
                    client=client,
                    file_id=file_id,
                    filename=filename,
                    target_path=dest_path,
                    expected_size=filesize,
                    expected_checksum=sha1_hash,
                    verify_checksum=not args.skip_checksum,
                )
                if downloaded:
                    total_downloaded += 1
                    total_bytes_downloaded += filesize
                else:
                    total_skipped += 1

                if args.delay > 0:
                    time.sleep(args.delay)

            except Exception as e:
                print(f"    [ERROR] Failed to download {filename}: {e}", file=sys.stderr)

        print(f"Page {page_num}/{total_pages} finished.")

    print("\n" + "=" * 80)
    print("Download Summary:")
    print(f"  - Newly downloaded: {total_downloaded} files ({format_bytes(total_bytes_downloaded)})")
    print(f"  - Already existed (skipped): {total_skipped} files")
    print("All requested pages processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
