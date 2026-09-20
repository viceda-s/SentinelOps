# ADR-013: Release Please for automated versioning and changelog generation

**Status:** Accepted

## Context

`CHANGELOG.md` was a hand-curated record scoped to design decisions (`docs/DESIGN.md`), not every commit — its own header said so, and `ROADMAP.md` described it the same way. There was no git tag, no `VERSION` file, and no `[project] version` anywhere in the repo; the only version number lived in `CHANGELOG.md`'s heading, updated by hand.

Commit history already follows Conventional Commits consistently, which is the precondition Release Please needs: it parses commit messages on `main` to decide the next version bump and changelog entries.

The user wanted version bumps automated, explicitly accepting that this replaces the hand-curated `CHANGELOG.md` format with Release Please's generated one (commits grouped by Conventional Commit type) going forward. Per ADR-012, Jenkins is this repo's primary, required CI/CD pipeline; this decision keeps release automation there rather than adding a second automation surface in GitHub Actions.

## Decision

Release Please runs as a non-blocking Jenkins stage (`Release Please`, gated to `main` via `when { branch 'main' }`, placed after `Quality Gate` and before `Container Build`), using the npm CLI installed on `jenkins-agent`.

**Why not the GitHub Action:** it would split release automation across two CI systems, working against ADR-012's "one pipeline of record" reasoning, and would run independent of Jenkins's own pass/fail signal.

**Why non-blocking:** Release Please's job is release bookkeeping, not code validation. A failure (GitHub API outage, expired token, rate limit) has nothing to do with whether the merged code is correct, and shouldn't block otherwise-green builds. The stage is wrapped in `catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE')`.

**Why both `release-pr` and `github-release` run on every `main` push:** `main` only advances through (a) normal feature-branch merges, which `release-pr` should fold into the standing release PR, and (b) merging the release PR itself, which `github-release` needs to see to cut the tag/GitHub Release. Both look identical to the pipeline ("a push landed on `main`"), so both commands run every time. This is supported by Release Please's own CLI docs, which describe this class of command as designed to be safely re-run repeatedly, including when there's nothing to do.

**Version source:** `pyproject.toml` gained a `[project]` table (`name`, `version`) as the `python` release-type's version anchor, rather than introducing an unrelated `VERSION.txt`. The project isn't published as an installable package — the `[project]` table exists solely because Release Please's `python` release-type requires it as a version anchor.

**Token handling:** `--token="$GITHUB_TOKEN"` is passed explicitly to both CLI invocations, sourced via Jenkins `withCredentials` from a Jenkins-stored credential scoped to `Contents: Read and write` + `Pull requests: Read and write` on this repo. The CLI docs list `--token` as required and don't document environment-variable-only support, so it's passed as documented rather than assumed unnecessary. (The specific Jenkins credential ID is an operational detail configured in Jenkins itself, intentionally not documented here — it's mutable infrastructure state, not an architectural decision.)

### Amendment: Docker image abandoned in favor of the npm CLI

The original version of this decision chose the official Docker image (`gcr.io/release-please/release-please`) specifically to avoid installing a Node.js runtime on `jenkins-agent`. During implementation, that image turned out to be **permanently unpullable**: `docker pull`/`docker run` against every tag (including `:latest`) fails with `This API method requires billing to be enabled` on the GCP project backing that GCR repository — not a transient registry hiccup, but the underlying Google Cloud project itself lacking active billing. Separately, Release Please's own README documents only two supported run methods — the GitHub Action and the npm CLI — with no Docker image mentioned at all, meaning the image was never an officially documented distribution channel to begin with.

`docker/jenkins-agent/Dockerfile` gained a Node.js runtime as a result — copied from the official `node:22-slim` image via a multi-stage build, rather than installed via NodeSource's script (which failed intermittently with opaque `npm error network` failures specific to this build context) or Debian trixie's own `apt` `nodejs` package (Node 20, which triggers an `EBADENGINE` warning from a release-please transitive dependency requiring Node ≥22). The pinned CLI version (`release-please@17.11.2`) is installed via `npm install -g` during the image build.

## Alternatives considered

- **GitHub Action (`googleapis/release-please-action`).** Rejected: splits release automation across two CI systems; runs independent of Jenkins's pass/fail signal.
- **Official Docker image (`gcr.io/release-please/release-please`).** Originally chosen, then abandoned during implementation — see Amendment above.
- **`VERSION.txt` + `release-type: simple`.** Rejected in favor of `pyproject.toml` + `release-type: python`: reuses an existing file instead of introducing a version file disconnected from any real project manifest.
- **Blocking stage.** Rejected: conflates release bookkeeping with code-correctness validation.

## Consequences

- `CHANGELOG.md`'s format changes from this point forward: new entries are commit-derived and grouped by Conventional Commit type, not hand-written design narrative. Existing entries (`[1.1]` through `[1.3.0]`) are unaffected.
- `pyproject.toml` carries a `[project]` table purely as Release Please's version anchor; the project still isn't published as an installable package.
- `docker/jenkins-agent/Dockerfile` now includes a Node.js runtime, used solely to run the `release-please` CLI.
- Every push to `main` with unreleased Conventional Commits opens or updates a standing release PR until merged; merging it is what actually cuts the version bump, tag, and GitHub Release.
- If the Post-v1 Docker-socket-proxy hardening (ADR-012) is ever applied to `jenkins-agent`, this stage is unaffected — it doesn't use `docker run`, unlike the existing Trivy stage.
