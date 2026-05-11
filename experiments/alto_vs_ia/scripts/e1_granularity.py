"""E1 — TextBlock vs TextLine granularity.

For each sampled ALTO file count blocks/lines/words and measure mean text
length at each level. Hypothesis from a single-page probe: a Wellcome ALTO
TextBlock is a coarse layout region (column / column-fragment), not a
paragraph, so TextBlock-as-row would give very few, very long blocks.
Check across the 30-sample corpus.

Writes ../results/e1_granularity.{md,json}.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

ALTO_NS = "http://www.loc.gov/standards/alto/ns-v2#"
NS = {"a": ALTO_NS}


def text_of_line(line: etree._Element) -> str:
    """Reconstruct a TextLine's text from its <String> CONTENT attrs."""
    parts: list[str] = []
    for child in line:
        tag = etree.QName(child).localname
        if tag == "String":
            c = child.get("CONTENT")
            if c is not None:
                parts.append(c)
        elif tag == "SP":
            parts.append(" ")
        elif tag == "HYP":
            # Hyphenation marker; keep the content but no extra space.
            c = child.get("CONTENT")
            if c is not None:
                parts.append(c)
    return " ".join(p for p in (" ".join(parts).split()) if p)


def text_of_block(block: etree._Element) -> str:
    """Concatenate all child TextLines."""
    lines = [text_of_line(l) for l in block.findall("a:TextLine", NS)]
    return " ".join(t for t in lines if t)


def analyze_file(path: Path) -> dict:
    tree = etree.parse(str(path))
    root = tree.getroot()
    page = root.find(".//a:Page", NS)
    page_w = int(page.get("WIDTH", 0)) if page is not None else 0
    page_h = int(page.get("HEIGHT", 0)) if page is not None else 0
    page_area = page_w * page_h

    blocks = root.findall(".//a:TextBlock", NS)
    block_lens = [len(text_of_block(b)) for b in blocks]

    lines = root.findall(".//a:TextLine", NS)
    line_lens = [len(text_of_line(l)) for l in lines]

    strings = root.findall(".//a:String", NS)
    illustrations = root.findall(".//a:Illustration", NS)
    graphical = root.findall(".//a:GraphicalElement", NS)
    composed = root.findall(".//a:ComposedBlock", NS)

    # Bbox coverage at TextBlock level
    covered = 0
    for b in blocks:
        try:
            w = int(b.get("WIDTH", 0))
            h = int(b.get("HEIGHT", 0))
            covered += w * h
        except (TypeError, ValueError):
            pass

    # Confidence — sample first 50 Strings to see if WC is populated
    wc_present = sum(1 for s in strings[:50] if s.get("WC") is not None)

    return {
        "file": path.name,
        "page_w": page_w,
        "page_h": page_h,
        "n_textblocks": len(blocks),
        "n_textlines": len(lines),
        "n_strings": len(strings),
        "n_illustrations": len(illustrations),
        "n_graphical_elements": len(graphical),
        "n_composed_blocks": len(composed),
        "block_text_lens": block_lens,
        "line_text_lens": line_lens,
        "mean_block_len": (statistics.mean(block_lens) if block_lens else 0),
        "mean_line_len": (statistics.mean(line_lens) if line_lens else 0),
        "median_block_len": (statistics.median(block_lens) if block_lens else 0),
        "median_line_len": (statistics.median(line_lens) if line_lens else 0),
        "bbox_coverage_ratio": (covered / page_area) if page_area else 0,
        "wc_present_in_first_50_strings": wc_present,
    }


