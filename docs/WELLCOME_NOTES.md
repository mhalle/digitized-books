# Wellcome Collection — IIIF & API Research Notes

Field notes for the `iiif-utils` Wellcome adapter. All claims below were
verified against the live API on 2026-05-10 unless noted otherwise.

Sources cited inline as bare URLs.

---

## 1. Catalogue API

### Base URL and version
- Base: `https://api.wellcomecollection.org/catalogue/v2`
- Works endpoint: `https://api.wellcomecollection.org/catalogue/v2/works`
- Single work: `.../works/{workId}` (e.g. `.../works/r32p4n5s`)
- Source: https://developers.wellcomecollection.org/api/catalogue
- Open-source code: https://github.com/wellcomecollection/catalogue-api

### Filter parameters (verified live)
The `/works` endpoint accepts:

| Filter | Notes |
|---|---|
| `query` | Full-text query string |
| `workType` | Single-letter format codes: `a`=books, `d`=journals, `h`=archives, etc. |
| `type` | Work / Collection / Series |
| `languages` | ISO codes, comma-sep |
| `genres` / `genres.label` | |
| `subjects` / `subjects.label` | |
| `contributors.agent` / `contributors.agent.label` | |
| `identifiers` | Lookup by Sierra/CALM/etc. ID values |
| `items` / `items.identifiers` | |
| `partOf` / `partOf.title` | Series/parent filtering |
| `availabilities` | `online`, `open-shelves`, `closed-stores` |
| `items.locations.accessConditions.status` | `open`, `restricted`, `safeguarded`, `licensed-resources`, `permission-required` |
| `items.locations.license` | `pdm`, `cc-by`, `cc-by-nc`, `inc`, ... |
| `items.locations.locationType` | Most importantly `iiif-presentation` and `iiif-image` |
| `production.dates.from` / `production.dates.to` | Year strings, e.g. `1800`, `1900` |
| `items.locations.createdDate.from` / `.to` | When the digital location was created |

Confirmed via: https://developers.wellcomecollection.org/api/catalogue
and the live response of
`https://api.wellcomecollection.org/catalogue/v2/works?include=items,identifiers,...`.

### Pagination, sort, includes
- `page` (≥1, default 1), `pageSize` (1–100, default 10).
- `nextPage` URL is included in result lists when more pages exist.
- Sort: only `sort=production.dates` with `sortOrder=asc|desc`. There is no
  generic relevance sort parameter — relevance is the default for `query`.
- `include` (comma-separated): `identifiers`, `items`, `holdings`,
  `subjects`, `genres`, `contributors`, `production`, `languages`, `notes`,
  `images`, `succeededBy`, `precededBy`, `partOf`, `parts`. **By default
  most arrays come back empty** — you almost always need
  `include=items,identifiers,...` to do anything useful.

### Authentication / API keys
**None.** No sign-up, no API key, no OAuth. The catalogue, IIIF, and Content
APIs are all public anonymous HTTP. Confirmed by the developer portal and by
unauthenticated `curl` returning 200 in our tests.
Source: https://developers.wellcomecollection.org/

### Rate limits and User-Agent
No documented rate limits. No published User-Agent requirement. In our
tests:

- No `X-RateLimit-*` or `Retry-After` headers ever appear on the catalogue
  API or on the IIIF host.
- The IIIF endpoints sit behind CloudFront (`x-cache: Hit from cloudfront`)
  and serve repeat requests from edge cache, so a polite client will rarely
  trip throttling.
- The `/presentation/collections/...` aggregator endpoint **does** have
  a soft cap. Hitting it returned `503 Temporarily unavailable / "Dynamic
  collections are disabled because of too many requests"` — interpret as
  "this endpoint is intentionally throttled, not for bulk crawling."
- Use a descriptive User-Agent (`iiif-utils/x.y (+url)`) as a courtesy;
  Wellcome staff have been reachable at `digital@wellcomecollection.org`
  if anything looks off.

### Work response shape
Top-level fields: `type` ("Work"), `id`, `title`, `alternativeTitles`,
`workType`, `production[]`, `physicalDescription`, `languages[]`,
`genres[]`, `subjects[]`, `identifiers[]`, `items[]`, `availabilities[]`,
`contributors[]`, `partOf[]`, `parts[]`, `notes[]`, `thumbnail`.

