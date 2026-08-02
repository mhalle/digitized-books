"""Smoke tests — no network. Validate pure-function modules and CLI shell."""
from __future__ import annotations

import click
from click.testing import CliRunner

from iiif_utils.cli import cli
from iiif_utils.core import alto, image_api, manifest
from iiif_utils.core.database import book_page_from_label


def test_cli_version_runs():
    r = CliRunner().invoke(cli, ["--version"])
    assert r.exit_code == 0
    assert "iiif-utils" in r.output


def test_cli_help_lists_commands():
    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    for cmd in ("info", "list-files", "create-index", "rebuild-index",
                 "search-catalog", "search-cat", "search-index",
                 "get-info", "get-page", "get-pages", "get-pdf",
                 "get-figure", "get-region", "get-text", "get-url",
                 "list-figures", "ocr-page", "render-page",
                 "migrate-index", "get-page-stats"):
        assert cmd in r.output


def test_dims_from_info():
    from iiif_utils.core.image_api import dims_from_info
    assert dims_from_info({"width": 1820, "height": 2938}) == (1820, 2938)
    assert dims_from_info({"width": "1820", "height": "2938"}) == (1820, 2938)
    assert dims_from_info({}) == (None, None)
    assert dims_from_info({"width": "garbage"}) == (None, None)


def test_resolve_dims_uses_stored_when_valid():
    from iiif_utils.core.image_api import resolve_dims
    row = {"image_width": 1820, "image_height": 2938,
           "width": 1731, "height": 2903,
           "image_service_url": "https://example.org/svc/x"}
    # No HTTP needed when stored dims are valid.
    assert resolve_dims(row) == (1820, 2938)


def test_resolve_dims_falls_through_to_placeholder_without_http():
    from iiif_utils.core.image_api import resolve_dims
    # LoC case: placeholder 99999, no cfg_http → return placeholder.
    row = {"image_width": None, "image_height": None,
           "width": 99999, "height": 99999,
           "image_service_url": "https://example.org/svc/x"}
    assert resolve_dims(row) == (99999, 99999)


