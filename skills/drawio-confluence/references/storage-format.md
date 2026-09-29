# Confluence storage format for draw.io

## The two embed forms

The draw.io app and hand-written HTML produce different storage markup. Both
occur on the same instance, sometimes on the same page. Always detect both.

**Form A — plain image (typical of scripts and migrations):**

```html
<p><img src="/download/attachments/3059024222/01-integration-architecture.png"
        alt="01-integration-architecture" width="1150"
        data-macro-attachment="01-integration-architecture.png" /></p>
```

**Form B — attachment element (typical of the draw.io app's own output):**

```html
<ac:image ac:alt="01-integration-architecture.png">
  <ri:attachment ri:filename="01-integration-architecture.png" />
</ac:image>
```

Detection regex that catches both, returning the stem from either alternative:

```python
EMBED = re.compile(
    r'<p>\s*<img[^>]*?/([\w.-]+)\.png"[^>]*?>\s*</p>'
    r'|<ac:image[^>]*?ac:alt="([\w.-]+)\.png"[^>]*?>.*?</ac:image>',
    re.S,
)
stem = match.group(1) or match.group(2)
```

A search for `<img` alone finds only Form A. On one real page, 10 of 11
diagrams were Form B and were invisible to an `img`-only parser.

## Redundant download links

Both forms ship with a companion link paragraph. Once the macro is in place the
diagram opens by double click, so these are noise and can be removed.

Form A companion:

```html
<p><a href="/download/attachments/{pageId}/{stem}.drawio">Скачать {stem}.drawio</a>
   · <a href="…/{stem}.png">PNG</a>
   · <a href="https://app.diagrams.net/?title={stem}.drawio">открыть в diagrams.net</a></p>
```

Form B companion:

```html
<p><ac:link><ri:attachment ri:filename="{stem}.drawio" />
  <ac:plain-text-link-body><![CDATA[Скачать {stem}.drawio]]></ac:plain-text-link-body>
</ac:link></p>
```

Keep the `.png` attachments on the page as a fallback. Only stop referencing
them from the body.

## A working macro

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

### Parameter notes

| Parameter | Required | Notes |
|---|---|---|
| `diagramName` | yes | The attachment title. `.drawio` suffix optional; both resolve. |
| `pageId` | yes | Must be the page the attachment lives on — not a parent page. |
| `width`, `height` | yes | Scale `pageWidth`/`pageHeight` from the diagram, keep the ratio. |
| `revision`, `contentVer` | yes | Start at `1`. |
| `diagramDisplayName` | yes | Caption in the draw.io UI. |
| `zoom`, `simple`, `pCenter`, `lbox`, `inComment`, `links`, `tbstyle` | no | View options; safe defaults shown above. |
| `baseUrl`, `custContentId` | no | Relics of Atlassian Cloud migration. Not required. |

## Sizing

Read the geometry from the diagram itself rather than a side manifest:

```python
m = re.search(r'pageWidth="(\d+)"\s+pageHeight="(\d+)"', xml_text)
disp_w = 1150
disp_h = round(disp_w * int(m.group(2)) / int(m.group(1)))
```

Rendering at native size overflows the content column. 1150 px fits the
default Confluence layout.

## Storage XML pitfalls

- **Duplicate attributes.** Adding an attribute without removing the existing
  one (e.g. two `data-macro-attachment`) makes the body unparseable; `PUT`
  returns `400` with a message that does not mention the real cause. Always
  rewrite the entire element.
- **Increment `version.number`** on every `PUT`, or the write is rejected.
- **Write with `ensure_ascii=False` and an explicit UTF-8 charset**, or Cyrillic
  and other non-ASCII prose in the page turns into mojibake.
- **`<p>` may be implicitly closed** in stored output. Do not assume the body
  is well-formed XHTML; match loosely and re-serialize only what you changed.

## Updating a page safely

1. `GET /rest/api/content/{id}?expand=body.storage,version`
2. transform the body in memory
3. `PUT /rest/api/content/{id}` with `version.number + 1`
4. re-`GET` and diff the result to confirm nothing unrelated was dropped