The IIIF manifest URL lives in
`items[].locations[]` where `locationType.id == "iiif-presentation"`. The
`url` field on that location is the manifest URL. Single-image (no
manifest) items appear as `locationType.id == "iiif-image"` whose `url`
points at an `info.json`.

Worked example:
```
GET https://api.wellcomecollection.org/catalogue/v2/works/r32p4n5s?include=items,identifiers
{
  "id": "r32p4n5s",
  "title": "Anatomy : proceedings at the National Political Union ...",
  "identifiers": [
    {"identifierType": {"id": "sierra-system-number"}, "value": "b22396147"},
    {"identifierType": {"id": "sierra-identifier"},    "value": "2239614"},
    {"identifierType": {"id": "wellcome-digcode"},     "value": "digrcs"}
  ],
  "items": [{
    "locations": [{
      "url": "https://iiif.wellcomecollection.org/presentation/v2/b22396147",
      "locationType": {"id": "iiif-presentation"},
      "accessConditions": [{"status": {"id": "open"}}],
      "license": {"id": "pdm"}
    }]
  }]
}
```

---

## 2. Identifiers

Wellcome runs **two parallel identifier spaces**:

1. **Catalogue work IDs** — opaque 8-char alphanumeric strings (e.g.
   `r32p4n5s`, `a2yy7fnc`, `bdgsey5f`). Used in catalogue API URLs and on
   `wellcomecollection.org/works/{workId}`. They are **not** b-numbers.
   Pattern roughly `^[a-z0-9]{8}$` but begin with a letter.
2. **Sierra system numbers (b-numbers)** — `b` + 7 digits + 1 check char
   (digit 0–9 or `x`). Pattern `^b\d{7}[\dx]$`. So 9 chars total, not 8 as
   the design doc's `^b\d{8}x?$` regex implies. Examples observed:
   `b22396147`, `b21131569`, `b3187003x`, `b3221456x`, `b33020863`.

A work record may also carry: `calm-record-id` (UUID, archives),
`calm-ref-no`, `calm-altref-no`, `wellcome-digcode` (collection grouping
code like `digrcs`, `digukmhl`, `digmiro`, `diggenetics`), `mets`,
`miro-image-number` (e.g. `M0004078`), `lc-subjects`, `lc-names`,
`label-derived`.

### When does the work ID equal the b-number?
**Effectively never for digitized items.** The work ID is the catalogue
primary key; the b-number is the legacy Sierra ILS identifier and is the
one that drives the IIIF URL. They co-exist on the same record. The IIIF
manifest URL is built from the b-number (or from a non-Sierra Goobi/METS
identifier in some edge cases — but in every record we sampled, the
location URL ended in the b-number).

### Multi-volume works
There is no single canonical strategy. We saw three patterns:

- **Sibling works linked by series.** "The complete works of John Hunter,
  F.R.S" exists as four separate works (`fvf6ps84`, `bdgsey5f`,
  `ue49q8g6`, `xfnts3sb`), each with its own b-number and its own
  manifest. They share `partOf: [{title: "Medical Heritage Library",
  type: "Series", totalParts: 0}]` — the Series object is unhelpful for
  enumeration (totalParts is 0, no id to fetch).
- **Single manifest with many canvases.** Periodicals like "Ophthalmic
  hospital reports" (`b30562910`) ship as one Manifest with 50 canvases
  and `behavior: ["paged"]`.
- **Archive parent → child works.** Archive aggregations
  (`workType=h`) like `a2yy7fnc` ("Lectures, 1965") have populated
  `parts: [{id, title}, ...]` arrays whose children are themselves Works
  with their own manifests.

We did **not** find a working public IIIF Collection manifest URL pattern
for catalogue works. There is a `/presentation/collections/...` namespace
(seen in `partOf` references on manifests, e.g.
`https://iiif.wellcomecollection.org/presentation/collections/contributors/ub6un7bg`)
but it returns 503 "Dynamic collections are disabled because of too many
requests" — so don't rely on it for enumeration. Use the catalogue API to
enumerate siblings instead.

---

## 3. Presentation / Manifest URLs