def test_create_mosaic_tiny():
    """Build a 2x1 mosaic from synthetic JPEG bytes."""
    import io as _io
    from PIL import Image as _Image
    from iiif_utils.core.mosaic import create_mosaic

    def jpg(color):
        b = _io.BytesIO()
        _Image.new("RGB", (100, 150), color).save(b, format="JPEG")
        return b.getvalue()

    out = create_mosaic([jpg("red"), jpg("blue")],
                        labels=["A", "B"], width=200, cols=2, grid=True)
    # Round-trip: it's a JPEG we can open and the size lines up with
    # 2 cols × 100 px tiles → 200 wide × 150 tall.
    im = _Image.open(_io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.size == (200, 150)


def test_create_mosaic_letterboxes_extreme_aspect():
    """Fold-out plates have wild aspect ratios — must not stretch to fit
    the first tile's shape. Verify the second tile gets letterboxed."""
    import io as _io
    from PIL import Image as _Image
    from iiif_utils.core.mosaic import create_mosaic

    def jpg(w, h, color):
        b = _io.BytesIO()
        _Image.new("RGB", (w, h), color).save(b, format="JPEG")
        return b.getvalue()

    # First tile: standard book-page aspect (~0.7 wide:tall)
    # Second tile: extreme tall fold-out (~0.35 wide:tall — like Bourgery's `af`)
    standard = jpg(700, 1000, "red")
    fold_out = jpg(700, 2000, "blue")

    out = create_mosaic([standard, fold_out],
                        labels=None, width=200, cols=2, grid=False)
    im = _Image.open(_io.BytesIO(out))
    # Grid is uniform: cells are 100×142 (first tile's aspect at 100w).
    # Fold-out fits-within so it gets letterboxed with white bars top+bottom.
    assert im.size == (200, 142)

    # Sample a pixel that should be white from letterboxing.
    # Second tile occupies the right half. Fold-out at 100w preserves aspect →
    # ~50h (since 700w → 2000h scaled to 100w → ~285h, but capped to 142, so
    # actual rendered size is constrained to fit 100×142). Top-left corner of
    # right tile should be inside the rendered area or letterbox depending on
    # which dimension is the limiter. Just confirm: the right-tile region
    # has at least some non-blue pixels (letterbox bars or blue image).
    px_top_right = im.getpixel((199, 0))
    # Either white (letterbox) or blue (image edge) — but NOT distorted-red
    assert px_top_right != (255, 0, 0), (
        "right tile shouldn't contain first-image color"
    )


def test_create_mosaic_uniform_aspect_unchanged():
    """When all tiles share the first tile's aspect, output dims are unchanged
    from the pre-letterboxing behavior."""
    import io as _io
    from PIL import Image as _Image
    from iiif_utils.core.mosaic import create_mosaic

    def jpg(color):
        b = _io.BytesIO()
        _Image.new("RGB", (100, 150), color).save(b, format="JPEG")
        return b.getvalue()

    out = create_mosaic([jpg("red"), jpg("blue")],
                        labels=["A", "B"], width=200, cols=2, grid=True)
    im = _Image.open(_io.BytesIO(out))
    assert im.size == (200, 150)


def test_seealso_polymorphism():
    """v2 allowed seeAlso to be a single dict, a list of dicts, or strings."""
    from iiif_utils.core.manifest import _alto_seealso
    alto_obj = {"@id": "https://x/page.alto.xml", "format": "text/xml",
                 "profile": "http://www.loc.gov/standards/alto/v3/alto.xsd"}
    # case 1: list of dicts (Wellcome)
    assert _alto_seealso({"seeAlso": [alto_obj]}) == "https://x/page.alto.xml"
    # case 2: single dict (MDZ-style)
    assert _alto_seealso({"seeAlso": alto_obj}) == "https://x/page.alto.xml"
    # case 3: list with non-ALTO entries — return None
    other = {"@id": "https://x/meta.xml", "format": "text/xml",
              "profile": "dublin-core"}
    assert _alto_seealso({"seeAlso": [other]}) is None
    # case 4: missing
    assert _alto_seealso({}) is None


def test_mdz_bsb_recognizer():
    from iiif_utils.providers.mdz import looks_like_bsb, parse_ref
    assert looks_like_bsb("bsb00056329")
    assert looks_like_bsb("bsb1234567890")
    assert not looks_like_bsb("b22396147")    # Wellcome
    assert not looks_like_bsb("kdckv24y")     # Wellcome work-id
    assert not looks_like_bsb("49043519")     # LoC
    assert parse_ref("bsb00056329") == "bsb00056329"
    assert parse_ref(
        "https://api.digitale-sammlungen.de/iiif/presentation/v2/"
        "bsb00056329/manifest"
    ) == "bsb00056329"
    assert parse_ref(
        "https://api.digitale-sammlungen.de/iiif/presentation/v2/"
        "bsb11107655_0001/manifest"
    ) == "bsb11107655"


def test_mdz_inject_hocr_urls():
    from iiif_utils.providers.mdz import inject_hocr_urls
    m = {"sequences": [{"canvases": [
        {"@id": "x/canvas/1"},  # no existing seeAlso
        {"@id": "x/canvas/2", "seeAlso": {"@id": "y", "format": "x/y"}},
        {"@id": "x/canvas/3", "seeAlso": [{"@id": "z", "format": "a/b"}]},
    ]}]}
    inject_hocr_urls(m, "bsb00056329")
    cs = m["sequences"][0]["canvases"]
    # All three should now have a list-typed seeAlso with a hOCR entry
    for i, c in enumerate(cs, start=1):
        sa = c["seeAlso"]
        assert isinstance(sa, list)
        hocr_entries = [s for s in sa
                         if s.get("format") == "text/vnd.hocr+html"]
        assert len(hocr_entries) == 1
        assert hocr_entries[0]["@id"] == (
            f"https://api.digitale-sammlungen.de/ocr/bsb00056329/{i}")
    # Existing entries preserved on canvases 2 + 3
    assert any(s.get("format") == "x/y" for s in cs[1]["seeAlso"])
    assert any(s.get("format") == "a/b" for s in cs[2]["seeAlso"])


def test_hocr_parser_minimal():
    from iiif_utils.core.hocr import parse_hocr_bytes
    sample = b"""<html><body>
    <div class="ocr_page" title="image x.jp2; bbox 0 0 1000 1500">
      <div class="ocrx_block" title="bbox 10 20 110 60">
        <p class="ocr_par" title="bbox 10 20 110 60">
          <span class="ocr_line" title="bbox 10 20 110 60">
            <span class="ocrx_word" title="bbox 10 20 50 60; x_wconf 95">hello</span>
            <span class="ocrx_word" title="bbox 55 20 110 60; x_wconf 87">world</span>
          </span>
        </p>
      </div>
    </div></body></html>"""
    page = parse_hocr_bytes(sample)
    assert page.page_w == 1000
    assert page.page_h == 1500
    assert len(page.text_blocks) == 1
    b = page.text_blocks[0]
    assert b.text == "hello world"
    assert (b.bbox_x0, b.bbox_y0, b.bbox_x1, b.bbox_y1) == (10, 20, 110, 60)
    assert b.line_count == 1
    assert b.word_count == 2
    assert page.illustrations == []  # hOCR has no Illustration analog


def test_loc_lccn_recognizer():
    from iiif_utils.providers.loc import looks_like_lccn, parse_ref
    assert looks_like_lccn("49043519")
    assert looks_like_lccn("18017427")
    assert looks_like_lccn("a33000991")
    assert not looks_like_lccn("b22396147")  # Wellcome b-number
    assert not looks_like_lccn("kdckv24y")    # Wellcome work id
    assert parse_ref("49043519") == "49043519"
    assert parse_ref("https://www.loc.gov/item/49043519/") == "49043519"
    assert parse_ref("https://loc.gov/item/49043519") == "49043519"
    assert parse_ref("not a thing") is None


def test_loc_synthesize_manifest():
    from iiif_utils.providers.loc import synthesize_manifest
    item_json = {
        "item": {
            "title": "Test Book",
            "date": "1543",
            "contributor_names": ["Author One"],
            "subject": ["Anatomy"],
            "language": ["Latin"],
        },
        "resources": [{
            "pdf": "https://example.org/book.pdf",
            "fulltext_file": "https://example.org/book.txt",
            "files": [
                # canvas 0 — ALTO + plain text + image
                [
                    {"mimetype": "image/jpeg",
                     "url": "https://tile.loc.gov/image-services/iiif/SVC1/full/pct:100/0/default.jpg"},
                    {"mimetype": "text/xml",
                     "url": "https://tile.loc.gov/storage/foo/0001.alto.xml"},
                    {"mimetype": "text/plain",
                     "url": "https://tile.loc.gov/storage/foo/0001.txt"},
                ],
                # canvas 1 — plain text only (Vesalius case)
                [
                    {"mimetype": "image/jpeg",
                     "url": "https://tile.loc.gov/image-services/iiif/SVC2/full/pct:100/0/default.jpg"},
                    {"mimetype": "text/plain",
                     "url": "https://tile.loc.gov/storage/foo/0002.txt"},
                ],
            ],
        }],
    }
    m = synthesize_manifest("49043519", item_json)
    assert m["@type"] == "sc:Manifest"
    assert m["label"] == "Test Book"
    cans = m["sequences"][0]["canvases"]
    assert len(cans) == 2
    # canvas 0 — both ALTO and text seeAlso
    sa0 = cans[0]["seeAlso"]
    assert any(s["format"] == "text/xml" and "alto" in s["profile"].lower()
                for s in sa0)
    assert any(s["format"] == "text/plain" for s in sa0)
    # canvas 1 — only text seeAlso
    sa1 = cans[1]["seeAlso"]
    assert all(s["format"] != "text/xml" for s in sa1)
    assert any(s["format"] == "text/plain" for s in sa1)
    # image service URL stripped to base
    assert cans[0]["images"][0]["resource"]["service"]["@id"] == \
        "https://tile.loc.gov/image-services/iiif/SVC1"
    # rendering carries PDF + fulltext
    fmts = {r["format"] for r in m["rendering"]}
    assert "application/pdf" in fmts
    assert "text/plain" in fmts


def test_resolve_leaf_explicit_leaf():
    import sqlite3 as _sql
    from iiif_utils.utils.page import resolve_leaf
    conn = _sql.connect(":memory:")
    conn.row_factory = _sql.Row
    conn.execute("CREATE TABLE page_numbers ("
                 "leaf_num INTEGER PRIMARY KEY, book_page_number TEXT)")
    conn.execute("INSERT INTO page_numbers VALUES (756, '737')")
    conn.execute("INSERT INTO page_numbers VALUES (760, '741')")
    conn.commit()
    # explicit leaf
    assert resolve_leaf(conn, 198, None) == 198
    # via book lookup
    assert resolve_leaf(conn, None, "737") == 756
    assert resolve_leaf(conn, None, "741") == 760


def test_resolve_leaf_errors():
    import sqlite3 as _sql
    import pytest as _pt
    from iiif_utils.utils.page import resolve_leaf
    conn = _sql.connect(":memory:")
    conn.row_factory = _sql.Row
    conn.execute("CREATE TABLE page_numbers ("
                 "leaf_num INTEGER PRIMARY KEY, book_page_number TEXT)")
    conn.commit()
    # both → error
    with _pt.raises(click.UsageError):
        resolve_leaf(conn, 1, "2")
    # neither → error
    with _pt.raises(click.UsageError):
        resolve_leaf(conn, None, None)
    # book that doesn't exist → ClickException
    with _pt.raises(click.ClickException):
        resolve_leaf(conn, None, "999")


def test_ocr_page_bbox_parser():
    """Multi-format bbox parsing from ia-utils."""
    from iiif_utils.commands.ocr_page import _parse_bbox
    assert _parse_bbox("10,20,30,40") == (10, 20, 30, 40)
    assert _parse_bbox("10 20 30 40") == (10, 20, 30, 40)
    assert _parse_bbox("bbox 10 20 30 40") == (10, 20, 30, 40)
    assert _parse_bbox(" 10 , 20 , 30 , 40 ") == (10, 20, 30, 40)


def test_search_catalog_alias_works():
    """search-cat must reach the same handler as search-catalog."""
    r1 = CliRunner().invoke(cli, ["search-catalog", "--help"])
    r2 = CliRunner().invoke(cli, ["search-cat", "--help"])
    assert r1.exit_code == 0 and r2.exit_code == 0
    # Both --help outputs describe the same options
    assert "--year" in r1.output and "--year" in r2.output
    assert "--has-iiif" in r1.output and "--has-iiif" in r2.output


def test_book_page_normalization():
    assert book_page_from_label("145") == "145"
    assert book_page_from_label("-") is None
    assert book_page_from_label("--") is None
    assert book_page_from_label("") is None
    assert book_page_from_label(None) is None
    assert book_page_from_label(" 12 ") == "12"


def test_label_string_v3_language_map():
    assert manifest.label_string({"none": ["foo"]}) == "foo"
    assert manifest.label_string({"en": ["bar"]}) == "bar"
    assert manifest.label_string("plain") == "plain"
    assert manifest.label_string(None) is None


def test_region_url_pixel_bbox():
    url = image_api.region_url(
        "https://example.org/image/x",
        (10, 20, 110, 220),
        size="800,",
    )
    assert url == "https://example.org/image/x/10,20,100,200/800,/0/default.jpg"


def test_region_url_full():
    url = image_api.region_url("https://example.org/image/x", None,
                                size="full")
    assert url == "https://example.org/image/x/full/full/0/default.jpg"


def test_resolve_max_size_passes_through(monkeypatch):
    # Non-'max' sizes never trigger an info.json fetch.
    def explode(*a, **kw):
        raise AssertionError("fetch_info_json must not be called")
    monkeypatch.setattr(image_api, "fetch_info_json", explode)
    assert image_api.resolve_max_size("800,", "https://x/y",
                                        cfg_http={}) == "800,"
    assert image_api.resolve_max_size("full", "https://x/y",
                                        cfg_http={}) == "full"


def test_resolve_max_size_expands_to_native_width(monkeypatch):
    # 'max' fetches info.json and substitutes '{width},'.
    monkeypatch.setattr(image_api, "fetch_info_json",
                        lambda url, **kw: {"width": 2734, "height": 4485})
    assert image_api.resolve_max_size("max", "https://x/y",
                                        cfg_http={}) == "2734,"


def test_resolve_max_size_falls_back_on_missing_width(monkeypatch):
    monkeypatch.setattr(image_api, "fetch_info_json", lambda url, **kw: {})
    assert image_api.resolve_max_size("max", "https://x/y",
                                        cfg_http={}) == "full"


def test_padded_bbox_clamps():
    out = image_api.padded_bbox((100, 100, 200, 200), 50,
                                  canvas_w=210, canvas_h=210)
    assert out == (50, 50, 210, 210)


def test_padded_bbox_pct():
    out = image_api.padded_bbox((100, 100, 200, 300), "10%")
    assert out == (90, 80, 210, 320)  # 10px x, 20px y


def test_padded_bbox_four_value_pixels():
    # bbox = (100, 100, 200, 300), w=100, h=200
    # padding = left=10, top=20, right=30, bottom=40
    out = image_api.padded_bbox((100, 100, 200, 300), "10,20,30,40")
    assert out == (90, 80, 230, 340)


def test_padded_bbox_four_value_mixed_pct():
    # left=10%×100=10, top=10%×200=20, right=5%×100=5, bottom=5%×200=10
    out = image_api.padded_bbox((100, 100, 200, 300), "10%,10%,5%,5%")
    assert out == (90, 80, 205, 310)


def test_padded_bbox_four_value_clamps():
    # Symmetric 50px asymmetric clamped to a tight 210x210 canvas
    out = image_api.padded_bbox((100, 100, 200, 200), "50,50,50,50",
                                  canvas_w=210, canvas_h=210)
    assert out == (50, 50, 210, 210)


def test_padded_bbox_invalid_count_raises():
    import pytest
    with pytest.raises(ValueError):
        image_api.padded_bbox((0, 0, 100, 100), "10,20,30")  # 3 values


def test_clamp_dims_prefers_image_dims():
    # When both available, image-native (ALTO Page) wins over canvas dims
    row = {"image_width": 1820, "image_height": 2938,
           "width": 1731, "height": 2903}
    assert image_api.clamp_dims_from_page_row(row) == (1820, 2938)


def test_clamp_dims_falls_back_to_canvas_dims():
    row = {"image_width": None, "image_height": None,
           "width": 1731, "height": 2903}
    assert image_api.clamp_dims_from_page_row(row) == (1731, 2903)


def test_output_formats_roundtrip():
    """Smoke-test all four output formats over the same rows."""
    import io
    import json as json_
    from iiif_utils.utils.output import write_records

    rows = [
        {"canvas": 198, "n": 0, "bbox": [454, 306, 1148, 2676],
         "url": "https://x/y"},
        {"canvas": 312, "n": 1, "bbox": [100, 100, 200, 200],
         "url": None},
    ]

    # json: round-trippable
    buf = io.StringIO()
    write_records(rows, "json", fp=buf)
    parsed = json_.loads(buf.getvalue())
    assert parsed == rows

    # jsonl: one record per line
    buf = io.StringIO()
    write_records(rows, "jsonl", fp=buf)
    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert json_.loads(lines[0])["canvas"] == 198

    # csv: header + 2 rows
    buf = io.StringIO()
    write_records(rows, "csv", fp=buf)
    out_lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(out_lines) == 3
    assert out_lines[0].startswith("canvas,")

    # table: header + 2 rows
    buf = io.StringIO()
    write_records(rows, "table", fp=buf)
    assert "canvas" in buf.getvalue()
    assert "198" in buf.getvalue()

    # records: key: value lines
    buf = io.StringIO()
    write_records(rows, "records", fp=buf)
    assert "canvas: 198" in buf.getvalue()
    assert "canvas: 312" in buf.getvalue()


def test_listing_commands_accept_format_flag():
    """--format is wired on list-figures / list-files / search-index."""
    r = CliRunner().invoke(cli, ["list-figures", "--help"])
    assert "--format" in r.output
    r = CliRunner().invoke(cli, ["list-files", "--help"])
    assert "--format" in r.output
    r = CliRunner().invoke(cli, ["search-index", "--help"])
    assert "--format" in r.output


MINIMAL_ALTO = b"""<?xml version='1.0'?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Description><MeasurementUnit>pixel</MeasurementUnit></Description>
  <Layout>
    <Page WIDTH="1000" HEIGHT="2000" PHYSICAL_IMG_NR="1" ID="P1">
      <PrintSpace>
        <TextBlock ID="B1" HPOS="10" VPOS="20" WIDTH="100" HEIGHT="50">
          <TextLine ID="L1" HPOS="10" VPOS="20" WIDTH="100" HEIGHT="20">
            <String CONTENT="hello" HPOS="10" VPOS="20" WIDTH="40" HEIGHT="20"/>
            <SP HPOS="50" VPOS="20" WIDTH="5"/>
            <String CONTENT="world" HPOS="55" VPOS="20" WIDTH="55" HEIGHT="20"/>
          </TextLine>
        </TextBlock>
        <Illustration ID="I1" HPOS="500" VPOS="800" WIDTH="300" HEIGHT="400"/>
      </PrintSpace>
    </Page>
  </Layout>
</alto>"""


def test_parse_year_spec():
    from iiif_utils.commands.search_catalog import _parse_year
    # Single year → Jan 1 / Dec 31
    assert _parse_year("1914") == ("1914-01-01", "1914-12-31")
    assert _parse_year("1900-1950") == ("1900-01-01", "1950-12-31")
    assert _parse_year("1900-") == ("1900-01-01", None)
    assert _parse_year("-1950") == (None, "1950-12-31")
    assert _parse_year("") == (None, None)


def test_parse_leaf_range():
    from iiif_utils.commands.get_pages import _parse_leaf_range
    assert _parse_leaf_range("3", 10) == [3]
    assert _parse_leaf_range("1-5", 10) == [1, 2, 3, 4, 5]
    assert _parse_leaf_range("1-5,10", 10) == [1, 2, 3, 4, 5, 10]
    assert _parse_leaf_range("1-3,2-4", 10) == [1, 2, 3, 4]  # union, sorted
    assert _parse_leaf_range("8-12", 10) == [8, 9, 10]  # clamp to max
    assert _parse_leaf_range("", 10) == []


def test_health_partial_digitization_label():
    from iiif_utils.core.health import detect_partial_digitization
    assert detect_partial_digitization({"label": "Cunningham. Section 2."})
    assert detect_partial_digitization({"label": "Atlas of Anatomy"}) is None


def test_health_multiple_volumes_via_cover_ranges():
    from iiif_utils.core.health import detect_multiple_volumes
    m = {"structures": [
        {"type": "Range", "label": {"none": ["Cover"]}, "items": []},
        {"type": "Range", "label": {"none": ["Vol. 1"]}, "items": []},
        {"type": "Range", "label": {"none": ["Cover"]}, "items": []},
        {"type": "Range", "label": {"none": ["Vol. 2"]}, "items": []},
    ]}
    reason = detect_multiple_volumes(m)
    assert reason is not None and "cover" in reason.lower()
    # Single Cover should NOT trip the detector
    m2 = {"structures": [
        {"type": "Range", "label": {"none": ["Cover"]}, "items": []},
        {"type": "Range", "label": {"none": ["Vol. 1"]}, "items": []},
    ]}
    assert detect_multiple_volumes(m2) is None


def test_disambiguate_filename():
    from iiif_utils.core.database import disambiguate_filename
    assert disambiguate_filename("a", set()) == "a"
    assert disambiguate_filename("a", {"a"}) == "a-2"
    assert disambiguate_filename("foo.pdf", {"foo.pdf"}) == "foo-2.pdf"
    assert disambiguate_filename("foo.pdf", {"foo.pdf", "foo-2.pdf"}) == "foo-3.pdf"


def test_get_pages_sample_indices_evenly_spaced():
    from iiif_utils.commands.get_pages import _sample_indices
    assert _sample_indices(100, 5) == [0, 20, 40, 60, 80]
    assert _sample_indices(10, 3) == [0, 3, 6]
    # n > total → return all indices, no duplicates
    assert _sample_indices(3, 10) == [0, 1, 2]
    # Edge: clamp last index to total-1 even if step rounds up
    out = _sample_indices(7, 7)
    assert out == list(range(7))
    assert _sample_indices(0, 5) == []
    assert _sample_indices(10, 0) == []


def test_get_pages_requires_source():
    """--index or --manifest is mandatory."""
    r = CliRunner().invoke(cli, ["get-pages", "--all", "--url-only"])
    assert r.exit_code != 0
    assert "INDEX" in r.output or "manifest" in r.output.lower()


def test_get_pages_rejects_combining_sources(tmp_path):
    """-i and --manifest are mutually exclusive."""
    idx = tmp_path / "fake.sqlite"
    idx.write_bytes(b"")  # exists; we won't actually open it
    r = CliRunner().invoke(cli, [
        "get-pages", "-i", str(idx), "--manifest", "https://x/m", "--all",
        "--url-only",
    ])
    assert r.exit_code != 0
    assert "combine" in r.output.lower() or "exclusive" in r.output.lower()


def test_get_pages_rejects_child_without_manifest(tmp_path):
    idx = tmp_path / "fake.sqlite"
    idx.write_bytes(b"")
    r = CliRunner().invoke(cli, [
        "get-pages", "-i", str(idx), "--child", "2", "--all", "--url-only",
    ])
    assert r.exit_code != 0


def test_get_pages_rejects_zip_with_manifest():
    """Zip/prefix require an index — they need page-level metadata."""
    r = CliRunner().invoke(cli, [
        "get-pages", "--manifest", "https://x/m", "--all", "--zip",
        "-o", "/tmp/x.zip",
    ])
    assert r.exit_code != 0
    assert "manifest" in r.output.lower()


def test_get_pages_rejects_multiple_selection_modes(tmp_path):
    idx = tmp_path / "fake.sqlite"
    idx.write_bytes(b"")
    r = CliRunner().invoke(cli, [
        "get-pages", "-i", str(idx), "--all", "--sample", "10", "--url-only",
    ])
    assert r.exit_code != 0
    assert "exclusive" in r.output.lower()


def test_create_index_has_no_ocr_flag():
    r = CliRunner().invoke(cli, ["create-index", "--help"])
    assert r.exit_code == 0
    assert "--no-ocr" in r.output


def test_heidelberg_parse_ref_stem_and_url():
    from iiif_utils.providers import heidelberg as h
    assert h.parse_ref("bourgery1834bd2_1") == "bourgery1834bd2_1"
    assert h.parse_ref("bourgey1832bd1_1") == "bourgey1832bd1_1"
    assert h.parse_ref(
        "https://digi.ub.uni-heidelberg.de/diglit/bourgery1834bd2_1"
    ) == "bourgery1834bd2_1"
    assert h.parse_ref(
        "https://digi.ub.uni-heidelberg.de/diglit/iiif/bourgery1834bd2_1/manifest.json"
    ) == "bourgery1834bd2_1"
    assert h.parse_ref("not a stem!!!") is None


def test_heidelberg_parse_mets_alto_urls():
    """Tiny synthetic METS — verify FULLTEXT fileGrp URLs are extracted."""
    from iiif_utils.providers.heidelberg import parse_mets_alto_urls
    mets = b"""<?xml version="1.0"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
            xmlns:xlink="http://www.w3.org/1999/xlink">
  <mets:fileSec>
    <mets:fileGrp USE="MAX">
      <mets:file><mets:FLocat xlink:href="https://example.org/img/1"/></mets:file>
    </mets:fileGrp>
    <mets:fileGrp USE="FULLTEXT">
      <mets:file><mets:FLocat xlink:href="https://example.org/ocr/a"/></mets:file>
      <mets:file><mets:FLocat xlink:href="https://example.org/ocr/b"/></mets:file>
      <mets:file><mets:FLocat xlink:href="https://example.org/ocr/c"/></mets:file>
    </mets:fileGrp>
  </mets:fileSec>
</mets:mets>"""
    urls = parse_mets_alto_urls(mets)
    assert urls == [
        "https://example.org/ocr/a",
        "https://example.org/ocr/b",
        "https://example.org/ocr/c",
    ]


def test_heidelberg_parse_mets_no_fulltext():
    from iiif_utils.providers.heidelberg import parse_mets_alto_urls
    mets = b"""<?xml version="1.0"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/">
  <mets:fileSec>
    <mets:fileGrp USE="MAX"></mets:fileGrp>
  </mets:fileSec>
</mets:mets>"""
    assert parse_mets_alto_urls(mets) == []


def test_heidelberg_inject_alto_urls_into_manifest():
    from iiif_utils.providers.heidelberg import inject_alto_urls
    manifest = {
        "@type": "sc:Manifest",
        "sequences": [{"canvases": [
            {"@id": "c1"},
            {"@id": "c2", "seeAlso": {"@id": "existing", "format": "image/svg+xml"}},
            {"@id": "c3", "seeAlso": [{"@id": "e1"}]},
        ]}],
    }
    out = inject_alto_urls(manifest, [
        "https://x/ocr/1",
        "https://x/ocr/2",
        "https://x/ocr/3",
    ])
    canvases = out["sequences"][0]["canvases"]
    # c1: no prior seeAlso → list of 1
    assert canvases[0]["seeAlso"] == [
        {"@id": "https://x/ocr/1", "format": "text/xml",
         "profile": "http://www.loc.gov/standards/alto/ns-v2#",
         "label": "ALTO (Heidelberg)"},
    ]
    # c2: had a dict → normalized to list of 2
    assert len(canvases[1]["seeAlso"]) == 2
    assert canvases[1]["seeAlso"][1]["@id"] == "https://x/ocr/2"
    # c3: had a list of 1 → extended to 2
    assert len(canvases[2]["seeAlso"]) == 2
    assert canvases[2]["seeAlso"][1]["@id"] == "https://x/ocr/3"


def test_heidelberg_inject_alto_fewer_urls_than_canvases():
    """Partial coverage: shorter ALTO list → only first N canvases get it."""
    from iiif_utils.providers.heidelberg import inject_alto_urls
    manifest = {"sequences": [{"canvases": [{"@id": f"c{i}"} for i in range(5)]}]}
    inject_alto_urls(manifest, ["https://x/1", "https://x/2"])
    canvases = manifest["sequences"][0]["canvases"]
    assert "seeAlso" in canvases[0] and "seeAlso" in canvases[1]
    assert "seeAlso" not in canvases[2]
    assert "seeAlso" not in canvases[3]
    assert "seeAlso" not in canvases[4]


def test_heidelberg_provider_guessed_from_url():
    from iiif_utils.providers import _guess_provider
    cfg = {"default_provider": "generic"}
    assert _guess_provider(
        "https://digi.ub.uni-heidelberg.de/diglit/bourgery1834bd2_1", cfg,
    ) == "heidelberg"


def test_ia_parse_ref():
    from iiif_utils.providers.internet_archive import parse_ref
    assert parse_ref("anatomyofhumanbo1918gray") == "anatomyofhumanbo1918gray"
    assert parse_ref("cihm_90559") == "cihm_90559"
    assert parse_ref("cu31924024790648") == "cu31924024790648"
    assert parse_ref(
        "https://archive.org/details/anatomyofhumanbo1918gray"
    ) == "anatomyofhumanbo1918gray"
    assert parse_ref(
        "https://archive.org/details/anatomyofhumanbo1918gray/page/n5"
    ) == "anatomyofhumanbo1918gray"
    assert parse_ref(
        "https://archive.org/download/anatomyofhumanbo1918gray/"
        "anatomyofhumanbo1918gray_djvu.txt"
    ) == "anatomyofhumanbo1918gray"
    assert parse_ref(
        "https://iiif.archive.org/iiif/anatomyofhumanbo1918gray/manifest.json"
    ) == "anatomyofhumanbo1918gray"
    assert parse_ref(
        "https://iiif.archive.org/iiif/anatomyofhumanbo1918gray$0/manifest.json"
    ) == "anatomyofhumanbo1918gray"
    # Unrecognized URL hosts return None.
    assert parse_ref("https://example.com/x") is None
    # Too short fails the heuristic.
    assert parse_ref("ab") is None


def test_ia_manifest_url():
    from iiif_utils.providers.internet_archive import manifest_url_for
    assert manifest_url_for("anatomyofhumanbo1918gray") == (
        "https://iiif.archive.org/iiif/anatomyofhumanbo1918gray/manifest.json"
    )


def test_ia_extra_metadata():
    from iiif_utils.providers.internet_archive import extra_metadata_for
    manifest = {
        "metadata": [
            {"label": {"none": ["title"]}, "value": {"none": ["Anatomy"]}},
            {"label": {"none": ["creator"]},
             "value": {"none": ["Gray, Henry", "Lewis, W. H."]}},
        ],
        "seeAlso": [
            {"id": "https://archive.org/metadata/anatomyofhumanbo1918gray",
             "format": "application/json", "type": "Metadata"},
            {"id": "https://archive.org/download/anatomyofhumanbo1918gray/"
                   "anatomyofhumanbo1918gray_page_numbers.json",
             "format": "application/json"},
            {"id": "https://archive.org/download/anatomyofhumanbo1918gray/"
                   "anatomyofhumanbo1918gray_hocr_pageindex.json.gz",
             "format": "application/json"},
        ],
    }
    out = extra_metadata_for(manifest, "anatomyofhumanbo1918gray")
    assert out["identifier:ia"] == "anatomyofhumanbo1918gray"
    assert out["ia_details_url"] == (
        "https://archive.org/details/anatomyofhumanbo1918gray"
    )
    assert out["manifest_metadata:title"] == "Anatomy"
    assert out["manifest_metadata:creator"] == "Gray, Henry | Lewis, W. H."
    assert "page_numbers.json" in out["ia_page_numbers_url"]
    assert "hocr_pageindex" in out["ia_hocr_pageindex_url"]
    assert "/metadata/" in out["ia_metadata_api_url"]


def test_ia_derivatives_come_from_rendering_not_seealso():
    """The OCR payloads we index from live in `rendering`, not `seeAlso`
    — verified against the real Gray's Anatomy manifest."""
    from iiif_utils.providers.internet_archive import extra_metadata_for
    base = "https://archive.org/download/gray/gray"
    manifest = {
        "seeAlso": [
            {"id": f"{base}_hocr_pageindex.json.gz"},
            {"id": f"{base}_scandata.xml"},
        ],
        "rendering": [
            {"id": f"{base}.pdf"},
            {"id": f"{base}_chocr.html.gz"},     # must NOT match _hocr.html
            {"id": f"{base}_hocr_searchtext.txt.gz"},
            {"id": f"{base}_hocr.html"},
            {"id": f"{base}_djvu.xml"},
            {"id": f"{base}_djvu.txt"},
        ],
    }
    out = extra_metadata_for(manifest, "gray")
    assert out["ia_hocr_url"] == f"{base}_hocr.html"
    assert out["ia_djvu_xml_url"] == f"{base}_djvu.xml"
    assert out["ia_djvu_txt_url"] == f"{base}_djvu.txt"
    assert out["ia_pdf_url"] == f"{base}.pdf"
    assert out["ia_hocr_searchtext_url"] == f"{base}_hocr_searchtext.txt.gz"
    assert out["ia_hocr_pageindex_url"] == f"{base}_hocr_pageindex.json.gz"
    assert out["ia_scandata_url"] == f"{base}_scandata.xml"


def test_ia_parse_page_numbers():
    """IA's own detector is authoritative; canvas labels are counters."""
    from iiif_utils.providers.internet_archive import parse_page_numbers
    payload = b"""{
      "identifier": "x", "format-version": "2",
      "pages": [
        {"leafNum": 1, "confidence": null, "pageNumber": "",
         "pageProb": null, "wordConf": null},
        {"leafNum": 24, "confidence": 100, "pageNumber": "20",
         "pageProb": 94, "wordConf": 99},
        {"leafNum": 687, "confidence": 100, "pageNumber": "687",
         "pageProb": 97, "wordConf": 32}
      ]
    }"""
    out = parse_page_numbers(payload)
    # Sparse: keyed by leafNum, not list position
    assert set(out) == {1, 24, 687}
    assert out[24]["book_page_number"] == "20"
    assert out[24]["confidence"] == 100
    assert out[24]["pageProb"] == 94
    assert out[24]["wordConf"] == 99
    # Empty pageNumber (endpapers/plates) → None, not ""
    assert out[1]["book_page_number"] is None


def test_ia_page_numbers_override_used_by_create_index(monkeypatch, tmp_path):
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    payload = (b'{"pages": [{"leafNum": 24, "confidence": 100,'
               b' "pageNumber": "20", "pageProb": 94, "wordConf": 99}]}')
    monkeypatch.setattr(ci.http_, "fetch_bytes", lambda url, **kw: payload)
    out = ci._fetch_page_number_overrides(
        {"ia_page_numbers_url": "https://x/y_page_numbers.json"},
        cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    )
    assert out[24]["book_page_number"] == "20"


def test_page_number_overrides_absent_without_url(tmp_path):
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    assert ci._fetch_page_number_overrides(
        {}, cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    ) == {}


def test_page_number_overrides_fall_back_on_error(monkeypatch, tmp_path):
    """A broken page_numbers.json must not abort the whole index."""
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger

    def boom(url, **kw):
        raise RuntimeError("404")
    monkeypatch.setattr(ci.http_, "fetch_bytes", boom)
    assert ci._fetch_page_number_overrides(
        {"ia_page_numbers_url": "https://x/y.json"},
        cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    ) == {}


def test_ia_derivative_key_rejects_chocr():
    """`_chocr.html.gz` is a different format — never map it to hOCR."""
    from iiif_utils.providers.internet_archive import _derivative_key
    assert _derivative_key("https://x/y/z_chocr.html.gz") is None
    assert _derivative_key("https://x/y/z_hocr.html") == "ia_hocr_url"
    assert _derivative_key("https://x/y/z_hocr.html.gz") == "ia_hocr_url"


def test_ia_provider_guessed_from_url():
    from iiif_utils.providers import _guess_provider
    cfg = {"default_provider": "generic"}
    assert _guess_provider(
        "https://archive.org/details/anatomyofhumanbo1918gray", cfg,
    ) == "ia"
    assert _guess_provider(
        "https://iiif.archive.org/iiif/anatomyofhumanbo1918gray/manifest.json",
        cfg,
    ) == "ia"
    assert _guess_provider(
        "https://archive.org/download/foo/bar.pdf", cfg,
    ) == "ia"


MONO_HOCR = b"""<html><body>
<div class="ocr_page" id="page_0" title="image f0; bbox 0 0 1000 1500; ppageno 0">
  <div class="ocr_carea" title="bbox 10 20 110 60">
    <p class="ocr_par" title="bbox 10 20 110 60">
      <span class="ocr_line" title="bbox 10 20 110 60">
        <span class="ocrx_word" title="bbox 10 20 50 60; x_wconf 95">hello</span>
        <span class="ocrx_word" title="bbox 55 20 110 60; x_wconf 87">world</span>
      </span>
    </p>
  </div>
</div>
<div class="ocr_page" id="page_1" title="image f1; bbox 0 0 1000 1500; ppageno 1">
  <div class="ocr_carea" title="bbox 10 20 200 60">
    <p class="ocr_caption" title="bbox 10 20 200 60">
      <span class="ocr_line" title="bbox 10 20 200 60">
        <span class="ocrx_word" title="bbox 10 20 200 60; x_wconf 80">Fig.</span>
      </span>
    </p>
  </div>
</div>
<div class="ocr_page" id="page_2" title="image f2; bbox 0 0 1000 1500; ppageno 2">
</div>
</body></html>"""


def test_hocr_multipage_parse():
    from iiif_utils.core.hocr import parse_hocr_multipage
    pages = parse_hocr_multipage(MONO_HOCR)
    # Empty page 2 still returned (dims useful downstream)
    assert [leaf for leaf, _ in pages] == [0, 1, 2]
    p0 = pages[0][1]
    assert p0.page_w == 1000 and p0.page_h == 1500
    assert len(p0.text_blocks) == 1
    b = p0.text_blocks[0]
    assert b.text == "hello world"
    assert b.block_type == "ocr_par"
    assert b.avg_confidence == 91.0        # mean(95, 87) — IA path keeps it
    assert (b.bbox_x0, b.bbox_y0, b.bbox_x1, b.bbox_y1) == (10, 20, 110, 60)
    p1 = pages[1][1]
    assert p1.text_blocks[0].block_type == "ocr_caption"
    assert pages[2][1].text_blocks == []


def test_hocr_multipage_sequence_fallback_without_ids():
    from iiif_utils.core.hocr import parse_hocr_multipage
    sample = b"""<html><body>
    <div class="ocr_page" title="bbox 0 0 100 100"></div>
    <div class="ocr_page" title="bbox 0 0 100 100"></div>
    </body></html>"""
    pages = parse_hocr_multipage(sample)
    assert [leaf for leaf, _ in pages] == [0, 1]


def test_hocr_single_page_confidence_stays_null():
    """MDZ per-canvas path must preserve its NULL-confidence invariant."""
    from iiif_utils.core.hocr import parse_hocr_bytes
    sample = b"""<html><body>
    <div class="ocr_page" title="bbox 0 0 1000 1500">
      <div class="ocrx_block" title="bbox 10 20 110 60">
        <span class="ocr_line" title="bbox 10 20 110 60">
          <span class="ocrx_word" title="bbox 10 20 50 60; x_wconf 95">hi</span>
        </span>
      </div>
    </div></body></html>"""
    page = parse_hocr_bytes(sample)
    assert page.text_blocks[0].avg_confidence is None


MONO_DJVU = b"""<?xml version="1.0"?>
<DjVuXML>
<BODY>
<OBJECT width="2400" height="3600">
  <HIDDENTEXT><PAGECOLUMN><REGION>
    <PARAGRAPH>
      <LINE>
        <WORD coords="278,1029,437,993" x-confidence="90">Smakula,</WORD>
        <WORD coords="450,1029,600,993" x-confidence="80">Alexander</WORD>
      </LINE>
    </PARAGRAPH>
  </REGION></PAGECOLUMN></HIDDENTEXT>
</OBJECT>
<OBJECT width="2400" height="3600">
</OBJECT>
</BODY>
</DjVuXML>"""


def test_djvu_multipage_parse_and_axis_conversion():
    from iiif_utils.core.djvu import parse_djvu_multipage
    pages = parse_djvu_multipage(MONO_DJVU)
    assert [leaf for leaf, _ in pages] == [0, 1]
    p0 = pages[0][1]
    assert p0.page_w == 2400 and p0.page_h == 3600
    assert len(p0.text_blocks) == 1
    b = p0.text_blocks[0]
    assert b.text == "Smakula, Alexander"
    assert b.block_type == "ocr_par"
    assert b.avg_confidence == 85.0
    # DjVu coords are left,BOTTOM,right,TOP — converted to x0,y0,x1,y1:
    # union of (278,993,437,1029) and (450,993,600,1029)
    assert (b.bbox_x0, b.bbox_y0, b.bbox_x1, b.bbox_y1) == (278, 993, 600, 1029)
    assert b.line_count == 1 and b.word_count == 2
    # Wordless page still present, no blocks
    assert pages[1][1].text_blocks == []


def test_djvu_leaf_from_usemap_not_position():
    """usemap is DjVu's own leaf-file number; position drifts when sparse."""
    from iiif_utils.core.djvu import parse_djvu_multipage
    sample = b"""<?xml version="1.0"?><DjVuXML><BODY>
    <OBJECT usemap="x_0001.djvu" width="100" height="200"></OBJECT>
    <OBJECT usemap="x_0004.djvu" width="100" height="200"></OBJECT>
    </BODY></DjVuXML>"""
    pages = parse_djvu_multipage(sample)
    # usemap is 1-based → 0-based leaves 0 and 3, NOT positions 0 and 1
    assert [leaf for leaf, _ in pages] == [0, 3]


def test_djvu_leaf_falls_back_to_position_without_usemap():
    from iiif_utils.core.djvu import parse_djvu_multipage
    assert [leaf for leaf, _ in parse_djvu_multipage(MONO_DJVU)] == [0, 1]


def test_djvu_alignment_warning():
    """Sparse or short DjVu can't be trusted against canvases."""
    from iiif_utils.core.alto import AltoPage
    from iiif_utils.core.djvu import djvu_alignment_warning

    def pg(leaf):
        return (leaf, AltoPage(0, 0, "pixel", [], []))

    # Contiguous and matching the canvas count → no warning
    assert djvu_alignment_warning([pg(0), pg(1), pg(2)], 3) is None
    # Non-contiguous (the poll-book shape) → warn
    w = djvu_alignment_warning([pg(0), pg(1), pg(3)], 3)
    assert w is not None and "non-contiguous" in w
    # Count mismatch (leaves DjVu never saw) → warn
    w2 = djvu_alignment_warning([pg(0), pg(1)], 5)
    assert w2 is not None and "5 canvases" in w2
    assert djvu_alignment_warning([], 3) is None


def _fake_canvas(index):
    from iiif_utils.core.manifest import Canvas
    return Canvas(index=index, canvas_id=f"c{index}", label=None,
                   image_id=None, image_service_url=None,
                   image_api_version=None, width=None, height=None,
                   alto_url=None, text_url=None, hocr_url=None)


def test_monolithic_ocr_branch_hocr(monkeypatch, tmp_path):
    """IA shape: whole-book hOCR URL in extra metadata → text_blocks rows."""
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    monkeypatch.setattr(ci.http_, "fetch_bytes",
                        lambda url, **kw: MONO_HOCR)
    canvases = [_fake_canvas(i) for i in range(3)]
    out = ci._parse_monolithic_ocr(
        {"ia_hocr_url": "https://archive.org/download/x/x_hocr.html"},
        canvases, cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    )
    assert out is not None
    tb_rows, image_dims, source, pw_rows = out
    assert source == "hocr"
    assert image_dims[0] == (1000, 1500)
    assert [r["page_id"] for r in tb_rows] == [0, 1]
    assert tb_rows[0]["text"] == "hello world"
    assert tb_rows[0]["block_type"] == "ocr_par"
    assert tb_rows[0]["avg_confidence"] == 91.0
    assert tb_rows[1]["block_type"] == "ocr_caption"


def test_monolithic_ocr_branch_djvu_fallback(monkeypatch, tmp_path):
    """hOCR absent → DjVu XML fallback drives the same row shape."""
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    monkeypatch.setattr(ci.http_, "fetch_bytes",
                        lambda url, **kw: MONO_DJVU)
    canvases = [_fake_canvas(i) for i in range(2)]
    out = ci._parse_monolithic_ocr(
        {"ia_djvu_xml_url": "https://archive.org/download/x/x_djvu.xml"},
        canvases, cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    )
    assert out is not None
    tb_rows, image_dims, source, pw_rows = out
    assert source == "djvu"
    assert len(tb_rows) == 1
    assert tb_rows[0]["text"] == "Smakula, Alexander"
    assert tb_rows[0]["bbox_y0"] == 993   # axis conversion survived ingest


def test_monolithic_ocr_branch_none_without_urls(tmp_path):
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    out = ci._parse_monolithic_ocr(
        {}, [_fake_canvas(0)], cfg_http={}, cache_dir=tmp_path,
        log=Logger(verbose=False),
    )
    assert out is None


def test_monolithic_ocr_drops_out_of_range_leaves(monkeypatch, tmp_path):
    """OCR pages beyond the canvas range are dropped with a warning."""
    from iiif_utils.commands import create_index as ci
    from iiif_utils.utils.logger import Logger
    monkeypatch.setattr(ci.http_, "fetch_bytes",
                        lambda url, **kw: MONO_HOCR)
    canvases = [_fake_canvas(0)]  # only leaf 0 exists
    out = ci._parse_monolithic_ocr(
        {"ia_hocr_url": "https://x/h.html"},
        canvases, cfg_http={}, cache_dir=tmp_path, log=Logger(verbose=False),
    )
    assert out is not None
    tb_rows, _dims, _source, _pw = out
    assert [r["page_id"] for r in tb_rows] == [0]


# --- WORD_GEOMETRY_PLAN: codec, layout modes, detection ------------------

def _w(text, x, y, w=40, h=30, conf=None, fsize=None):
    from iiif_utils.core.wordgeom import Word
    return Word(text=text, x=x, y=y, w=w, h=h, conf=conf, fsize=fsize)


def test_wordgeom_roundtrip():
    from iiif_utils.core.wordgeom import PageWords, decode, encode
    page = PageWords(
        words=[_w("Smakula,", 278, 993, 159, 36, conf=90, fsize=12),
               _w("Alexander", 450, 993, 150, 36, conf=80),
               _w("same", 700, 993, 90, 36)],
        words_per_line=[3],
    )
    out = decode(encode(page))
    assert [x.text for x in out.words] == ["Smakula,", "Alexander", "same"]
    assert (out.words[0].x, out.words[0].y) == (278, 993)
    assert (out.words[0].w, out.words[0].h) == (159, 36)
    assert out.words[0].conf == 90 and out.words[0].fsize == 12
    # None survives the sentinel round-trip, and isn't confused with 0
    assert out.words[1].fsize is None
    assert out.words[2].conf is None and out.words[2].fsize is None
    assert out.words_per_line == [3]
    assert len(out.lines()) == 1 and len(out.lines()[0]) == 3


def test_wordgeom_unicode_and_empty():
    from iiif_utils.core.wordgeom import PageWords, decode, encode
    page = PageWords(words=[_w("œuvre", 10, 10), _w("größer", 60, 10)],
                      words_per_line=[2])
    assert [x.text for x in decode(encode(page)).words] == ["œuvre", "größer"]
    empty = decode(encode(PageWords()))
    assert empty.words == [] and empty.words_per_line == []


def test_wordgeom_rejects_garbage():
    import pytest
    from iiif_utils.core.wordgeom import decode
    with pytest.raises(ValueError):
        decode(b"not zlib at all")


def test_wordgeom_clamps_out_of_range_coords():
    """Coords beyond uint16 are clamped, never silently wrapped."""
    from iiif_utils.core.wordgeom import PageWords, decode, encode
    page = PageWords(words=[_w("x", 70000, -5, 40, 30)], words_per_line=[1])
    out = decode(encode(page))
    assert out.words[0].x == 65535
    assert out.words[0].y == 0


def _poll_book_page():
    """A poll-book style table: OCR columnized it into vertical stacks.

    Two records across four columns. In OCR (document) order the words
    arrive column-by-column — every house number, then every name — which
    is exactly the failure WORD_GEOMETRY_PLAN §1 describes.
    """
    from iiif_utils.core.wordgeom import PageWords
    rows_y = [1000, 1060]
    cols = [("15", 100), ("Smakula,", 300), ("same", 700), ("Physicist", 900)]
    cols2 = [("15", 100), ("Smakula,", 300), ("same", 700), ("Chem.", 900)]
    words = []
    per_line = []
    # column-major emission: for each column, both rows' cells
    for i in range(4):
        for r, y in enumerate(rows_y):
            text, x = (cols if r == 0 else cols2)[i]
            words.append(_w(text, x, y, w=len(text) * 18, h=38))
            per_line.append(1)          # one token per line: the stack
    return PageWords(words=words, words_per_line=per_line)


def test_table_mode_reassembles_rows_from_columnized_ocr():
    """§7 fixture shape: the Smakula record must come back as one row."""
    from iiif_utils.core.layout import render_table
    out = render_table(_poll_book_page())
    assert out.layout == "table"
    assert out.quotable is False      # §3.4 — reconstructed, not transcribed
    assert out.lines[0] == "15 Smakula, same Physicist"
    assert out.lines[1] == "15 Smakula, same Chem."


def test_table_mode_survives_skew():
    """§7 regression: a synthetic slope must not fragment rows.

    The field report's ±22px failure was skew, not noise — deskew runs
    before clustering, so the rows still come back whole.
    """
    from iiif_utils.core.layout import render_table
    page = _poll_book_page()
    from iiif_utils.core.wordgeom import PageWords, Word
    slope = 0.02                       # ~1.1 degrees
    skewed = PageWords(
        words=[Word(text=wd.text, x=wd.x,
                     y=int(wd.y + slope * (wd.x + wd.w / 2)),
                     w=wd.w, h=wd.h, conf=wd.conf, fsize=wd.fsize)
               for wd in page.words],
        words_per_line=page.words_per_line,
    )
    out = render_table(skewed)
    assert out.lines[0] == "15 Smakula, same Physicist"
    assert out.lines[1] == "15 Smakula, same Chem."


def test_row_tolerance_self_calibrates():
    """§5: tolerance ≈ 0.7 × median word height, with a floor."""
    from iiif_utils.core.layout import row_tolerance
    words = [_w("a", 0, 0, h=38) for _ in range(5)]
    assert abs(row_tolerance(words) - 0.7 * 38) < 0.01
    tiny = [_w("a", 0, 0, h=2) for _ in range(5)]
    assert row_tolerance(tiny) == 6.0      # floor


def test_estimate_skew_recovers_known_slope():
    from iiif_utils.core.layout import estimate_skew
    slope = 0.02
    words = [_w("w", x, int(100 + slope * x), w=40, h=30)
             for x in range(0, 1200, 60)]
    assert abs(estimate_skew(words) - slope) < 0.005


def _braided_page():
    """Two-column prose that OCR braided: each line spans both columns."""
    from iiif_utils.core.wordgeom import PageWords
    words, per_line = [], []
    left = [["The", "patient", "was"], ["seen", "again", "in"]]
    right = [["Fever", "abated", "on"], ["the", "third", "day"]]
    for lrow, rrow in zip(left, right):
        n = 0
        for i, t in enumerate(lrow):
            words.append(_w(t, 100 + i * 120, 500 + 60 * len(per_line), w=100))
            n += 1
        for i, t in enumerate(rrow):
            words.append(_w(t, 900 + i * 120, 500 + 60 * len(per_line), w=100))
            n += 1
        per_line.append(n)
    return PageWords(words=words, words_per_line=per_line)


def test_columns_mode_unbraids_and_table_is_not_applied():
    from iiif_utils.core.layout import render_columns, render_raw
    page = _braided_page()
    # Raw keeps the braid — and is the only quotable rendering
    raw = render_raw(page)
    assert raw.quotable is True
    assert raw.lines[0] == "The patient was Fever abated on"
    # Columns splits at the gutter: left column first, then right
    out = render_columns(page, page_width=2000)
    assert out.quotable is False
    assert out.lines[:2] == ["The patient was", "seen again in"]
    assert out.lines[2:] == ["Fever abated on", "the third day"]


def test_columns_mode_never_splits_without_a_gutter():
    """No-regression rule (§5 columns 3): unsplittable stays braided."""
    from iiif_utils.core.layout import render_columns
    from iiif_utils.core.wordgeom import PageWords
    page = PageWords(
        words=[_w(t, 100 + i * 110, 500, w=100)
               for i, t in enumerate(["one", "two", "three", "four"])],
        words_per_line=[4],
    )
    out = render_columns(page, page_width=2000)
    assert out.lines == ["one two three four"]


def test_render_dispatch_and_unknown_layout():
    import pytest
    from iiif_utils.core.layout import render
    page = _braided_page()
    assert render(page, "raw").quotable is True
    assert render(page, "table").layout == "table"
    assert render(page, "columns", page_width=2000).layout == "columns"
    with pytest.raises(ValueError):
        render(page, "diagonal")


def test_detect_is_a_hint_with_signals():
    from iiif_utils.core.layout import detect
    hint = detect(_poll_book_page())
    assert hint.layout_hint == "table"
    assert 0.0 <= hint.confidence <= 1.0
    # Signals are reported so a human can audit the call (§5 detect)
    assert "left_edge_peaks" in hint.signals
    assert "stacked_frac" in hint.signals
    assert "width_cv" in hint.signals


def test_detect_never_auto_applies():
    """Configuration wins; contradiction is surfaced, not acted on (§3.3)."""
    import dataclasses
    from iiif_utils.core.layout import contradiction_warning, detect
    hint = detect(_poll_book_page())
    # §7: while the detector is uncalibrated it must stay silent — a
    # warning from an unvalidated classifier pushes users to the wrong
    # layout, the very failure this feature prevents.
    assert hint.calibrated is False
    assert contradiction_warning("columns", hint) is None

    # Once calibrated, a confident disagreement IS surfaced.
    calibrated = dataclasses.replace(hint, calibrated=True)
    warn = contradiction_warning("columns", calibrated)
    assert warn is not None and "configured" in warn
    assert "table" in warn
    # Agreement still produces no noise
    assert contradiction_warning("table", calibrated) is None


def test_hocr_parser_retains_word_geometry():
    from iiif_utils.core.hocr import parse_hocr_multipage
    pages = parse_hocr_multipage(MONO_HOCR)
    words = pages[0][1].words
    assert words is not None
    assert [wd.text for wd in words.words] == ["hello", "world"]
    assert (words.words[0].x, words.words[0].y) == (10, 20)
    assert words.words[0].w == 40 and words.words[0].h == 40
    assert words.words[0].conf == 95
    assert words.words_per_line == [2]


def test_djvu_parser_retains_word_geometry_with_converted_axis():
    from iiif_utils.core.djvu import parse_djvu_multipage
    pages = parse_djvu_multipage(MONO_DJVU)
    words = pages[0][1].words
    assert words is not None
    assert [wd.text for wd in words.words] == ["Smakula,", "Alexander"]
    # coords="278,1029,437,993" → x=278, y=993 (top), h=36
    assert (words.words[0].x, words.words[0].y) == (278, 993)
    assert words.words[0].h == 36
    assert words.words[0].conf == 90
    assert words.words[0].fsize is None     # DjVu has no font size
    assert words.words_per_line == [2]


def test_alto_parser_retains_word_geometry():
    page = alto.parse_alto_bytes(MINIMAL_ALTO)
    assert page.words is not None
    assert [wd.text for wd in page.words.words] == ["hello", "world"]
    assert (page.words.words[0].x, page.words.words[0].y) == (10, 20)
    assert page.words.words_per_line == [2]


def test_page_words_rows_written_by_ingest():
    """_rows_from_page emits a page_words row whenever geometry exists."""
    from iiif_utils.commands.create_index import _rows_from_page
    from iiif_utils.core.hocr import parse_hocr_multipage
    from iiif_utils.core.wordgeom import decode
    _leaf, page = parse_hocr_multipage(MONO_HOCR)[0]
    tb, il, dims, pw = [], [], {}, []
    _rows_from_page(0, page, default_block_type="ocr_par", tb_rows=tb,
                     il_rows=il, image_dims=dims, pw_rows=pw)
    assert len(pw) == 1 and pw[0]["page_id"] == 0
    assert [wd.text for wd in decode(pw[0]["blob"]).words] == ["hello", "world"]


def test_create_index_exposes_layout_flag():
    r = CliRunner().invoke(cli, ["create-index", "--help"])
    assert r.exit_code == 0
    assert "--layout" in r.output
    for mode in ("raw", "columns", "table"):
        assert mode in r.output


# --- Phase 3: IA catalog search + migration ------------------------------

def test_build_ia_query_filters_and_quoting():
    from iiif_utils.commands.search_catalog import build_ia_query
    q = build_ia_query(
        query="anatomy", year="1900-1950", creator='Gray, "Henry"',
        subject="Human anatomy", languages=("eng",),
        collections=("medicalheritagelibrary",), mediatype="texts",
        has_ocr=True,
    )
    assert "(anatomy)" in q
    assert 'creator:"Gray, \\"Henry\\""' in q          # quotes escaped
    assert 'subject:"Human anatomy"' in q
    assert 'language:"eng"' in q
    assert 'collection:"medicalheritagelibrary"' in q
    assert 'mediatype:"texts"' in q
    assert "date:[1900-01-01 TO 1950-12-31]" in q
    assert "ocr:*" in q
    # ia-utils' availability default: unreachable items excluded
    assert "NOT collection:printdisabled" in q
    assert "NOT indexflag:removed" in q


def test_build_ia_query_open_ended_years_and_empty():
    from iiif_utils.commands.search_catalog import build_ia_query
    kw = dict(query=None, creator=None, subject=None, languages=(),
              collections=(), mediatype=None, has_ocr=False)
    assert "date:[1900-01-01 TO *]" in build_ia_query(year="1900-", **kw)
    assert "date:[* TO 1950-12-31]" in build_ia_query(year="-1950", **kw)
    # No query at all still produces a valid match-all
    assert build_ia_query(year=None, **kw).startswith("*:*")


def test_summarize_ia_builds_usable_ref():
    """`ref` must be a details URL — bare IA ids are never auto-guessed."""
    from iiif_utils.commands.search_catalog import _summarize_ia
    row = _summarize_ia({
        "identifier": "anatomyofhumanbo1918gray",
        "title": "Anatomy of the human body",
        "creator": ["Gray, Henry", "Lewis, W. H."],
        "date": "1918-01-01T00:00:00Z",
        "language": "eng", "ocr": "tesseract 5.0", "downloads": 12,
    })
    assert row["id"] == "anatomyofhumanbo1918gray"
    assert row["year"] == "1918"
    assert row["creator"] == "Gray, Henry | Lewis, W. H."
    assert row["has_ocr"] is True
    assert row["ref"] == (
        "https://archive.org/details/anatomyofhumanbo1918gray")
    from iiif_utils.providers import _guess_provider
    assert _guess_provider(row["ref"], {"default_provider": "generic"}) == "ia"


def test_search_catalog_offers_ia_provider():
    r = CliRunner().invoke(cli, ["search-catalog", "--help"])
    assert r.exit_code == 0
    assert "ia" in r.output
    assert "--collection" in r.output


def _make_ia_utils_index(path):
    """Minimal ia-utils-dialect index: wide doc row, hocr_id PK, no
    index_metadata."""
    import sqlite3 as _sql
    c = _sql.connect(path)
    c.execute("CREATE TABLE document_metadata (id INTEGER PRIMARY KEY, "
              "slug TEXT, ia_identifier TEXT, title TEXT, "
              "creator_primary TEXT, publisher TEXT, publication_date TEXT)")
    c.execute("INSERT INTO document_metadata VALUES "
              "(1,'x','chargoog','Lectures','Charcot','New Syd.','1877')")
    c.execute("CREATE TABLE text_blocks (page_id INT, block_number INT, "
              "hocr_id TEXT PRIMARY KEY, block_type TEXT, language TEXT, "
              "text_direction TEXT, bbox_x0 INT, bbox_y0 INT, bbox_x1 INT, "
              "bbox_y1 INT, text TEXT, line_count INT, length INT, "
              "avg_confidence FLOAT, avg_font_size INT, "
              "parent_carea_id TEXT)")
    c.execute("INSERT INTO text_blocks VALUES (254,0,'par_1','ocr_par',NULL,"
              "NULL,10,20,110,60,'nervous system lectures',1,23,88.5,NULL,"
              "NULL)")
    c.execute("CREATE TABLE page_numbers (leaf_num INTEGER PRIMARY KEY, "
              "book_page_number TEXT, confidence INT, pageProb INT, "
              "wordConf INT)")
    c.execute("INSERT INTO page_numbers VALUES (254,'209',100,93,99)")
    c.commit()
    c.close()


def test_migrate_index_translates_dialect(tmp_path):
    import sqlite3 as _sql
    src = tmp_path / "old.sqlite"
    _make_ia_utils_index(src)
    before = src.read_bytes()

    r = CliRunner().invoke(cli, ["migrate-index", str(src)])
    assert r.exit_code == 0, r.output
    out = tmp_path / "old_iiif.sqlite"
    assert out.exists()
    # Non-destructive: the source is untouched
    assert src.read_bytes() == before

    c = _sql.connect(out)
    meta = {k: v for k, v in c.execute(
        "SELECT key, value FROM index_metadata")}
    assert meta["provider"] == "ia"
    assert meta["index_mode"] == "migrated"
    assert meta["migrated_tool"] == "ia-utils"
    assert "get-page unavailable" in meta["migration_limits"]
    assert meta["manifest_url"].endswith("chargoog/manifest.json")

    doc = {k: v for k, v in c.execute(
        "SELECT key, value FROM document_metadata")}
    assert doc["title"] == "Lectures"
    assert doc["identifier:ia"] == "chargoog"
    assert doc["creator"] == "Charcot"        # creator_primary → creator
    assert doc["ia_details_url"].endswith("/details/chargoog")

    tb = c.execute("SELECT * FROM text_blocks").fetchone()
    cols = [d[0] for d in c.execute("SELECT * FROM text_blocks").description]
    row = dict(zip(cols, tb))
    assert row["alto_id"] == "par_1"          # hocr_id → alto_id
    assert row["word_count"] == 3             # derived, absent in ia-utils
    assert row["avg_confidence"] == 88.5
    # page_numbers carried; image columns explicitly unavailable
    pn = dict(zip(
        [d[0] for d in c.execute("SELECT * FROM page_numbers").description],
        c.execute("SELECT * FROM page_numbers").fetchone()))
    assert pn["book_page_number"] == "209" and pn["pageProb"] == 93
    assert pn["image_service_url"] is None
    # FTS was built
    assert c.execute("SELECT count(*) FROM text_blocks_fts "
                     "WHERE text_blocks_fts MATCH 'nervous'").fetchone()[0] == 1


def test_migrate_index_refuses_to_clobber_source(tmp_path):
    src = tmp_path / "old.sqlite"
    _make_ia_utils_index(src)
    r = CliRunner().invoke(cli, ["migrate-index", str(src), "-o", str(src)])
    assert r.exit_code != 0
    assert "Refusing" in r.output


def test_migrate_index_rejects_already_migrated(tmp_path):
    import sqlite3 as _sql
    src = tmp_path / "already.sqlite"
    _make_ia_utils_index(src)
    c = _sql.connect(src)
    c.execute("CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT)")
    c.commit()
    c.close()
    r = CliRunner().invoke(cli, ["migrate-index", str(src)])
    assert r.exit_code != 0
    assert "iiif-utils index" in r.output


# --- parity gaps: naming, page stats, per-page text, image, refetch ------

def _ref(url, extra=None):
    from iiif_utils.providers import ManifestRef
    return ManifestRef(manifest_url=url, provider_key="x",
                        extra_metadata=extra or {})


def test_provider_identifier_prefers_stable_ids_over_title():
    """Index names key off the identifier, never the manifest label —
    titles vary between editions and get corrected over time."""
    from iiif_utils.commands.create_index import provider_identifier
    # Wellcome b-number straight out of the URL, child suffix preserved
    assert provider_identifier(_ref(
        "https://iiif.wellcomecollection.org/presentation/b22396147"
    )) == "b22396147"
    assert provider_identifier(_ref(
        "https://iiif.wellcomecollection.org/presentation/b22396147_0003"
    )) == "b22396147_0003"
    # Provider-supplied identifiers
    assert provider_identifier(_ref(
        "https://iiif.archive.org/iiif/graybook/manifest.json",
        {"identifier:ia": "anatomyofhumanbo1918gray"},
    )) == "anatomyofhumanbo1918gray"
    assert provider_identifier(_ref(
        "https://x/y", {"identifier:bsb": "bsb00056329"})) == "bsb00056329"
    # Fallback: slugified URL, bounded
    out = provider_identifier(_ref("https://example.org/some/deep/manifest"))
    assert out and len(out) <= 40


def test_parse_leaf_spec_shared():
    from iiif_utils.utils.page import parse_leaf_spec
    assert parse_leaf_spec("3") == [3]
    assert parse_leaf_spec("1-5,10") == [1, 2, 3, 4, 5, 10]
    assert parse_leaf_spec("1-3,2-4") == [1, 2, 3, 4]
    assert parse_leaf_spec("8-12", 10) == [8, 9, 10]     # clamped
    assert parse_leaf_spec("8-12") == [8, 9, 10, 11, 12]  # unbounded
    assert parse_leaf_spec("") == []


def _stats_index(path):
    import sqlite3 as _sql
    c = _sql.connect(path)
    c.execute("CREATE TABLE text_blocks (page_id INT, block_number INT, "
              "block_type TEXT, bbox_x0 INT, bbox_y0 INT, bbox_x1 INT, "
              "bbox_y1 INT, text TEXT, line_count INT, word_count INT, "
              "length INT, avg_confidence FLOAT)")
    # Three dense prose pages and one sparse plate page
    for leaf in (0, 1, 2):
        for b in range(6):
            c.execute("INSERT INTO text_blocks VALUES "
                      "(?,?,'ocr_par',0,0,10,10,?,4,20,120,90.0)",
                      (leaf, b, "word " * 20))
    c.execute("INSERT INTO text_blocks VALUES "
              "(3,0,'ocr_par',0,0,10,10,'Fig. 42',1,2,7,60.0)")
    c.execute("CREATE TABLE page_numbers (leaf_num INTEGER PRIMARY KEY, "
              "book_page_number TEXT)")
    for leaf, page in ((0, "1"), (1, "2"), (2, "3"), (3, "4")):
        c.execute("INSERT INTO page_numbers VALUES (?,?)", (leaf, page))
    c.commit()
    c.close()


def test_get_page_stats_and_figure_heuristic(tmp_path):
    import json as _json
    idx = tmp_path / "stats.sqlite"
    _stats_index(idx)

    r = CliRunner().invoke(cli, ["get-page-stats", "-i", str(idx),
                                  "--format", "json"])
    assert r.exit_code == 0, r.output
    rows = _json.loads(r.output)
    assert len(rows) == 4
    assert rows[0]["blocks"] == 6 and rows[0]["words"] == 120
    assert rows[0]["page"] == "1"

    # The sparse plate page is the only figure candidate
    r2 = CliRunner().invoke(cli, ["get-page-stats", "-i", str(idx),
                                   "--figures", "--format", "json"])
    assert r2.exit_code == 0, r2.output
    figs = _json.loads(r2.output)
    assert [f["leaf"] for f in figs] == [3]

    # Leaf selection
    r3 = CliRunner().invoke(cli, ["get-page-stats", "-i", str(idx),
                                   "-l", "1-2", "--format", "json"])
    assert [f["leaf"] for f in _json.loads(r3.output)] == [1, 2]


def test_get_page_stats_rejects_both_selectors(tmp_path):
    idx = tmp_path / "stats.sqlite"
    _stats_index(idx)
    r = CliRunner().invoke(cli, ["get-page-stats", "-i", str(idx),
                                  "-l", "1", "-b", "2"])
    assert r.exit_code != 0


def test_get_text_per_page_from_index(tmp_path):
    import json as _json
    idx = tmp_path / "stats.sqlite"
    _stats_index(idx)
    # By leaf, aggregated
    r = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "-l", "3",
                                  "--format", "json"])
    assert r.exit_code == 0, r.output
    rows = _json.loads(r.output)
    assert rows[0]["leaf"] == 3 and "Fig. 42" in rows[0]["text"]
    # By printed page
    r2 = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "-b", "4",
                                   "--format", "json"])
    assert _json.loads(r2.output)[0]["leaf"] == 3
    # --blocks gives per-block records with bbox + confidence
    r3 = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "-l", "3",
                                   "--blocks", "--format", "json"])
    blk = _json.loads(r3.output)[0]
    assert blk["block"] == 0 and blk["bbox"] == [0, 0, 10, 10]
    assert blk["confidence"] == 60.0


