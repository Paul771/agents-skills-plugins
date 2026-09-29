# Troubleshooting draw.io in Confluence

## Symptom table

| Symptom | Real cause | Fix |
|---|---|---|
| "Diagram attachment access error" frame | Attachment media type is not `application/vnd.jgraph.mxfile` | Re-upload with the type in the multipart part's `Content-Type` |
| "Ошибка: 404" / empty frame, `crud` returns 404 | Same as above, or the attachment name does not match `diagramName` | Check both; `crud` is the oracle |
| Nothing renders, no visible error | `diagramName` points at an attachment on a different page | Attach the file to the page that holds the macro |
| `403 XSRF check failed` on upload | Missing XSRF exemption header | Send `X-Atlassian-Token: no-check` |
| `400` on attachment upload | An attachment with that name already exists | Delete the old one first, then `POST` |
| `405` on attachment upload | Used `PUT` | Create with `POST` only |
| `404` on `/api/v2/pages/{id}/attachments` | v2 endpoint unsupported on this instance | Use `/rest/api/content/{id}/child/attachment` |
| `400` on page `PUT`, message about XML | Duplicate attribute in the body | Rewrite the whole element instead of patching it |
| `400` on page `PUT` after upload succeeded | Body contains a macro for a stem that was skipped | Confirm every `crud` call returns 200 before writing |
| Page looks right in HTML source, empty in browser | Server renders macro markup regardless of validity | Verify in a real browser, not via the API |
| Diagrams render, editing is broken | Genuinely broken — but see the red herrings below | Check `crud`, then the app's own scripts |

## Red herrings

**`403` on `/rest/drawio/1.0/license/status` is not a fault indicator.** It
returns 403 on instances where every diagram renders, opens in the inline
editor, and saves correctly. Verified against a page authored years earlier and
edited daily. Do not use it to explain a broken diagram, and do not report it
as a blocker to the user.

**`POST`/`PUT`/`DELETE` on the `crud` endpoint returning 409/400/405 means
nothing.** Diagrams are stored as attachments, not in a separate CRUD store.
The read endpoint is the only one that matters, and it works fine.

**A `404` on `…/diagram/crud/{name}.png` is expected**, not a fault. That is
the app probing for a cached preview; the viewer falls back to rendering the
XML it already has.

## Proving it works

Server-side checks, cheapest first:

```bash
curl -H "Authorization: Bearer $PAT" \
  "$BASE/rest/drawio/1.0/diagram/crud/01-integration-architecture.drawio/3059024222?revision=1"
```

`200` means the diagram resolves. Repeat for every diagram on the page; a page
with 8 diagrams needs 8 passing calls.

Then confirm in a browser, because this is the step that catches what the API
cannot:

- count rendered diagram containers — should equal the number of macros
- count rich SVGs (>20 child nodes) — should equal the number of diagrams
- assert zero `crud` responses with a non-200 status
- assert no `<img>` remains that points at a `.png` in `/download/attachments`
- scroll the whole page so lazily-initialised viewers get a chance to render
- check the body text for "attachment access", "Ошибка: 404", "Error: 404"

When matching error text, do not match the bare word "error": pages about error
handling legitimately contain it, and the check will fire on healthy content.

## Diagnostic sequence that avoids guessing

1. `GET` the page body. Does the macro exist? Is `diagramName` spelled the same
   as the attachment title?
2. `GET` the attachment list. Is the file there, and what is its media type?
3. `GET` `crud`. 200 or 404 decides the issue: resolution versus absence.
4. Only if all three are healthy, open a real browser and look.

Skipping straight to a browser is also fine and often faster — but do not skip
it, because that is precisely where a "successful" API response turns out to
be a blank page.

## Media type is set from the part, not the header

```python
part = (
    'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
    "Content-Type: application/vnd.jgraph.mxfile\r\n\r\n" % filename
) + xml_bytes
```

`X-Atlassian-Override: media-type=…` is accepted and ignored. Verified by
uploading with the header and re-reading the stored media type, which came back
unchanged.