### URL pattern
- **v3 (default, content-negotiated):** `https://iiif.wellcomecollection.org/presentation/{bnumber}`
  Returns `Content-Type: application/ld+json; profile="http://iiif.io/api/presentation/3/context.json"`.
- **v2 (explicit):** `https://iiif.wellcomecollection.org/presentation/v2/{bnumber}`
  Returns `Content-Type: application/ld+json; profile="http://iiif.io/api/presentation/2/context.json"`.

The catalogue API's `items[].locations[].url` field **currently emits the
v2 form** (`/presentation/v2/{bnumber}`). The same b-number resolves at
both URLs. Treat the catalogue's URL as a hint; rewrite to the
`/presentation/{bnumber}` form to get v3.

Confirmed live: `b22396147`, `b21131569`, `b18035723`, `b30562910`,
`b32858899`, etc.

### Version reality
Both v2 and v3 are served from production. v3 is the modern default.
There is no current plan to retire v2 publicly that we found. If
designing fresh, target v3 — it's where SearchService1 and the auth/2
context land.

### Multi-volume modeling
As above (§2): there is no first-class IIIF Collection that wraps a
multi-volume work. Each volume is a standalone Manifest, addressable by
its own b-number. The relationship is in the catalogue (`parts`,
`partOf`), not the manifest tree.

A v3 manifest does carry a `partOf` array pointing at "virtual"
Collection URLs (subjects, contributors, digcode), e.g.:
```
"partOf": [
  {"id": "https://iiif.wellcomecollection.org/presentation/collections/contributors/ub6un7bg",
   "type": "Collection", "label": "Royal London Ophthalmic Hospital."},
  {"id": "https://iiif.wellcomecollection.org/presentation/collections/subjects/nj9wmncw",
   "type": "Collection", "label": "..."}
]
```
…but as noted, the `/collections/...` endpoint is throttled to the point
of unusable for client crawling. Treat as informational only.

---

## 4. Content Search (full-text)

### Version
**IIIF Content Search API v1**, not v2. The service block is:

```json
"service": [{
  "@id":     "https://iiif.wellcomecollection.org/search/v1/{bnumber}",
  "@type":   "SearchService1",
  "profile": "http://iiif.io/api/search/1/search",
  "service": {
    "@id":     "https://iiif.wellcomecollection.org/search/autocomplete/v1/{bnumber}",
    "@type":   "AutoCompleteService1",
    "profile": "http://iiif.io/api/search/1/autocomplete"
  }
}]
```

The block lives at the top level of the v3 manifest under `service` (note
the `@id`/`@type` keys — Wellcome uses the v1 search vocabulary embedded
in a v3 manifest). The manifest's `@context` array includes
`http://iiif.io/api/search/1/context.json` alongside the presentation v3
context.

### Coverage
Present on every Wellcome book/journal manifest we sampled — including
the **restricted** one (`b32858899`). Search works for restricted items
even when the page images don't.

### Example query/response
```
GET https://iiif.wellcomecollection.org/search/v1/b22396147?q=anatomy
```
Returns an `sc:AnnotationList`:
```json
{
  "@context": "http://iiif.io/api/search/1/context.json",
  "@id": "...?q=anatomy",
  "@type": "sc:AnnotationList",
  "within": { "total": 44 },
  "resources": [{
    "@id": "https://iiif.wellcomecollection.org/annotations/b22396147/b22396147_0003.jp2/h0r403,121,606,64",
    "@type": "oa:Annotation",
    "motivation": "sc:painting",
    "resource": { "@type": "cnt:ContentAsText", "chars": "ANATOMY." },
    "on": "https://iiif.wellcomecollection.org/presentation/b22396147/canvases/b22396147_0003.jp2#xywh=403,121,606,64"
  }, ...]
}
```

The `on` URI carries the canvas ID and the matched bbox in `#xywh=`,
which is everything you need to map a hit back to a `page_numbers` row
plus an `image_service_url` region.

---

## 5. OCR / text source per canvas

### Per-canvas ALTO via `seeAlso`
Each canvas has a `seeAlso` entry pointing at METS-ALTO XML:

```json
"seeAlso": [{
  "id":      "https://api.wellcomecollection.org/text/alto/b22396147/b22396147_0003.jp2",
  "type":    "Dataset",
  "profile": "http://www.loc.gov/standards/alto/v3/alto.xsd",
  "format":  "text/xml",
  "label":   {"none": ["METS-ALTO XML"]}
}]
```

Match on `format == "text/xml"` AND `profile` containing `alto`. Note:

- The `profile` advertises ALTO v3 but the served XML is actually
  **ALTO v2** (`xmlns="http://www.loc.gov/standards/alto/ns-v2#"`).
  Parser must accept either.
- ALTO is generated upstream from ABBYY Recognition Server output by
  intranda's OCR module.
- URL pattern: `https://api.wellcomecollection.org/text/alto/{bnumber}/{bnumber}_NNNN.jp2`
  (the trailing `.jp2` is part of the asset name, not a JPEG2000 file).

### Per-canvas annotation pages
v3 manifests also expose:

```json
"annotations": [{
  "id":   "https://iiif.wellcomecollection.org/annotations/v3/b22396147/b22396147_0003.jp2/line",
  "type": "AnnotationPage",
  "label": {"en": ["Text of page  -"]}
}]
```

This is W3C Web Annotation page of OCR lines — alternative to ALTO if you
want JSON-shaped text with line bboxes mapped onto the canvas.

### Manifest-level full text
A manifest-level `rendering` of `format: "text/plain"` gives the whole
work as plain text:
```
https://api.wellcomecollection.org/text/v1/{bnumber}
```
Present even on restricted manifests (where it is the *only* way to get
the OCR for the document).

### Recommended OCR fallback chain for Wellcome
1. ALTO via canvas `seeAlso` (`format=text/xml`, profile contains `alto`)
   — best for bboxes per word.
2. AnnotationPage via canvas `annotations[]` — same data in W3C form,
   useful if you prefer JSON over XML.
3. Manifest-level plain-text rendering at `/text/v1/{bnumber}` — fastest
   path for a `searchtext` index, no per-canvas walks.
4. Live Content Search v1 — last-resort, online-only.

---

## 6. PDFs and other renderings

Manifest-level `rendering` array on a typical book:

```json
"rendering": [
  {"id": "https://iiif.wellcomecollection.org/pdf/{bnumber}",
   "type": "Text", "format": "application/pdf",
   "label": {"en": ["View as PDF"]}},
  {"id": "https://api.wellcomecollection.org/text/v1/{bnumber}",
   "type": "Text", "format": "text/plain",
   "label": {"en": ["View raw text"]}}
]
```

Observations:

- PDF rendering is **usually but not always** present. Restricted-content
  manifest `b32858899` had no PDF rendering, only the raw-text one. Open
  books reliably ship a PDF.
- We did **not** see manifest-level METS, EPUB, or full-work XML
  renderings on any sample. The METS-ALTO XML lives only at the canvas
  level (per page).
- The PDF URL is direct (`/pdf/{bnumber}`), no auth, no token. Files can
  be hundreds of MB for long works.

---

## 7. Image API

### Version
**Image API v2** is what Wellcome serves today. Every `info.json` we
fetched returns:

```json
"@context": "http://iiif.io/api/image/2/context.json",
"@type":    "iiif:Image",
"profile":  ["http://iiif.io/api/image/2/level2.json", { ... }],
"protocol": "http://iiif.io/api/image"
```

The Image API URL pattern is the standard:
`https://iiif.wellcomecollection.org/image/{asset}/{region}/{size}/{rotation}/{quality}.{format}`

`{asset}` is `{bnumber}_NNNN.jp2` for paged content (e.g.
`b22396147_0003.jp2`) or a Miro identifier (e.g. `M0004078`) for legacy
single-image items.

**Note:** the manifest's `@context` and embedded service blocks declare
`ImageService2` (i.e. Image v2). Despite the developer portal page
labeled "IIIF APIs (v3)" implying v3 across the board, the *Image* API is
still v2. v3 service blocks were not seen in any manifest we sampled.

### info.json shape (open content)
- `protocol`: `http://iiif.io/api/image`
- `profile`: array, level 2 with formats `[jpg, tif, gif, png]`
  (`webp` is **not** in the supports list of the open assets we sampled,
  despite the developer portal listing it)
