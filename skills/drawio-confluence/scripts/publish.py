#!/usr/bin/env python3
"""
Publish .drawio diagrams into Confluence as live, inline-editable drawio macros.

The decisive detail: Confluence's draw.io app resolves a diagram by attachment
name AND media type. The media type must be application/vnd.jgraph.mxfile.
Anything else gives a 404 and an "attachment access error" frame, while the
page itself still returns HTTP 200.

Stdlib only, except `verify`, which needs playwright.

    export CONFLUENCE_BASE_URL="https://confluence.example.internal"
    export CONFLUENCE_PAT="<bearer token>"

    publish.py check   --page 3059024222
    publish.py upload  --page 3059024222 --dir ./diagrams --stems 01-a 02-b
    publish.py embed   --page 3059024222
    publish.py convert --page 3059024222 --dir ./diagrams
    publish.py verify  --page 3059024222
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MX = "application/vnd.jgraph.mxfile"
DISP_W = 1150
PAT_ENV = (
    "CONFLUENCE_PAT",
    "CONFLUENCE_TOKEN",
    "CONFLUENCE_API_TOKEN",
    "CONFLUENCE_BEARER_TOKEN",
)

# <p><img src=".../{stem}.png" .../></p>   OR   <ac:image ac:alt="{stem}.png">…</ac:image>
EMBED = re.compile(
    r'<p>\s*<img[^>]*?/([\w.-]+)\.png"[^>]*?>\s*</p>'
    r'|<ac:image[^>]*?ac:alt="([\w.-]+)\.png"[^>]*?>.*?</ac:image>',
    re.S,
)
LINK_A = re.compile(r'<p><a href="[^"]*/([\w.-]+)\.drawio">[^<]*</a>.*?</p>', re.S)
LINK_B = re.compile(
    r'<p><ac:link>\s*<ri:attachment ri:filename="([\w.-]+)\.drawio"\s*/>.*?</ac:link></p>',
    re.S,
)
# already-embedded macros, so an audit works on converted pages too
MACRO = re.compile(r'<ac:parameter ac:name="diagramName">([^<]+)</ac:parameter>')


# --------------------------------------------------------------------------- io

class Conf:
    def __init__(self, base, pat):
        self.base = base.rstrip("/")
        self.auth = {"Authorization": "Bearer " + pat, "Accept": "application/json"}

    def __call__(self, method, path, data=None, headers=None):
        h = dict(self.auth)
        if headers:
            h.update(headers)
        body = None
        if data is not None:
            if isinstance(data, bytes):
                body = data
            else:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                h.setdefault("Content-Type", "application/json; charset=utf-8")
        r = urllib.request.Request(self.base + path, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def page(self, pid):
        # space must be expanded: put_page echoes it back and Confluence
        # rejects the request body when it is null
        st, t = self("GET", "/rest/api/content/%s?expand=body.storage,version,space" % pid)
        if st != 200:
            raise SystemExit("cannot read page %s -> HTTP %s" % (pid, st))
        return json.loads(t)

    def attachments(self, pid):
        st, t = self("GET", "/rest/api/content/%s/child/attachment?limit=200" % pid)
        if st != 200:
            return {}
        return {a["title"]: a for a in json.loads(t)["results"]}

    def crud(self, stem, pid, revision=1):
        return self(
            "GET",
            "/rest/drawio/1.0/diagram/crud/%s.drawio/%s?revision=%d"
            % (urllib.parse.quote(stem), pid, revision),
        )

    def put_page(self, pid, page, body):
        if not page.get("space"):
            raise SystemExit("page %s has no space; re-read with expand=space" % pid)
        return self(
            "PUT",
            "/rest/api/content/%s" % pid,
            {
                "id": pid,
                "type": "page",
                "title": page["title"],
                "space": {"key": page["space"]["key"]},
                "version": {"number": page["version"]["number"] + 1},
                "body": {"storage": {"value": body, "representation": "storage"}},
            },
        )

    def upload_mxfile(self, pid, filename, xml):
        """Delete any same-named attachment, then POST with the required media type.

        The media type must sit in the multipart part's Content-Type.
        X-Atlassian-Override is ignored by Confluence.
        """
        for a in self.attachments(pid).values():
            if a["title"] == filename:
                self("DELETE", "/rest/api/content/%s" % a["id"])
        b = "----b" + uuid.uuid4().hex
        payload = (
            ("--" + b + "\r\n").encode()
            + (
                'Content-Disposition: form-data; name="file"; filename="%s"\r\n'
                "Content-Type: %s\r\n\r\n" % (filename, MX)
            ).encode()
            + xml
            + ("\r\n--" + b + "--\r\n").encode()
        )
        st, t = self(
            "POST",
            "/rest/api/content/%s/child/attachment" % pid,
            data=payload,
            headers={
                "Content-Type": "multipart/form-data; boundary=" + b,
                "X-Atlassian-Token": "no-check",
            },
        )
        if st not in (200, 201):
            return st, "?"
        a = (json.loads(t).get("results") or [json.loads(t)])[0]
        return st, a.get("metadata", {}).get("mediaType", "?")


# ---------------------------------------------------------------------- helpers

def stems_in(body):
    """Diagram stems referenced by a PNG preview embed."""
    return [m.group(1) or m.group(2) for m in EMBED.finditer(body)]


def stems_in_macros(body):
    """Diagram stems already embedded as native drawio macros."""
    out = []
    for m in MACRO.finditer(body):
        s = m.group(1).strip()
        if s.endswith(".drawio"):
            s = s[: -len(".drawio")]
        if s not in out:
            out.append(s)
    return out


def scaled_height(xml_text, disp_w=DISP_W):
    m = re.search(r'pageWidth="(\d+)"\s+pageHeight="(\d+)"', xml_text)
    if not m:
        return round(disp_w * 0.66)
    return round(disp_w * int(m.group(2)) / int(m.group(1)))


def macro(pid, stem, height):
    return (
        '<ac:structured-macro ac:macro-id="%s" ac:name="drawio" ac:schema-version="1">'
        '<ac:parameter ac:name="zoom">1</ac:parameter>'
        '<ac:parameter ac:name="simple">0</ac:parameter>'
        '<ac:parameter ac:name="inComment">0</ac:parameter>'
        '<ac:parameter ac:name="pageId">%s</ac:parameter>'
        '<ac:parameter ac:name="lbox">1</ac:parameter>'
        '<ac:parameter ac:name="diagramDisplayName">%s</ac:parameter>'
        '<ac:parameter ac:name="contentVer">1</ac:parameter>'
        '<ac:parameter ac:name="revision">1</ac:parameter>'
        '<ac:parameter ac:name="diagramName">%s.drawio</ac:parameter>'
        '<ac:parameter ac:name="pCenter">0</ac:parameter>'
        '<ac:parameter ac:name="width">%d</ac:parameter>'
        '<ac:parameter ac:name="links"></ac:parameter>'
        '<ac:parameter ac:name="tbstyle"></ac:parameter>'
        '<ac:parameter ac:name="height">%d</ac:parameter>'
        "</ac:structured-macro>" % (uuid.uuid4(), pid, stem, stem, DISP_W, height)
    )


def resolve_dir(stems, directory):
    out = []
    for s in stems:
        p = os.path.join(directory, s + ".drawio")
        if not os.path.exists(p):
            raise SystemExit("missing local file: %s" % p)
        out.append((s, p))
    return out


# ------------------------------------------------------------------- subcommands

def cmd_check(c, args):
    page = c.page(args.page)
    body = page["body"]["storage"]["value"]
    atts = c.attachments(args.page)
    embedded, macros = stems_in(body), stems_in_macros(body)
    stems = embedded + [s for s in macros if s not in embedded]
    stems += [
        t[: -len(".drawio")] for t in sorted(atts)
        if t.endswith(".drawio") and t[: -len(".drawio")] not in stems
    ]
    print("page %s  v%s" % (args.page, page["version"]["number"]))
    print("  %d PNG embed(s), %d macro(s), %d attachment(s)"
          % (len(embedded), len(macros), len(atts)))
    if not stems:
        print("  no diagrams found on this page")
        return 0
    bad = 0
    for s in stems:
        a = atts.get(s + ".drawio")
        mt = a["metadata"]["mediaType"] if a else "MISSING"
        st, _ = c.crud(s, args.page)
        where = "macro" if s in macros else ("embed" if s in embedded else "attachment")
        ok = st == 200 and mt == MX
        bad += 0 if ok else 1
        print("  %-40s %-10s mediaType=%-34s crud=%s %s"
              % (s, where, mt, st, "OK" if ok else "<-- FIX"))
    print("checked %d, need attention: %d" % (len(stems), bad))
    return 0 if not bad else 1


def cmd_upload(c, args):
    stems = args.stems or sorted(
        f[: -len(".drawio")] for f in os.listdir(args.dir) if f.endswith(".drawio")
    )
    fails = 0
    for stem, path in resolve_dir(stems, args.dir):
        st, mt = c.upload_mxfile(args.page, stem + ".drawio", open(path, "rb").read())
        cst, _ = c.crud(stem, args.page)
        good = st in (200, 201) and mt == MX and cst == 200
        fails += 0 if good else 1
        print("  %-42s upload=%s mediaType=%-34s crud=%s %s" % (stem, st, mt, cst, "" if good else "<-- FAIL"))
        time.sleep(0.3)
    return 1 if fails else 0


def cmd_embed(c, args):
    page = c.page(args.page)
    body = page["body"]["storage"]["value"]
    stems = stems_in(body)
    if args.stems:
        stems = [s for s in stems if s in set(args.stems)]
    if not stems:
        print("no PNG embeds found; nothing to convert")
        return 0

    atts = c.attachments(args.page)
    done, skipped = [], []
    for s in stems:
        a = atts.get(s + ".drawio")
        st, _ = c.crud(s, args.page)
        if not a or a["metadata"]["mediaType"] != MX or st != 200:
            skipped.append(s)

    if skipped and not args.force:
        print("refusing to embed, these do not resolve: %s" % ", ".join(skipped))
        print("run `upload` first, or pass --force to embed anyway")
        return 1

    heights = {}
    for s in stems:
        if s in skipped:
            heights[s] = round(DISP_W * 0.66)
            continue
        p = args.dir and os.path.join(args.dir, s + ".drawio")
        text = open(p, encoding="utf-8", errors="replace").read() if p and os.path.exists(p) else ""
        heights[s] = scaled_height(text)

    def sub(m):
        s = m.group(1) or m.group(2)
        if s not in heights:
            return m.group(0)
        done.append(s)
        return macro(args.page, s, heights[s])

    new = EMBED.sub(sub, body)
    new, na = LINK_A.subn("", new)
    new, nb = LINK_B.subn("", new)
    print("embeds converted: %d | download links removed: %d + %d" % (len(done), na, nb))
    st, t = c.put_page(args.page, page, new)
    print("page put -> %s (v%s -> v%s)" % (st, page["version"]["number"], page["version"]["number"] + 1))
    if st not in (200, 201):
        print(t[:300])
        return 1
    return 0


def cmd_convert(c, args):
    page = c.page(args.page)
    stems = stems_in(page["body"]["storage"]["value"])
    if args.stems:
        stems = [s for s in stems if s in set(args.stems)]
    if not stems:
        print("no PNG embeds found; nothing to convert")
        return 0
    print("diagrams in body: %d" % len(stems))
    rc = cmd_upload(c, argparse.Namespace(page=args.page, dir=args.dir, stems=stems))
    if rc and not args.force:
        print("upload phase had failures; stopping before touching the body")
        return 1
    return cmd_embed(c, args)


def cmd_verify(c, args):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("verify needs playwright:  pip install playwright && playwright install chrome")
        return 2
    base = c.base
    url = "%s/spaces/%s/pages/%s" % (base, args.space, args.page) if args.space else \
          "%s/pages/viewpage.action?pageId=%s" % (base, args.page)
    hits = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel=args.channel)
        ctx = b.new_context(
            viewport={"width": 1600, "height": 1100},
            extra_http_headers={"Authorization": "Bearer " + c.auth["Authorization"].split()[1]},
        )
        pg = ctx.new_page()
        pg.on(
            "response",
            lambda r: hits.append((r.status, r.url))
            if "/rest/drawio/1.0/diagram/crud/" in r.url
            else None,
        )
        pg.goto(url, wait_until="networkidle", timeout=120000)
        pg.wait_for_timeout(6000)
        for _ in range(12):  # lazy viewers only initialise once scrolled into view
            pg.mouse.wheel(0, 3000)
            pg.wait_for_timeout(700)
        pg.wait_for_timeout(3000)
        info = pg.evaluate(
            """() => {
          const boxes = Array.from(document.querySelectorAll('.conf-macro.output-block'))
            .filter(e => e.querySelector('svg'));
          const svgs = Array.from(document.querySelectorAll('svg'))
            .filter(s => s.querySelectorAll('*').length > 20);
          const imgs = Array.from(document.querySelectorAll('img'))
            .map(i => ({src: i.currentSrc || i.src, w: i.naturalWidth}))
            .filter(i => i.w > 0 && /attachments\\/\\d+\\/.*\\.png/.test(i.src));
          return {boxes: boxes.length, svgs: svgs.length, png: imgs.length,
                  text: document.body.innerText || ''};
        }"""
        )
        if args.shot:
            pg.screenshot(path=args.shot, full_page=True)
        b.close()
    # match specific failure markers, never the bare word "error":
    # pages legitimately discuss error handling
    bad = re.findall(
        r"(attachment access|Ошибка:\s*404|Error:\s*404|diagram (?:not found|error))",
        info["text"],
        re.I,
    )
    c200 = sum(1 for s, _ in hits if s == 200)
    c404 = sum(1 for s, _ in hits if s == 404)
    other = [(s, u) for s, u in hits if s not in (200, 404)]
    expect = args.expect if args.expect is not None else c200
    ok = not bad and not other and c404 == 0 and info["boxes"] == expect and info["svgs"] == expect
    print(
        "boxes=%d svgs=%d crud200=%d 404=%d other=%d strayPNG=%d expect=%d -> %s"
        % (info["boxes"], info["svgs"], c200, c404, len(other), info["png"], expect,
           "OK" if ok else "PROBLEM")
    )
    if bad:
        print("  failure markers:", set(bad))
    if other:
        print("  unexpected responses:", other[:3])
    if args.shot:
        print("  screenshot:", args.shot)
    return 0 if ok else 1


# ------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "upload", "embed", "convert", "verify"])
    ap.add_argument("--page", required=True, help="Confluence page id")
    ap.add_argument("--base-url", default=os.environ.get("CONFLUENCE_BASE_URL"))
    ap.add_argument("--pat", default=None)
    ap.add_argument("--dir", default=".", help="directory holding <stem>.drawio files")
    ap.add_argument("--stems", nargs="*", help="limit to these diagram stems")
    ap.add_argument("--space", help="space key, for a tidy verify URL")
    ap.add_argument("--expect", type=int, help="expected diagram count for verify")
    ap.add_argument("--shot", help="save a full-page screenshot here")
    ap.add_argument("--channel", default="chrome", help="playwright browser channel")
    ap.add_argument("--force", action="store_true", help="embed even if some diagrams do not resolve")
    args = ap.parse_args()

    pat = args.pat or next((os.environ[e] for e in PAT_ENV if os.environ.get(e)), None)
    if not args.base_url or not pat:
        raise SystemExit(
            "set CONFLUENCE_BASE_URL and one of: %s  (or pass --base-url/--pat)" % ", ".join(PAT_ENV)
        )
    c = Conf(args.base_url, pat)
    return {
        "check": cmd_check, "upload": cmd_upload, "embed": cmd_embed,
        "convert": cmd_convert, "verify": cmd_verify,
    }[args.command](c, args)


if __name__ == "__main__":
    sys.exit(main())
