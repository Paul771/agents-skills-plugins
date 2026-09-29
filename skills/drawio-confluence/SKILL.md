---
name: drawio-confluence
description: Publish and troubleshoot editable draw.io diagrams embedded in Confluence via the native `drawio` macro, so diagrams render and stay editable inline. Use when Confluence shows "Diagram attachment access error", a 404/empty diagram frame, or "Ошибка: 404"; when converting PNG previews or Mermaid/ASCII blocks into inline draw.io on a Confluence page; when uploading `.drawio` attachments so the draw.io app can resolve them; when migrating Confluence between instances or from Atlassian Cloud; or when auditing which diagrams on a page actually resolve. Not for authoring draw.io XML itself — use the drawio-skill for that.
---

# Draw.io → Confluence

Embed `.drawio` files in Confluence as **live, inline-editable** diagrams (the
`drawio` macro), not as PNG previews. This skill covers the Confluence side
only: attachments, storage format, macro parameters, and verification. Author
the XML with the `drawio-skill`.

## The one fact that decides everything

`GET /rest/drawio/1.0/diagram/crud/{name}/{pageId}` resolves a diagram by
attachment **name and media type**. The attachment must be
`application/vnd.jgraph.mxfile`. Any other type yields `404` and the macro
shows an access error, while the page still returns HTTP 200 and the attachment
is visibly present. So "the file is attached" proves nothing — the media type
is the discriminator.

`publish.py upload` sets it correctly by putting the type in the
`Content-Type` of the multipart part. The `X-Atlassian-Override` header is
**ignored** by Confluence; do not rely on it.

## Workflow

```bash
export CONFLUENCE_BASE_URL="https://confluence.example.internal"
export CONFLUENCE_PAT="<bearer token>"

# 1. audit: which diagrams on this page resolve, and with what media type
python3 scripts/publish.py check   --page 3059024222

# 2. upload .drawio files with the required media type
python3 scripts/publish.py upload  --page 3059024222 --dir ./diagrams --stems 01-x 02-y

# 3. replace PNG previews with drawio macros
python3 scripts/publish.py embed   --page 3059024222

# 2+3 in one pass, for every diagram found in the page body
python3 scripts/publish.py convert --page 3059024222 --dir ./diagrams

# 4. prove it in a real browser (needs playwright)
python3 scripts/publish.py verify  --page 3059024222
```

`convert` uploads first, confirms each `crud` call returns 200, and only then
rewrites the body — so a page never points a macro at a missing attachment.

## Rules that prevent the common failures

1. **Never trust server-rendered HTML as proof.** A page with a broken macro
   still returns 200 with well-formed macro markup. Confirm by counting
   rendered SVG nodes in a browser, or by calling `crud` directly. Skipping
   this is the single most common way to ship a silently broken page.
2. **Re-uploading requires delete-then-POST.** A duplicate attachment name
   returns `400`, and `PUT` on an attachment returns `405`. Create only via
   `POST /rest/api/content/{pageId}/child/attachment`; the v2 endpoint
   `/api/v2/pages/{pageId}/attachments` returns `404`.
3. **Send `X-Atlassian-Token: no-check` on every attachment upload**, otherwise
   Confluence answers `403 XSRF check failed`.
4. **Expect two different embed forms in storage format.** Some pages use
   `<p><img src="/download/attachments/…png"></p>`, others
   `<ac:image ac:alt="…png"><ri:attachment ri:filename="…png"/></ac:image>`.
   A parser that only looks for `img` silently misses half the diagrams.
5. **When editing storage XML, rewrite the whole element.** Adding an attribute
   without removing the old one produces a duplicate attribute, the body stops
   parsing, and `PUT` returns `400` with a misleading message.
6. **Take display size from the diagram's own `pageWidth`/`pageHeight`,**
   scaled to ~1150 px wide, so the aspect ratio is exact.
7. **Handle non-ASCII content in UTF-8 end to end.** PowerShell `Get-Content`
   mangles Cyrillic; use the provided script rather than shell string
   surgery on Confluence storage format.
8. **`403` on `/rest/drawio/1.0/license/status` is a red herring.** It also
   occurs on pages whose diagrams work perfectly, including inline editing
   and saving. Do not treat it as the cause of a broken diagram, and do not
   report it as a blocker.

## Editing in place

`diagramName` is the attachment title; the `.drawio` extension is optional
(both resolve). `baseUrl` and `custContentId` appear in macros migrated from
Atlassian Cloud and are not required. Once a diagram is embedded, opening it by
double click edits the attachment in place, so the macro keeps working after
the user changes it.

## Reference

- `references/storage-format.md` — the two embed forms, a working macro, the
  minimal parameter set, and the storage-XML pitfalls.
- `references/troubleshooting.md` — symptom → cause → fix, including the
  misleading signals.