- Qualities: `bitonal, default, gray, color`
- Tile size: `512×512`, scale factors `[1,2,4,8,16]` (and `32` on larger
  images)
- `sizes`: pre-rendered thumbnail sizes
- Width/height: full source dimensions (often 1600–3200 px on the long
  edge for digitized books)

Example: https://iiif.wellcomecollection.org/image/b22396147_0003.jp2/info.json

### Auth-gated (restricted) images
Restricted assets advertise IIIF Auth in **two places** with mixed
versions:

In the manifest's image service block (per canvas):
```json
"service": [{
  "@id": "https://iiif.wellcomecollection.org/image/b32858899_0001.jp2",
  "@type": "ImageService2",
  "service": [
    { "@id":  "https://iiif.wellcomecollection.org/auth/restrictedlogin",
      "@type": "AuthCookieService1" },
    { "id":   "https://iiif.wellcomecollection.org/auth/v2/probe/b32858899_0001.jp2",
      "type": "AuthProbeService2",
      "service": [{
        "id":   "https://iiif.wellcomecollection.org/auth/v2/access/restrictedlogin",
        "type": "AuthAccessService2"
      }]
    }
  ]
}]
```

Note **both Auth API v1 and v2 are advertised on the same canvas** —
`AuthCookieService1` next to `AuthProbeService2` / `AuthAccessService2`.

The image asset's own `info.json` is more confusing: it returns
`@context: ["http://iiif.io/api/auth/2/context.json", "http://iiif.io/api/image/2/context.json"]`
but **omits the service array entirely** — so a client reading
info.json alone has no way to discover the auth probe URL, only the
indication via the auth context that auth is required. The auth services
must be discovered from the **manifest**, not from `info.json`.

Unauthenticated fetch of a restricted image returns:
```
HTTP/2 401
content-length: 0
```
No body, no JSON, no `WWW-Authenticate` hint. Detect by status code.

Access status values to expect on
`items[].locations[].accessConditions[].status.id`:
- `open` — anonymous fetch works
- `restricted` — login + acceptance of terms required (clinical material)
- `safeguarded` — content warning, login required
- `licensed-resources` — third-party license terms
- `permission-required` — manual request to Wellcome

For v1, `iiif-utils` should treat anything other than `open` as "skip
image download, but still index manifest metadata + Content Search +
plain-text rendering" — these continue to work even when images are
401.

---

## 8. Reference samples

### a) Open-access single-volume book with OCR
- **Work:** `r32p4n5s` — *Anatomy : proceedings at the National Political
  Union, respecting legislative interference in the study of anatomy ...*
  (Barnes, London, 1832)
- **B-number:** `b22396147`
- **Manifest v3:** https://iiif.wellcomecollection.org/presentation/b22396147
- **Manifest v2:** https://iiif.wellcomecollection.org/presentation/v2/b22396147
- **Catalogue:** https://api.wellcomecollection.org/catalogue/v2/works/r32p4n5s?include=items,identifiers
- **What makes it interesting:** small (24 canvases), open, public-domain,
  ALTO + Content Search + PDF rendering all present. Good fixture for end-
  to-end smoke tests.

### b) Multi-volume work (sibling-Works pattern)
- **Series anchor:** "The complete works of John Hunter, F.R.S" — exists
  as four catalogue Works, no parent record:
  - Vol 1: work `fvf6ps84`, b-number `b21131569`
    https://iiif.wellcomecollection.org/presentation/b21131569
  - Vol 2: work `bdgsey5f`, b-number `b21131570`
    https://iiif.wellcomecollection.org/presentation/b21131570
  - Vol 3: work `ue49q8g6`, b-number `b21131582`
    https://iiif.wellcomecollection.org/presentation/b21131582
  - Vol 4: work `xfnts3sb`, b-number `b21131594`
    https://iiif.wellcomecollection.org/presentation/b21131594
- **What makes it interesting:** demonstrates that "multi-volume" on
  Wellcome is a *catalogue-side* relationship, not a IIIF Collection.
  An adapter that wants to enumerate siblings has to query the catalogue,
  not walk a Collection manifest.

Alternative bound-as-one pattern:
- **Periodical (single manifest, many canvases):** `b30562910`
  *Ophthalmic hospital reports and journal of the Royal London Ophthalmic
  Hospital* — 50 canvases, `behavior: ["paged"]`.