def test_get_text_per_page_usage_errors(tmp_path):
    idx = tmp_path / "stats.sqlite"
    _stats_index(idx)
    # -l without an index
    r = CliRunner().invoke(cli, ["get-text", "-l", "3"])
    assert r.exit_code != 0 and "INDEX" in r.output
    # --blocks outside per-page mode
    r2 = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "--blocks"])
    assert r2.exit_code != 0
    # both selectors
    r3 = CliRunner().invoke(cli, ["get-text", "-i", str(idx),
                                   "-l", "1", "-b", "2"])
    assert r3.exit_code != 0


def test_process_image_autocontrast_and_implication():
    import io as _io
    from PIL import Image as _Image
    from iiif_utils.core.image import process_image, wants_processing

    # A low-contrast scan: all values squeezed into 100-120 rather than
    # spanning 0-255. Autocontrast should stretch that range back out.
    img = _Image.new("L", (40, 40), 100)
    for x in range(40):
        for y in range(40):
            img.putpixel((x, y), 100 + (x % 21))
    src = _io.BytesIO()
    img.save(src, format="PNG")
    raw = src.getvalue()
    assert img.getextrema() == (100, 120)

    assert wants_processing(autocontrast=True, cutoff=None,
                            preserve_tone=False, quality=None)
    assert not wants_processing(autocontrast=False, cutoff=None,
                                 preserve_tone=False, quality=None)
    # --cutoff alone implies autocontrast (it is meaningless otherwise)
    assert wants_processing(autocontrast=False, cutoff=5,
                            preserve_tone=False, quality=None)

    out = process_image(raw, output_format="png", autocontrast=True)
    assert out != raw
    stretched = _Image.open(_io.BytesIO(out))
    assert stretched.size == (40, 40)
    # The squeezed 100-120 band now spans (nearly) the full range
    lo, hi = stretched.getextrema()
    assert hi - lo > 200, f"autocontrast did not stretch: {lo}-{hi}"


