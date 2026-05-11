"""Smoke tests — no network. Validate pure-function modules and CLI shell."""
from __future__ import annotations

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
    for cmd in ("info", "list-files", "create-index", "search-index",
                 "get-page", "get-figure", "get-region", "get-text",
                 "get-url", "list-figures"):
        assert cmd in r.output


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