### c) Restricted / clinical material
- **Work:** `a22mnm7y` — *Le bilan matériel et l'énergétique des synthèses
  biologiques*
- **B-number:** `b32858899`
- **Manifest v3:** https://iiif.wellcomecollection.org/presentation/b32858899
- **Access status:** `restricted`
- **What makes it interesting:** manifest fetches successfully, all 56
  canvases listed, Content Search v1 service is present, plain-text
  rendering works — but image fetch returns HTTP 401 and the canvases
  advertise `AuthCookieService1` + `AuthProbeService2` +
  `AuthAccessService2`. Use this fixture to exercise the "skip image
  download, keep text indexing" path and the auth-detection code.

---

## 9. Anything else surprising

- **No b-number in the canonical catalogue ID.** The catalogue work ID
  (e.g. `r32p4n5s`) is what `wellcomecollection.org/works/{id}` uses.
  But all IIIF URLs key on b-numbers. Adapters need to carry both.
- **B-number check digit.** B-numbers are 9 chars (`b` + 7 digits +
  1 check char that can be a digit or `x`). The design doc's regex
  `^b\d{8}x?$` is wrong on two counts: it allows 9 digits, and it makes
  the `x` optional rather than placing it among the legal final chars.
  Use `^b\d{7}[\dx]$`.
- **Catalogue API emits v2 manifest URLs.** Even though v3 is the modern
  default, the catalogue's `items[].locations[].url` value uses
  `/presentation/v2/{bnumber}`. Don't trust the catalogue URL for the
  presentation version; rewrite to `/presentation/{bnumber}` if you want
  v3.
- **Image API is v2, not v3.** The developer portal is titled "IIIF APIs
  (v3)" but only the *Presentation* API is v3. Image services in
  manifests are still `ImageService2` and info.json declares `image/2`.
- **Content Search is v1, not v2.** Despite the design doc assuming
  `SearchService2`, every manifest we examined uses `SearchService1` /
  `AutoCompleteService1` with profile `http://iiif.io/api/search/1/...`.
- **ALTO version mismatch.** Canvas `seeAlso.profile` says ALTO v3
  (`http://www.loc.gov/standards/alto/v3/alto.xsd`) but the file body is
  ALTO v2 (`xmlns=...alto/ns-v2#`). Parser must handle either namespace.
- **Auth services live on the manifest, not in info.json.** The image
  asset's `info.json` includes the `auth/2` context but no actual service
  block; clients have to read the manifest's image service to find the
  `AuthProbeService2` URL.
- **Both AuthService1 and AuthService2 advertised together** on
  restricted assets — clients should support v2, fall back to v1.
- **`/presentation/collections/...` is throttled.** Returns
  `503 "Dynamic collections are disabled because of too many requests"`
  more often than not. Don't design a discovery path that depends on it.
- **Restricted manifests still expose plain-text and Content Search.**
  This is genuinely useful: you can index searchable text for clinical
  material whose images you can't download.
- **Manifest `services` array carries Wellcome-specific extensions:**
  `tracking-extensions-profile` (Universal Viewer telemetry hint),
  `iiif-builder/build-timestamp`, and `access-control-hints` (the legacy
  Wellcome `open|restricted|safeguarded|...` hint). These are harmless to
  ignore but useful to inspect during development.
- **CORS is wide open** (`access-control-allow-origin: *`) on both the
  catalogue API and the IIIF host. Browser-side discovery is feasible.
- **Built by:** the Presentation API server is the open-source
  `iiif-builder` (.NET, PostgreSQL, AWS) at
  https://github.com/wellcomecollection/iiif-builder. The
  `services[].profile` of `https://github.com/wellcomecollection/iiif-builder/build-timestamp`
  in every manifest is its calling card.
- **No documented Change Discovery / Activity Streams endpoint** is
  surfaced from the developer portal as of May 2026. The design doc
  mentions Wellcome publishing one — this could not be verified.

### Recent breaking changes (last ~2 years)
- Migration from the old `wellcomelibrary.org` host to
  `iiif.wellcomecollection.org` is long settled but old links may still
  appear in third-party docs.
