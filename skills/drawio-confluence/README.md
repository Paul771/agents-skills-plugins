# drawio-confluence — Live, Editable draw.io Diagrams in Confluence

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/Paul771/agents-skills-plugins?logo=github)](https://github.com/Paul771/agents-skills-plugins/commits/main)
[![GitHub stars](https://img.shields.io/github/stars/Paul771/agents-skills-plugins?style=flat&logo=github)](https://github.com/Paul771/agents-skills-plugins/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Paul771/agents-skills-plugins?style=flat&logo=github)](https://github.com/Paul771/agents-skills-plugins/network/members)

Companion to [drawio-skill](https://github.com/Agents365-ai/drawio-skill) — that skill
authors the `.drawio` XML, this one publishes it into Confluence as a **live,
inline-editable diagram** instead of a flat PNG preview.

## ✨ Highlights

**One fact decides everything**

- **The media type is the whole ballgame** — Confluence's draw.io app resolves a
  diagram by attachment name **and** media type. The type must be
  `application/vnd.jgraph.mxfile`. Anything else returns `404` and renders an
  empty frame, *while the page itself still returns HTTP 200 and the attachment
  is visibly present*. An attachment being attached proves nothing.
- **The header that lies** — `X-Atlassian-Override: media-type=…` is silently
  ignored. The type is taken from the `Content-Type` of the multipart part
  itself.
- **Two misleading signals, documented** — `403` on `/rest/drawio/1.0/license/status`
  and failed `POST`/`PUT`/`DELETE` on the crud endpoint both occur on pages
  whose diagrams work perfectly. The skill lists them as red herrings so they
  are not mistaken for a broken app.

**Publish and maintain**

- **Live editing, no PNG** — readers double-click the diagram and edit it in the
  browser; the macro keeps working afterwards, because the diagram *is* the
  attachment.
- **Migrates existing previews** — converts `<img>` and `<ac:image>` embeds on
  existing pages, rewrites the body, and drops the now-redundant
  "download `.drawio`" links.
- **Never points a macro at a missing attachment** — `convert` uploads first,
  confirms every diagram resolves, and only then rewrites the page.
- **Auditable** — `check` reports every diagram on a page with its media type and
  resolution status; `verify` opens a real browser and counts rendered SVGs.

**Practical**

- **Python 3 standard library only** — no `requests`, no plugin, no daemon.
  Playwright is optional and only needed for `verify`.
- **No secrets in the repo** — credentials come from environment variables.

## 🚀 Installation

### 1. Install the skill

```bash
git clone https://github.com/Paul771/agents-skills-plugins.git
cp -r agents-skills-plugins/skills/drawio-confluence ~/.claude/skills/
```

For OpenCode, copy the directory to `~/.config/opencode/skills/`.

### 2. Provide credentials

```bash
export CONFLUENCE_BASE_URL="https://confluence.example.internal"
export CONFLUENCE_PAT="<bearer token>"
```

A personal access token with read/write on the target space. The script also
accepts `CONFLUENCE_TOKEN`, `CONFLUENCE_API_TOKEN`, or `CONFLUENCE_BEARER_TOKEN`;
`--base-url` and `--pat` override the environment.

### 3. Optional: browser verification

```bash
pip install playwright && playwright install chrome
```

Only `verify` needs this. Everything else is offline HTTP.

## ⚡ Quick Start

```bash
cd ./diagrams
export CONFLUENCE_BASE_URL="https://confluence.example.internal"
export CONFLUENCE_PAT="<bearer token>"

# audit: which diagrams resolve, and with what media type
python3 scripts/publish.py check --page 3059024222

# upload .drawio files with the required media type
python3 scripts/publish.py upload --page 3059024222 --dir .

# replace PNG previews with drawio macros
python3 scripts/publish.py embed --page 3059024222 --dir .

# both at once, for every diagram found in the page body
python3 scripts/publish.py convert --page 3059024222 --dir .

# prove it in a browser
python3 scripts/publish.py verify --page 3059024222 --space MER --expect 8
```

## 🔍 Why your diagram is probably invisible

The failure mode is nasty because **nothing looks wrong from the outside**: the
page loads, the macro is present, the attachment is listed in the page
properties, and the HTTP response is `200`. The frame is just empty.

`check` names the cause directly:

```text
page 3059024222  v11
  8 PNG embed(s), 0 macro(s), 16 attachment(s)
  01-integration-architecture   embed  mediaType=application/xml           crud=404 <-- FIX
  02-sap-integration-flow       embed  mediaType=application/xml           crud=404 <-- FIX
```

| media type of the `.drawio` attachment | `crud` | macro |
| --- | --- | --- |
| `application/vnd.jgraph.mxfile` | **200** | works |
| `application/xml` | 404 | error frame |
| `application/octet-stream` | 404 | error frame |

Use the `crud` endpoint as the oracle — it is the single cheapest check:

```bash
curl -H "Authorization: Bearer $CONFLUENCE_PAT" \
  "$CONFLUENCE_BASE_URL/rest/drawio/1.0/diagram/crud/01-x.drawio/3059024222?revision=1"
```

Full symptom → cause → fix table, and the diagnostic order that avoids guessing,
in [references/troubleshooting.md](references/troubleshooting.md).

### Signals that do **not** mean the app is broken

| Signal | Reality |
| --- | --- |
| `403` on `/rest/drawio/1.0/license/status` | Occurs on pages where every diagram renders **and** edits correctly. Not a fault indicator. |
| `409` / `400` / `405` on `POST`/`PUT`/`DELETE` to `crud` | Diagrams live in attachments, not a separate store. Only the `GET` matters. |
| `404` on `…/diagram/crud/{name}.png` | The app probing for a cached preview. Expected; the viewer falls back to the XML. |
| Page HTML contains well-formed `ac:structured-macro` | Says nothing. The server renders macro markup whether or not it resolves. |

## 🗄️ Storage format

The same instance uses **two different embed forms**, sometimes on one page. A
parser that only looks for `img` silently misses half the diagrams.

| Form | Typical source |
| --- | --- |
| `<p><img src="/download/attachments/{pageId}/{stem}.png" …></p>` | scripts, migrations |
| `<ac:image ac:alt="{stem}.png"><ri:attachment ri:filename="{stem}.png" /></ac:image>` | the draw.io app's own output |

Replaced by:

```html
<ac:structured-macro ac:macro-id="{uuid}" ac:name="drawio" ac:schema-version="1">
  <ac:parameter ac:name="zoom">1</ac:parameter>
  <ac:parameter ac:name="simple">0</ac:parameter>
  <ac:parameter ac:name="inComment">0</ac:parameter>
  <ac:parameter ac:name="pageId">{pageId}</ac:parameter>
  <ac:parameter ac:name="lbox">1</ac:parameter>
  <ac:parameter ac:name="diagramDisplayName">{stem}</ac:parameter>
  <ac:parameter ac:name="contentVer">1</ac:parameter>
  <ac:parameter ac:name="revision">1</ac:parameter>
  <ac:parameter ac:name="diagramName">{stem}.drawio</ac:parameter>
  <ac:parameter ac:name="pCenter">0</ac:parameter>
  <ac:parameter ac:name="width">1150</ac:parameter>
  <ac:parameter ac:name="links"></ac:parameter>
  <ac:parameter ac:name="tbstyle"></ac:parameter>
  <ac:parameter ac:name="height">{scaledHeight}</ac:parameter>
</ac:structured-macro>
```

`diagramName` is the attachment title; the `.drawio` suffix is optional.
`baseUrl` and `custContentId` appear in macros migrated from Atlassian Cloud and
are not required. Display size is scaled from the diagram's own
`pageWidth`/`pageHeight` to keep the aspect ratio exact.

Full parameter notes and the storage-XML pitfalls — duplicate attributes, version
incrementing, UTF-8 — are in
[references/storage-format.md](references/storage-format.md).

## 🧪 Commands

| Command | What it does |
| --- | --- |
| `check --page ID` | Every diagram on the page with its media type and `crud` status. Read-only. |
| `upload --page ID --dir D` | Deletes any same-named attachment, re-uploads with the required media type, verifies `crud`. |
| `embed --page ID --dir D` | Replaces PNG embeds with macros, removes redundant download links. Refuses to run if any diagram does not resolve. |
| `convert --page ID --dir D` | `upload` then `embed`, in that order, for every diagram found in the body. |
| `verify --page ID` | Opens a real browser, counts rendered SVGs, checks every `crud` response and looks for failure markers. Needs playwright. |

Useful flags: `--stems` to limit the scope, `--expect N` to assert a diagram
count, `--shot FILE.png` for a full-page screenshot, `--force` to embed anyway.

## 🆚 Three ways to put a diagram on a Confluence page

| | **drawio macro** | PNG preview + download link | Attached `.drawio` only |
| --- | --- | --- | --- |
| **Renders in the page** | ✅ native SVG | ✅ image | ❌ |
| **Editable in the browser** | ✅ double click | ❌ | ❌ |
| **Needs a build step** | ❌ | ✅ | ✅ |
| **Survives a Confluence migration** | ⚠️ depends on the app | ✅ | ✅ |
| **Fails silently** | ⚠️ yes — see above | ✅ no | ✅ no |

Prefer the macro. Keep the PNG as a fallback attachment rather than in the body.

## 🎯 When to use (and when not)

**Good fit:**

- Architecture, data-flow, and process diagrams that readers should be able to
  correct themselves, without asking you for a new build
- Migrating pages that currently show PNG previews
- Auditing an instance where *some* diagrams work and others do not — the
  red-herring table above usually explains the split

**Reach for something else when:**

- **You do not have write access to the Confluence space** — a PNG plus the
  `.drawio` attachment is the fallback
- **The draw.io app is not installed on the instance** — the macro has nothing to
  resolve the diagram; use PNGs
- **The diagram must render on a Confluence export to PDF/Word** — verify the
  macro survives that pipeline first
- **You are authoring the XML** — that is [drawio-skill](https://github.com/Agents365-ai/drawio-skill)'s job, not this one

## 🔄 How it works

```text
check (read-only audit)
   └─> upload   delete same-named attachment → POST with the mxfile media type → verify crud = 200
        └─> embed   detect both embed forms → swap in the macro → drop download links → PUT body
             └─> verify   open a real browser → count rendered SVGs → assert every crud call
```

Each stage is separately runnable, and `convert` simply chains them. The ordering
matters: upload before embed, so the page never contains a macro pointing at a
missing attachment.

## 🔗 Related Skills

| Skill | Best for |
| --- | --- |
| [drawio-skill](https://github.com/Agents365-ai/drawio-skill) | Authoring the `.drawio` XML, importers, layouts, exports — run this first, then publish with this one |
| [jgraph/drawio-desktop](https://github.com/jgraph/drawio-desktop) | The draw.io desktop app itself, used for CLI export |

## 👤 Author

**Paul771**

- GitHub: <https://github.com/Paul771>

## 📄 License

[MIT](LICENSE)