def test_process_image_jp2_passthrough_and_rgba_flatten():
    import io as _io
    from PIL import Image as _Image
    from iiif_utils.core.image import process_image
    # JP2 with nothing to do must not be re-encoded (Pillow can't write it)
    assert process_image(b"\x00fake-jp2", output_format="jp2") == b"\x00fake-jp2"
    # RGBA → JPEG flattens onto white instead of raising
    buf = _io.BytesIO()
    _Image.new("RGBA", (10, 10), (255, 0, 0, 128)).save(buf, format="PNG")
    out = process_image(buf.getvalue(), output_format="jpg", quality=80)
    assert _Image.open(_io.BytesIO(out)).mode == "RGB"


def test_get_page_exposes_image_processing_flags():
    r = CliRunner().invoke(cli, ["get-page", "--help"])
    for flag in ("--autocontrast", "--cutoff", "--preserve-tone",
                  "--quality"):
        assert flag in r.output


def test_rebuild_index_refetch_guards(tmp_path):
    """--refetch must refuse rather than wipe text it can't replace."""
    import sqlite3 as _sql
    idx = tmp_path / "x.sqlite"
    c = _sql.connect(idx)
    c.execute("CREATE TABLE text_blocks (page_id INT, block_number INT, "
              "text TEXT)")
    c.commit()
    c.close()
    # No index_metadata at all
    r = CliRunner().invoke(cli, ["rebuild-index", str(idx), "--refetch"])
    assert r.exit_code != 0 and "migrate-index" in r.output

    c = _sql.connect(idx)
    c.execute("CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT INTO index_metadata VALUES ('index_mode','image_only')")
    c.execute("INSERT INTO index_metadata VALUES ('manifest_url','https://x/m')")
    c.commit()
    c.close()
    r2 = CliRunner().invoke(cli, ["rebuild-index", str(idx), "--refetch"])
    assert r2.exit_code != 0 and "--no-ocr" in r2.output


