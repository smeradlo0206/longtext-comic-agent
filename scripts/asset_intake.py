"""Local-only CLI for controlled public reference-asset intake.

The command never sends assets to a provider and never touches StoryBible.  It
uses only the official Wikimedia Commons Action API configured in the service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comic_agent.services.asset_library import (
    DEFAULT_ASSET_LIBRARY_ROOT,
    AssetIntakeError,
    AssetLibraryPaths,
    AssetLibraryService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled local reference-asset intake")
    parser.add_argument("--root", type=Path, default=DEFAULT_ASSET_LIBRARY_ROOT)
    subcommands = parser.add_subparsers(dest="command", required=True)
    discover = subcommands.add_parser("discover", help="Discover official-API candidates")
    discover.add_argument("--limit", type=int, default=150)
    discover.add_argument("--source", default="reference_only_catalog")
    discover.add_argument("--tag", action="append", default=[])
    discover.add_argument(
        "--write", action="store_true", help="Persist manifests; default is dry-run"
    )
    download = subcommands.add_parser("download", help="Download eligible persisted candidates")
    download.add_argument("--limit", type=int, default=300)
    download.add_argument("--max-file-mib", type=int, default=25)
    subcommands.add_parser("report", help="Summarize local manifests and files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = AssetLibraryService(AssetLibraryPaths(args.root))
    try:
        if args.command == "discover":
            manifests = service.discover(
                limit=args.limit,
                source=args.source,
                tags=set(args.tag) or None,
                dry_run=not args.write,
            )
            output = {
                "dry_run": not args.write,
                "candidate_count": len(manifests),
                "estimated_asset_bytes": sum(item.bytes_size or 0 for item in manifests),
                "candidates": [
                    {
                        "asset_id": item.asset_id,
                        "source": item.source_site,
                        "license": item.license_code,
                        "page": item.original_page_url,
                        "tags": item.tags,
                    }
                    for item in manifests
                ],
            }
        elif args.command == "download":
            manifests = service.download_pending(
                max_files=args.limit,
                max_file_bytes=args.max_file_mib * 1024**2,
            )
            output = {
                "downloaded_count": len(manifests),
                "downloaded_bytes": sum(item.bytes_size or 0 for item in manifests),
                "root": str(args.root),
            }
        else:
            output = service.report()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except AssetIntakeError as error:
        print(f"asset intake stopped safely: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
