# Local pose and expression asset intake

This is a separate, local preparation lane for human-reviewed pose and expression
references. It is not connected to Narrative Analyst, Timeline, StoryBible,
SceneContext, storyboard construction, prompts, or image generation.

## Source survey (2026-08-17)

- **Wikimedia Commons** is the only enabled discovery/download source in the first
  batch. The code uses its official MediaWiki Action API with `prop=imageinfo` and
  `extmetadata`, which exposes file URLs, MIME/size, author/credit, and license
  metadata ([ImageInfo API documentation](https://www.mediawiki.org/wiki/API:Imageinfo)).
  It does not scrape Commons HTML. Only direct `https://upload.wikimedia.org/...`
  image URLs with confirmed CC0 or Public Domain metadata are downloadable into
  `incoming/production_candidate`; CC BY enters `incoming/attribution_review` with
  attribution metadata. Every human pose/expression candidate remains PENDING for
  likeness, trademark, and private-place review.
- **Openverse** may be a future discovery entry only. Its search metadata is not
  treated as final license proof; no Openverse asset is downloaded in this batch
  until its original source page and license are independently verified.
- **POSEMANIACS, PoseMy.Art, Mixamo, Sketchfab, and OpenGameArt** are reference-link
  sources only unless a later source-specific review approves an official API or
  package path. This implementation does not crawl their pages, log in, collect
  screenshots, or automate a browser.

License routing is fixed: CC0/PDM → production candidate; CC BY → attribution
review; CC BY-SA/GPL/OGA-BY → reference-only; NC/ND/custom/missing → rejected and
not downloaded. A license code, license URL, author, source page URL, allowed MIME,
file size, and allowed host are all required before a download. The user still makes
the final keep/reference/reject decision.

## Storage and commands

Mutable data is deliberately outside Git at `D:\107\asset_library\`:

```text
incoming/production_candidate/   verified CC0/PDM candidates, still PENDING
incoming/attribution_review/     CC BY candidates with attribution
incoming/reference_only/         human-designated local references
approved/                        retained files
rejected/                        rejected files; never automatically deleted
thumbnails/ manifests/ review_console/
```

Use the bounded command-line workflow:

```powershell
uv run python scripts/asset_intake.py discover --limit 150
uv run python scripts/asset_intake.py discover --limit 150 --write
uv run python scripts/asset_intake.py report
uv run python scripts/asset_intake.py download --limit 300 --max-file-mib 25
```

`discover` is dry-run by default. `download` has a 25 MiB per-file default, rejects
redirects and unknown hosts/MIME types, uses SHA-256 duplicate detection, and checks
the 10 GiB library ceiling before each asset and thumbnail. It does not retry an
item automatically. No command deletes files.

Start the API bound to loopback only, then visit
`http://127.0.0.1:8080/console/assets/`:

```powershell
uv run uvicorn comic_agent.main:app --host 127.0.0.1 --port 8080
```

The review page supports era/tag/source/license/status/size filtering. “保留”,
“仅参考”, and “拒绝” update the manifest, retain a review timestamp/note, and move
an existing local file to `approved`, `incoming/reference_only`, or `rejected`.
It cannot bulk-delete, upload files, send files to third parties, or use them in a
prompt.

## Contract and migration

`AssetManifestV1` is a new standalone, portable Schema v1.0. Runtime manifest JSON
stores only relative local paths and sanitized source metadata—never cookies, API
keys, login data, raw provider/API responses, absolute user paths, or web screenshots.
It does not alter Narrative Proposal, Timeline, or StoryBible schemas. No database
migration is required: manifests are local JSON files and raw assets are ignored by
Git. Part-whole entity resolution and semantic image analysis are intentionally out
of scope.