- Auth API v2 service blocks (`AuthProbeService2`, `AuthAccessService2`)
  were added alongside the v1 ones; existing v1-only clients still work.
- We did not see evidence of recent catalogue filter renames; the names in
  §1 are stable.

---

## Corrections to DESIGN.md §6

Concrete bullet-point updates the design doc needs:

- **Manifest URL pattern.** Change
  `https://iiif.wellcomecollection.org/presentation/{workId}` to
  `https://iiif.wellcomecollection.org/presentation/{bnumber}` — the
  path component is the Sierra b-number, **not** the catalogue work ID.
  The catalogue work ID (e.g. `r32p4n5s`) drives `wellcomecollection.org/works/{workId}`
  but is never in an IIIF URL.
- **Content Search version.** Replace "Content Search v2" / "SearchService2"
  with **Content Search v1 / `SearchService1`** (profile
  `http://iiif.io/api/search/1/search`). Wellcome has not deployed v2.
- **Image API version.** Add an explicit note that Wellcome's Image API is
  **v2** (`ImageService2`, `http://iiif.io/api/image/2/context.json`),
  even though Presentation is v3. The §8 size-keyword translation logic
  should default to v2 conventions for Wellcome.
- **B-number regex.** The text "Wellcome b-number regex
  `^b\d{8}x?$`" in §4.5 is wrong. Correct form is `^b\d{7}[\dx]$`
  (9 chars total: `b` + 7 digits + 1 trailing digit-or-`x` check char).
- **Catalogue filter name.** §6 says
  `availabilities=open-shelves|online`. Verified values are `online`,
  `open-shelves`, `closed-stores`. Add a separate filter
  `items.locations.accessConditions.status` with values
  `open|restricted|safeguarded|licensed-resources|permission-required`
  for the openness axis the design doc seems to want.
- **Multi-volume modeling.** The "may itself be a Collection for
  multi-volume works" parenthetical is misleading. In practice multi-
  volume works on Wellcome are sibling Works with `partOf` series links,
  **not** IIIF Collections. The `/presentation/collections/...` endpoint
  exists but is throttled and not designed for client crawling. The
  Wellcome adapter should enumerate via the catalogue API.
- **OCR strategy ordering.** §6 lists Content Search first, ALTO second.
  Re-order: ALTO via `seeAlso` first (offline, deterministic, has
  bboxes), then per-canvas AnnotationPage, then manifest-level plain-text
  rendering (`/text/v1/{bnumber}`), then live Content Search v1 as last
  resort. ALTO is universally available on books/journals.
- **ALTO format/profile matching.** Match on
  `format == "text/xml"` AND `profile` contains the substring `alto`.
  Don't string-equality-match the profile URL — Wellcome advertises
  `.../alto/v3/alto.xsd` but serves ALTO v2 XML
  (`xmlns=".../alto/ns-v2#"`).
- **Auth detection.** Add a §6 sub-bullet: restricted Wellcome assets
  advertise both `AuthCookieService1` and `AuthProbeService2` /
  `AuthAccessService2` on the **manifest's** image service block. The
  asset's own `info.json` carries the `auth/2` `@context` but **omits**
  the actual service block, so auth discovery must walk the manifest, not
  info.json. Unauthenticated image fetch returns bare `HTTP 401` (no
  body).
- **Restricted ≠ unindexable.** Note that restricted manifests still
  serve plain-text rendering and Content Search results — the adapter
  should still build a text-only index for those works and only skip
  image downloads.
- **No API key, no published rate limit.** Document that there is no
  authentication and no published rate limit, but warn that
  `/presentation/collections/...` is intentionally throttled (returns
  503 "Dynamic collections are disabled because of too many requests")
  and should not be part of a discovery path.
- **Catalogue includes are required.** Note that fields like
  `items`, `identifiers`, `parts`, `partOf`, `subjects`, `contributors`
  come back empty unless explicitly requested via `include=`. The
  Wellcome adapter should always send
  `include=items,identifiers,subjects,contributors,production,languages,genres,parts,partOf`
  for `search-iiif`.
- **Two identifier spaces.** `document_metadata` should store **both**
  the catalogue work ID and the b-number, plus emit a `homepage` of
  `https://wellcomecollection.org/works/{workId}` for the `--viewer`
  mode of `get-url`.
