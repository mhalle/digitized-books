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
                 "get-page", "get-pages", "get-pdf",
                 "get-figure", "get-region", "get-text", "get-url",
                 "list-figures", "ocr-page"):
        assert cmd in r.output


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