def test_rebuild_index_default_needs_no_network(tmp_path):
    import sqlite3 as _sql
    idx = tmp_path / "y.sqlite"
    c = _sql.connect(idx)
    c.execute("CREATE TABLE text_blocks (page_id INT, block_number INT, "
              "text TEXT)")
    c.execute("INSERT INTO text_blocks VALUES (0,0,'hello world')")
    c.commit()
    c.close()
    r = CliRunner().invoke(cli, ["rebuild-index", str(idx)])
    assert r.exit_code == 0, r.output
    assert "FTS rebuilt" in r.output


def _addressing_index(path):
    """Index exercising the hard page-addressing cases: roman front
    matter, a plate label, and two leaves claiming the same page."""
    import sqlite3 as _sql
    c = _sql.connect(path)
    c.execute("CREATE TABLE text_blocks (page_id INT, block_number INT, "
              "block_type TEXT, bbox_x0 INT, bbox_y0 INT, bbox_x1 INT, "
              "bbox_y1 INT, text TEXT, line_count INT, word_count INT, "
              "length INT, avg_confidence FLOAT)")
    c.execute("CREATE TABLE page_numbers (leaf_num INTEGER PRIMARY KEY, "
              "book_page_number TEXT)")
    for leaf, page in ((0, "i"), (1, "ii"), (2, "xii"), (3, "1"),
                        (4, "2"), (5, "1"), (6, "12a")):
        c.execute("INSERT INTO page_numbers VALUES (?,?)", (leaf, page))
        c.execute("INSERT INTO text_blocks VALUES "
                  "(?,0,'ocr_par',0,0,9,9,?,1,3,12,90.0)",
                  (leaf, f"text of leaf {leaf}"))
    c.commit()
    c.close()


