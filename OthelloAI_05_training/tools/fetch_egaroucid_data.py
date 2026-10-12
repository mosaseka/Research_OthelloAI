"""Download and verify the official Egaroucid board/score training data.

Only Python's standard library is used.  The downloader asks the GitHub
Releases API for the current asset metadata, streams the asset through a
``.part`` file, verifies its size (and the publisher digest when available),
then records a locally computed SHA-256 in a provenance sidecar.

The ``verify`` and ``self-test`` commands do not access the network.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = "Nyanyan/Egaroucid"
RELEASE_TAG = "training_data"
ASSET_NAME = "Egaroucid_Train_Data.zip"
EXPECTED_SIZE = 401_502_981
EXPECTED_RECORDS = 25_514_097
RELEASE_API_URL = (
    f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{RELEASE_TAG}"
)
CANONICAL_DOWNLOAD_URL = (
    "https://github.com/Nyanyan/Egaroucid/releases/download/"
    "training_data/Egaroucid_Train_Data.zip"
)
SOURCE_PAGE = "https://www.egaroucid.nyanyan.dev/ja/technology/train-data/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "raw" / ASSET_NAME
USER_AGENT = "original-04-data-fetcher/1.0 (+offline Othello coursework)"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024


class DataError(RuntimeError):
    """A metadata, download, or verification failure."""


@dataclass(frozen=True)
class AssetMetadata:
    release_tag: str
    release_id: int
    release_published_at: str | None
    asset_id: int
    name: str
    size: int
    digest: str | None
    browser_download_url: str
    asset_updated_at: str | None

    @property
    def official_sha256(self) -> str | None:
        if self.digest is None:
            return None
        algorithm, separator, value = self.digest.partition(":")
        if separator != ":" or algorithm.lower() != "sha256":
            raise DataError(f"unsupported official asset digest: {self.digest!r}")
        return normalise_sha256(value)


def normalise_sha256(value: str) -> str:
    result = value.strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise DataError(f"invalid SHA-256 value: {value!r}")
    return result


def parse_release_metadata(payload: dict[str, Any]) -> AssetMetadata:
    """Select and validate the configured asset from a GitHub release response."""

    try:
        tag = str(payload["tag_name"])
        release_id = int(payload["id"])
        assets = payload["assets"]
    except (KeyError, TypeError, ValueError) as error:
        raise DataError("GitHub release metadata is missing required fields") from error
    if tag != RELEASE_TAG:
        raise DataError(f"release tag mismatch: expected {RELEASE_TAG!r}, got {tag!r}")
    if not isinstance(assets, list):
        raise DataError("GitHub release metadata field 'assets' is not a list")

    matches = [asset for asset in assets if asset.get("name") == ASSET_NAME]
    if len(matches) != 1:
        raise DataError(
            f"expected exactly one {ASSET_NAME!r} asset, found {len(matches)}"
        )
    asset = matches[0]
    try:
        metadata = AssetMetadata(
            release_tag=tag,
            release_id=release_id,
            release_published_at=payload.get("published_at"),
            asset_id=int(asset["id"]),
            name=str(asset["name"]),
            size=int(asset["size"]),
            digest=asset.get("digest"),
            browser_download_url=str(asset["browser_download_url"]),
            asset_updated_at=asset.get("updated_at"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DataError("GitHub asset metadata is missing required fields") from error

    if metadata.size != EXPECTED_SIZE:
        raise DataError(
            "official asset size changed: "
            f"expected {EXPECTED_SIZE}, API reports {metadata.size}; review before downloading"
        )
    if metadata.browser_download_url != CANONICAL_DOWNLOAD_URL:
        raise DataError(
            "official asset URL changed: "
            f"expected {CANONICAL_DOWNLOAD_URL!r}, got {metadata.browser_download_url!r}"
        )
    # Parse now so an unexpected digest algorithm fails before any download.
    metadata.official_sha256
    return metadata


def github_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def fetch_metadata(timeout: float) -> AssetMetadata:
    try:
        with urlopen(github_request(RELEASE_API_URL), timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise DataError(f"could not fetch GitHub release metadata: {error}") from error
    if not isinstance(payload, dict):
        raise DataError("GitHub release metadata root is not an object")
    return parse_release_metadata(payload)


def sha256_stream(stream: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def sha256_file(path: Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> tuple[str, int]:
    try:
        with path.open("rb") as stream:
            return sha256_stream(stream, chunk_size)
    except OSError as error:
        raise DataError(f"could not read {path}: {error}") from error


def provenance_path(path: Path) -> Path:
    return path.with_name(path.name + ".provenance.json")


def provenance_display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def load_recorded_sha256(path: Path) -> str | None:
    sidecar = provenance_path(path)
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        return normalise_sha256(payload["local_file"]["sha256"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, DataError) as error:
        raise DataError(f"invalid provenance sidecar {sidecar}: {error}") from error


def verify_local_file(
    path: Path,
    *,
    expected_size: int = EXPECTED_SIZE,
    expected_sha256: str | None = None,
    check_provenance: bool = True,
) -> dict[str, Any]:
    if not path.is_file():
        raise DataError(f"data file does not exist: {path}")
    expected_digest = normalise_sha256(expected_sha256) if expected_sha256 else None
    recorded_digest = load_recorded_sha256(path) if check_provenance else None
    digest, size = sha256_file(path)
    if size != expected_size:
        raise DataError(f"size mismatch for {path}: expected {expected_size}, got {size}")
    if expected_digest is not None and digest != expected_digest:
        raise DataError(
            f"SHA-256 mismatch for {path}: expected {expected_digest}, got {digest}"
        )
    if recorded_digest is not None and digest != recorded_digest:
        raise DataError(
            f"SHA-256 differs from {provenance_path(path)}: "
            f"recorded {recorded_digest}, got {digest}"
        )
    return {
        "status": "verified",
        "path": str(path.resolve()),
        "size": size,
        "sha256": digest,
        "expected_size": expected_size,
        "publisher_sha256": expected_digest,
        "provenance_sha256": recorded_digest,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except OSError as error:
        raise DataError(f"could not write {path}: {error}") from error


def make_provenance(
    path: Path,
    metadata: AssetMetadata,
    local_sha256: str,
    acquisition: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_page": SOURCE_PAGE,
        "release_api_url": RELEASE_API_URL,
        "asset": asdict(metadata),
        "local_file": {
            "path": provenance_display_path(path),
            "size": path.stat().st_size,
            "sha256": local_sha256,
        },
        "acquisition": acquisition,
        "expected_records": EXPECTED_RECORDS,
        "integrity_note": (
            "The publisher did not provide a SHA-256 for this release asset; "
            "this is a locally computed provenance hash."
            if metadata.official_sha256 is None
            else "The local SHA-256 was checked against the publisher digest."
        ),
    }


def print_progress(downloaded: int, expected: int) -> None:
    percentage = downloaded * 100.0 / expected if expected else 0.0
    print(
        f"downloaded {downloaded:,}/{expected:,} bytes ({percentage:5.1f}%)",
        file=sys.stderr,
    )


def download(metadata: AssetMetadata, output: Path, timeout: float, chunk_size: int) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".part")
    request = Request(
        metadata.browser_download_url,
        headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
    )
    digest = hashlib.sha256()
    downloaded = 0
    next_progress = 64 * 1024 * 1024

    try:
        with urlopen(request, timeout=timeout) as response, partial.open("wb") as stream:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != metadata.size:
                raise DataError(
                    "HTTP Content-Length mismatch: "
                    f"API reports {metadata.size}, server reports {content_length}"
                )
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if downloaded >= next_progress:
                    print_progress(downloaded, metadata.size)
                    next_progress += 64 * 1024 * 1024
    except DataError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise DataError(
            f"download failed after {downloaded:,} bytes; partial file kept at {partial}: {error}"
        ) from error

    local_sha256 = digest.hexdigest()
    if downloaded != metadata.size:
        raise DataError(
            f"download size mismatch; expected {metadata.size}, got {downloaded}; "
            f"partial file kept at {partial}"
        )
    if metadata.official_sha256 is not None and local_sha256 != metadata.official_sha256:
        raise DataError(
            "download SHA-256 mismatch; "
            f"expected {metadata.official_sha256}, got {local_sha256}; "
            f"partial file kept at {partial}"
        )
    try:
        os.replace(partial, output)
    except OSError as error:
        raise DataError(f"could not move verified file to {output}: {error}") from error
    write_json_atomic(
        provenance_path(output),
        make_provenance(output, metadata, local_sha256, "streamed-download"),
    )
    return verify_local_file(
        output,
        expected_sha256=metadata.official_sha256,
        check_provenance=True,
    )


def metadata_json(metadata: AssetMetadata) -> dict[str, Any]:
    result = asdict(metadata)
    result["official_sha256"] = metadata.official_sha256
    result["release_api_url"] = RELEASE_API_URL
    result["source_page"] = SOURCE_PAGE
    return result


def run_self_test() -> None:
    fixture = {
        "id": 123,
        "tag_name": RELEASE_TAG,
        "published_at": "2025-02-02T00:00:00Z",
        "assets": [
            {
                "id": 456,
                "name": ASSET_NAME,
                "size": EXPECTED_SIZE,
                "digest": None,
                "browser_download_url": CANONICAL_DOWNLOAD_URL,
                "updated_at": "2025-02-02T00:00:00Z",
            }
        ],
    }
    metadata = parse_release_metadata(fixture)
    assert metadata.official_sha256 is None

    payload = b"streamed test payload\n"
    expected = hashlib.sha256(payload).hexdigest()
    actual, size = sha256_stream(io.BytesIO(payload), chunk_size=3)
    assert size == len(payload)
    assert actual == expected
    assert normalise_sha256(expected.upper()) == expected

    this_file = Path(__file__)
    file_digest, file_size = sha256_file(this_file, chunk_size=17)
    report = verify_local_file(
        this_file,
        expected_size=file_size,
        expected_sha256=file_digest,
        check_provenance=False,
    )
    assert report["status"] == "verified"
    try:
        verify_local_file(
            this_file,
            expected_size=file_size + 1,
            check_provenance=False,
        )
    except DataError:
        pass
    else:
        raise AssertionError("existing-file size mismatch was not detected")
    try:
        normalise_sha256("not-a-sha256")
    except DataError:
        pass
    else:
        raise AssertionError("invalid SHA-256 was not detected")
    print("fetch_egaroucid_data: self-test passed")


def positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch or verify Egaroucid_Train_Data.zip without extracting it. "
            "The verify and self-test commands are offline."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download", help="query official metadata, stream to .part, verify, and record provenance"
    )
    download_parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help=f"destination (default: {DEFAULT_OUTPUT})"
    )
    download_parser.add_argument(
        "--timeout", type=positive_float, default=60.0, help="HTTP timeout in seconds"
    )
    download_parser.add_argument(
        "--chunk-size", type=positive_int, default=DEFAULT_CHUNK_SIZE, help=argparse.SUPPRESS
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="redownload even when an existing file passes local verification",
    )

    metadata_parser = subparsers.add_parser(
        "metadata", help="show official GitHub release metadata without downloading the asset"
    )
    metadata_parser.add_argument(
        "--timeout", type=positive_float, default=30.0, help="HTTP timeout in seconds"
    )

    verify_parser = subparsers.add_parser(
        "verify", help="offline size/SHA-256 verification of an existing local file"
    )
    verify_parser.add_argument(
        "--file", type=Path, default=DEFAULT_OUTPUT, help=f"file to verify (default: {DEFAULT_OUTPUT})"
    )
    verify_parser.add_argument(
        "--sha256",
        help=(
            "optional independently obtained expected SHA-256; otherwise the command checks "
            "the fixed size and any provenance sidecar, and always reports the computed hash"
        ),
    )

    subparsers.add_parser("self-test", help="run network-free metadata and integrity tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "self-test":
            run_self_test()
            return 0
        if args.command == "metadata":
            print(json.dumps(metadata_json(fetch_metadata(args.timeout)), indent=2, ensure_ascii=False))
            return 0
        if args.command == "verify":
            report = verify_local_file(args.file, expected_sha256=args.sha256)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0

        metadata = fetch_metadata(args.timeout)
        if args.output.exists() and not args.force:
            report = verify_local_file(
                args.output,
                expected_sha256=metadata.official_sha256,
                check_provenance=True,
            )
            report["status"] = "existing-file-verified"
            if not provenance_path(args.output).exists():
                write_json_atomic(
                    provenance_path(args.output),
                    make_provenance(
                        args.output,
                        metadata,
                        report["sha256"],
                        "pre-existing-file-verified",
                    ),
                )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        report = download(metadata, args.output, args.timeout, args.chunk_size)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (DataError, AssertionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
