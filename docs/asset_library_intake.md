# Local pose and expression asset intake

This is a separate, local preparation lane for **2D anime/manga character pose and
expression** references. Real-person photography, statues, realistic portraits, and
photographic body-reference material are rejected at source. It is not connected to Narrative Analyst, Timeline, StoryBible,
SceneContext, storyboard construction, prompts, or image generation.

## Source survey (2026-08-17)

- **BOOTH / illust-pose** is a curated **reference-link only** source. Its pose and
  expression products are explicit manga/illustration material, but each product is
  purchaser/account-scoped and prohibits redistribution. The first catalog stores
  only the product URL, author, controlled style tags, and a manual-review note—no
  image is downloaded. [Standing-pose product](https://booth.pm/ja/items/3500935),
  [expression product](https://booth.pm/en/items/3513807).
- **Lambda Delta Pose Archive** is also reference-link only. It offers manga/webtoon
  line-art pose packs, but zero-price checkout and per-product terms need a human to
  verify. No account is logged in and no asset is fetched automatically.
- **Wikimedia Commons, Openverse, POSEMANIACS, PoseMy.Art, Mixamo, Sketchfab, and
  OpenGameArt** are not automatic candidates for this anime-only lane. Commons is
  specifically disabled because the prior photographic/statue result set was wrong.

Every candidate must carry `style:anime_2d`, `style:manga_line_art`,
`style:chibi_2d`, or `style:anime_3d`, in addition to an action/expression, era,
and composition tag. This is an explicit contract guard rather than a visual model
guess. No automatic image-download source is enabled until a source offers both
anime/manga content and a documented no-login download license suitable for this
project.

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
uv run python scripts/asset_intake.py discover
uv run python scripts/asset_intake.py discover --write
uv run python scripts/asset_intake.py report
uv run python scripts/asset_intake.py download --limit 300 --max-file-mib 25
```

`discover` is dry-run by default and currently creates only the reviewed manga-site
link catalog. `download` has a 25 MiB per-file default, rejects
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

`AssetManifestV1` is a new standalone, portable Schema v1.0. Its required visual
style tag prevents a source from being classified as an anime/manga candidate solely
because it depicts a person. Runtime manifest JSON
stores only relative local paths and sanitized source metadata—never cookies, API
keys, login data, raw provider/API responses, absolute user paths, or web screenshots.
It does not alter Narrative Proposal, Timeline, or StoryBible schemas. No database
migration is required: manifests are local JSON files and raw assets are ignored by
Git. Part-whole entity resolution and semantic image analysis are intentionally out
of scope.