def test_parse_book_spec_handles_non_numeric_labels():
    """Printed pages are TEXT: roman front matter, plate suffixes."""
    from iiif_utils.utils.page import parse_book_spec
    assert parse_book_spec("xii") == ["xii"]
    assert parse_book_spec("12a") == ["12a"]
    assert parse_book_spec("i,ii,xii") == ["i", "ii", "xii"]
    # Numeric ranges still expand
    assert parse_book_spec("100-103") == ["100", "101", "102", "103"]
    assert parse_book_spec("5,7-9") == ["5", "7", "8", "9"]
    # Mixed: range expands, label passes through
    assert parse_book_spec("1-2,xii") == ["1", "2", "xii"]
    # A hyphenated non-numeric token is a label, not a range
    assert parse_book_spec("A-1") == ["A-1"]
    assert parse_book_spec("") == []


def test_book_addressing_accepts_roman_numerals(tmp_path):
    """Regression: -b xii used to crash with a raw ValueError."""
    import json as _json
    idx = tmp_path / "addr.sqlite"
    _addressing_index(idx)
    r = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "-b", "xii",
                                  "--format", "json"])
    assert r.exit_code == 0, r.output
    assert _json.loads(r.output)[0]["leaf"] == 2
    r2 = CliRunner().invoke(cli, ["get-page-stats", "-i", str(idx),
                                   "-b", "i,12a", "--format", "json"])
    assert r2.exit_code == 0, r2.output
    assert [x["leaf"] for x in _json.loads(r2.output)] == [0, 6]


