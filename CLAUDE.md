# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**RekogNail** (formerly SmartThumb SA, the name in the proposal `.docx`): a serverless AWS pipeline in eu-west-1. A product photo uploaded to S3 triggers a Python Lambda that makes a ≤300×300 thumbnail and optionally gets Amazon Rekognition labels. A single-page web app on a public CloudFront URL is the team's test harness. Requirements FR1–FR7 come from the proposal; `README.md` maps them to evidence and holds the measured results, and `docs/presentation-notes.md` is the Friday demo script and Q&A.

## Commands

```bash
make setup                      # .venv via uv, installs requirements-dev.txt
make test                       # all unit tests
.venv/bin/python -m pytest tests/test_api.py::test_page_cacheable_with_etag -q   # single test
make images && make batch       # generate test_images/generated, run them through the LIVE site -> results/metrics.csv
make url / make code            # live CloudFront URL / team code (from Terraform outputs)
make logs                       # tail processor CloudWatch logs (needs AWS creds)
```

No linter is configured. CI also checks that the page's inline JS parses:
`python -c "s=open('web/index.html').read(); open('/tmp/page.mjs','w').write(s.split('<script>')[1].split('</script>')[0])" && node --check /tmp/page.mjs`

**Setup / teardown:** `scripts/setup.sh [--email ...] [--with-ci] [--no-labels]` goes from an empty account to a live URL (state bucket, layer, saved-plan apply, budget). `scripts/teardown.sh` removes everything except the account-level budget (`scripts/budget.sh`, deliberately outside Terraform), backing the buckets up to `results/backup-<date>/` first.

**CI is disabled** (`gh workflow disable`). When enabled via `setup.sh --with-ci`, pushing to `main` deploys: `.github/workflows/deploy.yml` runs tests, builds the Pillow layer, runs `terraform plan -out`, applies exactly that plan, then smoke-tests the live URL. Pull requests run tests only. AWS access uses OIDC: the `github-deploy-smartthumb` role trusts this repo's *immutable* OIDC subject (`repo:owner@<id>/name@<id>`), and `scripts/bootstrap_ci.sh` reads that prefix from the GitHub API.

Local `make deploy` also works. The Makefile wraps Terraform with `aws configure export-credentials` because Terraform can't read `aws login` sessions. State is shared in S3 (`infra/backend.hcl`, lockfile), so local and CI applies hit the same stack.

## Architecture (the parts that span files)

- **Two Lambdas, both named `handler.py`.** `src/processor/handler.py` handles S3 events. `src/api/handler.py` serves the web app and the JSON API. Tests load the API handler via `importlib.util.spec_from_file_location` to avoid the module-name clash. Keep it that way.
- **`web/index.html` is packaged into the API Lambda zip** (`archive_file` in `infra/lambda.tf`) and served at `GET /`. It uses relative `/api/...` paths, so it works both via CloudFront and via the old API Gateway URL. Locally the handler falls back to reading `web/index.html`.
- **No database: the `meta/<upload-key>.json` files in the output bucket are the data store.** The processor writes one per upload (status ok/rejected/error, sizes, timings, labels, tester). The API reads them for results, the gallery, summaries and votes (votes are written back into the same file). Thumbnails live at `thumbs/<key-without-ext>.jpg|png`. Upload keys are `uploads/YYYYmmdd-HHMMSS-<6hex>/<filename>`, and the gallery sorts by key (= upload time).
- **Processor contract:** every record gets a meta file, even when rejected, and the processor never raises, so the UI and test suite can show FR7 rejections. Validation is by file content (Pillow), not only the extension. The S3 notification deliberately has **no suffix filter**, so bad files reach the processor and are rejected visibly. Thumbnails get `Cache-Control: immutable`, which is safe because keys are unique per upload.
- **API caching:** `META_CACHE` (module-level, survives warm invocations) keyed by S3 ETag, so the gallery only re-downloads changed meta files. `/api/results` (no key) returns slim cards (`CARD_FIELDS`), paging (`offset/limit`), server-side filters (`status`, `tester`) and a `summary` over *all* results. **The frontend must tolerate fields missing from cards**: label `categories` were dropped once and broke the gallery. Single-key results still include `original_url`; elsewhere originals are signed on demand via `/api/original`.
- **CloudFront** (`infra/cloudfront.tf`): `/thumbs/*` comes from the private output bucket via OAC (the bucket policy allows only this distribution, only `thumbs/*`). `/api/*` goes to API Gateway uncached. `/*` (the page) is cached for the Lambda's `max-age=60` + ETag, so page changes take up to ~60 s to show after a deploy. The API Lambda gets `THUMB_BASE_URL` (the distribution domain) for thumbnail URLs.
- **Browser uploads** go straight to the private source bucket via presigned POST (size limit enforced by S3). The S3 client uses the **regional virtual-host endpoint** on purpose: the global endpoint 307-redirects new buckets, which breaks browser CORS. Source bucket CORS must list both the CloudFront and the API Gateway origins.
- **Logging:** both Lambdas print one JSON line per event via `log(level, event, **fields)`. `/api/logs` (`FilterLogEvents`), the web Logs tab, the in-browser test suite (FR6 looks for `event == "processed"` with the key) and the CloudWatch dashboard queries in `infra/monitoring.tf` all depend on these field names (`event`, `status`, `key`, `tester`, `duration_ms`, `reduction_pct`, ...).
- **Auth:** a shared team code in the `x-team-code` header, checked in the API Lambda (`TEAM_CODE` env from Terraform, generated if empty; `terraform output -raw team_code`). `GET /` is unauthenticated. Don't commit the code into docs.

## Constraints and gotchas

- **Do not rename the `smartthumb-*` AWS resources** (buckets, functions, roles, state bucket). The product rename to RekogNail is UI/docs only; renaming resources would recreate the live buckets and lose data. The CI smoke test asserts `RekogNail` appears in the page.
- **Pillow version is pinned in two places:** `requirements-dev.txt` and `scripts/build_layer.sh` (manylinux wheel, no Docker). Keep them in sync. `--no-compile` keeps the layer zip reproducible, so CI doesn't publish a new layer version every run.
- **New AWS account limits:** Lambda account concurrency is 10, so `reserved_concurrent_executions` fails. Don't add it back.
- **Rekognition isn't available in af-south-1**, which is why everything is in eu-west-1. `enable_labels` toggles the env var and the IAM statement together.
- **Applies happen in CI from a saved plan.** When applying locally, also use `plan -out` and apply that plan (the auto-mode classifier blocks blind `apply -auto-approve`).
- **Results figures in `README.md` and `docs/presentation-notes.md` were pulled from the live API.** Refresh them from `/api/results` (page through `next_offset`) rather than editing numbers by hand.