def main() -> None:
    samples_path = DATA / "samples.json"
    samples = json.loads(samples_path.read_text())
    alto_samples = [s for s in samples if s.get("alto_url")]
    print(f"Analyzing {len(alto_samples)} ALTO files...")

    rows: list[dict] = []
    for s in alto_samples:
        path = ROOT / s["alto_path"]
        try:
            r = analyze_file(path)
            r["volume"] = s["volume"]
            r["canvas_index"] = s["canvas_index"]
            rows.append(r)
        except Exception as e:
            print(f"  {path.name}: ERROR {e}")

    # Aggregate
    def col(name: str) -> list:
        return [r[name] for r in rows]

    def summ(name: str) -> dict:
        vals = col(name)
        return {
            "min": min(vals),
            "max": max(vals),
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
        }

    agg = {
        "n_samples": len(rows),
        "textblocks_per_page":   summ("n_textblocks"),
        "textlines_per_page":    summ("n_textlines"),
        "strings_per_page":      summ("n_strings"),
        "illustrations_per_page":summ("n_illustrations"),
        "mean_block_len_chars":  summ("mean_block_len"),
        "mean_line_len_chars":   summ("mean_line_len"),
        "bbox_coverage_ratio":   summ("bbox_coverage_ratio"),
    }
    all_block_lens = [v for r in rows for v in r["block_text_lens"]]
    all_line_lens = [v for r in rows for v in r["line_text_lens"]]
    wc_total = sum(r["wc_present_in_first_50_strings"] for r in rows)

    agg["all_block_lens_histogram"] = {
        "n": len(all_block_lens),
        "p50": (statistics.median(all_block_lens) if all_block_lens else 0),
        "p90": (sorted(all_block_lens)[int(0.9 * len(all_block_lens))]
                 if all_block_lens else 0),
        "max": (max(all_block_lens) if all_block_lens else 0),
    }
    agg["all_line_lens_histogram"] = {
        "n": len(all_line_lens),
        "p50": (statistics.median(all_line_lens) if all_line_lens else 0),
        "p90": (sorted(all_line_lens)[int(0.9 * len(all_line_lens))]
                 if all_line_lens else 0),
        "max": (max(all_line_lens) if all_line_lens else 0),
    }
    agg["WC_confidence_attribute_present"] = wc_total > 0
    agg["WC_count_in_first_50_strings_per_page_total"] = wc_total

    (RESULTS / "e1_granularity.json").write_text(json.dumps(
        {"samples": rows, "aggregate": agg}, indent=2))

    # Markdown report
    md = ["# E1 — TextBlock vs TextLine granularity (Wellcome ALTO, Spalteholz)",
          "",
          f"**Samples:** {agg['n_samples']} ALTO files, evenly spaced across all"
          " 3 volumes of `b31362126`.",
          "",
          "## Per-page counts",
          "",
          "| Element | min | median | mean | max |",
          "|---|---:|---:|---:|---:|"]
    for label, key in [
        ("TextBlock", "textblocks_per_page"),
        ("TextLine", "textlines_per_page"),
        ("String (word)", "strings_per_page"),
        ("Illustration", "illustrations_per_page"),
    ]:
        s = agg[key]
        md.append(f"| {label} | {s['min']} | {s['median']} | {s['mean']} | {s['max']} |")

    md += [
        "",
        "## Text length per row",
        "",
        "Lengths in characters of the reconstructed text per element.",
        "",
        "| Granularity | rows | p50 | p90 | max |",
        "|---|---:|---:|---:|---:|",
        f"| TextBlock-per-row | {agg['all_block_lens_histogram']['n']} |"
        f" {agg['all_block_lens_histogram']['p50']} |"
        f" {agg['all_block_lens_histogram']['p90']} |"
        f" {agg['all_block_lens_histogram']['max']} |",
        f"| TextLine-per-row | {agg['all_line_lens_histogram']['n']} |"
        f" {agg['all_line_lens_histogram']['p50']} |"
        f" {agg['all_line_lens_histogram']['p90']} |"
        f" {agg['all_line_lens_histogram']['max']} |",
        "",
        "## Bbox coverage",
        "",
        f"Sum of TextBlock bbox areas / page area: median "
        f"{agg['bbox_coverage_ratio']['median']:.3f}, "
        f"mean {agg['bbox_coverage_ratio']['mean']:.3f}.",
        "",
        "## Word-level confidence (`WC` attribute on `<String>`)",
        "",
        f"Across all {agg['n_samples']} sampled pages, the first-50-Strings "
        f"WC-attribute count was {agg['WC_count_in_first_50_strings_per_page_total']}. "
        f"WC present anywhere in sample: **{agg['WC_confidence_attribute_present']}**.",
        "",
        "## Per-file detail",
        "",
        "| volume | canvas | TBs | TLs | Strs | Illus | mean-block-len | mean-line-len |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| {r['volume']} | {r['canvas_index']} | {r['n_textblocks']} |"
            f" {r['n_textlines']} | {r['n_strings']} | {r['n_illustrations']} |"
            f" {r['mean_block_len']:.0f} | {r['mean_line_len']:.0f} |")

    (RESULTS / "e1_granularity.md").write_text("\n".join(md) + "\n")
    print(f"Wrote {RESULTS / 'e1_granularity.md'}")
    print(f"      {RESULTS / 'e1_granularity.json'}")
    print()
    print("Headline:")
    print(f"  median TextBlocks/page: {agg['textblocks_per_page']['median']}")
    print(f"  median TextLines/page:  {agg['textlines_per_page']['median']}")
    print(f"  median block-len chars: {agg['all_block_lens_histogram']['p50']}")
    print(f"  median line-len chars:  {agg['all_line_lens_histogram']['p50']}")
    print(f"  WC present: {agg['WC_confidence_attribute_present']}")


if __name__ == "__main__":
    main()