def test_leaf_spec_rejects_non_numeric_with_guidance(tmp_path):
    idx = tmp_path / "addr.sqlite"
    _addressing_index(idx)
    r = CliRunner().invoke(cli, ["get-text", "-i", str(idx), "-l", "xii"])
    assert r.exit_code != 0
    assert "not a leaf number" in r.output and "--book" in r.output


def test_ambiguous_printed_page_refuses(tmp_path):
    """Two leaves carrying page '1' must not silently resolve to one."""
    import sqlite3 as _sql
    import pytest as _pt
    from iiif_utils.utils.page import resolve_leaf
    idx = tmp_path / "addr.sqlite"
    _addressing_index(idx)
    conn = _sql.connect(idx)
    conn.row_factory = _sql.Row
    # Unambiguous pages still resolve
    assert resolve_leaf(conn, None, "xii") == 2
    assert resolve_leaf(conn, None, "2") == 4
    # Explicit leaf always wins
    assert resolve_leaf(conn, 5, None) == 5
    with _pt.raises(click.ClickException) as exc:
        resolve_leaf(conn, None, "1")
    msg = str(exc.value)
    assert "ambiguous" in msg and "3, 5" in msg and "--leaf" in msg


def test_leaf_book_flags_are_consistent_across_commands():
    """Every page-addressing command uses -l/--leaf and -b/--book."""
    for cmd in ("get-page", "get-text", "get-page-stats", "get-figure",
                 "get-region", "ocr-page", "get-info", "render-page"):
        out = CliRunner().invoke(cli, [cmd, "--help"]).output
        assert "-l, --leaf" in out, f"{cmd} lacks -l/--leaf"
        assert "-b, --book" in out, f"{cmd} lacks -b/--book"


def test_alto_minimal_parse():
    page = alto.parse_alto_bytes(MINIMAL_ALTO)
    assert page.measurement_unit == "pixel"
    assert page.page_w == 1000 and page.page_h == 2000
    assert len(page.text_blocks) == 1
    b = page.text_blocks[0]
    assert b.text == "hello world"
    assert b.bbox_x0 == 10 and b.bbox_y1 == 70
    assert b.line_count == 1 and b.word_count == 2
    assert len(page.illustrations) == 1
    ill = page.illustrations[0]
    assert ill.illustration_type == "Illustration"
    assert (ill.bbox_x0, ill.bbox_y0, ill.bbox_x1, ill.bbox_y1) == (500, 800, 800, 1200)
