# A curated public-domain anatomy corpus for LLM indexing

This is a working corpus plan: landmark and broadly-useful anatomy works that
are public domain in the US (`pre-1929` rule) or under PDM in Europe, with
emphasis on works that have both readable prose and substantive illustration,
and where ALTO OCR is available we prefer those scans.

Conventions
- **Wellcome ID**: 8-char work ID; resolve as `https://wellcomecollection.org/works/<id>`
- **lic**: `pdm` = Wellcome's Public Domain Mark; `inc` = Wellcome marks "in copyright" but the work is in fact PD in the US — see "PD override" notes
- **OCR**: ALTO availability per Wellcome's older scanning pipeline. Most Wellcome IIIF v2 manifests served from `wellcomelibrary.org` legacy expose ALTO via `seeAlso`; v3 manifests at `iiif.wellcomecollection.org` may or may not.
- **★ pick**: the recommended single edition to ingest. **Other editions of the same work are listed for reference but should not be ingested** — see "On choosing one edition per work" below.

## On choosing one edition per work

Successive editions of the same textbook share 70–95% of their text. Ingesting all of them feeds the LLM near-duplicate sentences with cosmetic variation: embedding clusters degenerate, retrieval returns the same content five times for any query, and the corpus burns disk and OCR cost without adding information.

**Pick one edition per textbook.** Default to the latest pre-1929 edition that's both clearly PD in the US and falls within the original author's lifetime or an authorized revision; that gives you the most polished prose with the cleanest rights provenance. The picks marked ★ in the tables below follow this rule.

**Where multiple editions/volumes DO add value** and should all be kept:

- **Different works by the same author.** Cajal's 1894 *Les nouvelles idées* and his 1909-11 *Histologie du système nerveux* are different texts at different career stages.
- **Volumes of a multi-volume work.** Henle's six-volume *Handbuch* (Knochen, Bänder, Muskel, Eingeweide, Gefäss, Nerven), Bardeleben's chapter-volumes (Holl, Krause, Tandler, Bartels…), Quain's, and Sappey's *Traité* each have multiple volumes which together comprise the whole work — keep them all.
- **Significantly different states of the same work.** Vesalius 1543 vs. 1555 (different woodcut states, scholarly significance to both); Edinger's 1885 vs. 1911 *Vorlesungen* (genuinely different states of his neuroanatomy thinking).
- **Different translations.** Sobotta in German vs. McMurrich's English translation — both useful for cross-language queries.

The heuristic: same author + same title (modulo "Nth ed") = pick one. Same author + different titles = keep all. Same multi-volume work = keep all volumes.

Following this rule cuts the corpus by roughly 30–40% with essentially zero loss of useful information.

## Tier 1 — core textbook backbone (early 20th c, Anglophone, US PD)

These are the workhorses. Long-form prose, comprehensive coverage of human gross anatomy in roughly modern terminology (BNA-aligned), substantial illustration, and most have ALTO OCR.

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Morris's Human Anatomy, 5th ed (Jackson, ed.) | `ad56hqjs` | 1914 | pdm | Multi-author US treatise. Already validated; ALTO confirmed; we built the Clark lymphatic chapter PDF from it. |
| | Morris's Human Anatomy, 4th ed (Morris, ed.) | `p9798mqw` / `cvrwpkdu` | 1898 | pdm | British original. Skip in favor of the 5th unless you specifically need the pre-Americanised text. |
| ★ | Cunningham's Text-book of Anatomy, 4th ed (Robinson rev.) | `cfn934u3` | 1914 | pdm | The British counterpart to Morris's. Latest pre-WWI mature edition. |
| | Cunningham's Text-book, 1st ed | `wxh98zsn` | 1902 | inc → PD override | Earlier; skip. |
| | Cunningham's Text-book, partial | `ppy5p9uc` | 1906 | inc → PD override | Section 2 only — skip. |
| ★ | Cunningham's Manual of Practical Anatomy (Robinson rev., 6th ed.) | `kw6vt8gv` | 1914 | inc → PD override: pre-1929 US PD | Dissection-room companion. The Manual is a **2-volume work** (Vol. 1: limbs; Vol. 2: thorax/abdomen/head/neck/brain), and the Wellcome IIIF manifest **contains both volumes concatenated as a single sequence** (752 canvases, with two "Cover" structural ranges marking the volume break). When ingesting, identify the boundary by the second "Cover" range. The 1920 BHL edition (BHL title 30040) is a close alternative if you want the post-WWI revision. |
| | Cunningham's Manual, earlier scanned eds | `eax5b5u2` (1907 4th, 644 canvases) / `m9e7nadd` (1912 5th, 726 canvases) | | mixed | Same 2-vol-concatenated structure. Skip. |
| | Cunningham's Manual, 1893–1903 records | `cnk4dsek` (1889 2nd), `t6m83dvf`/`m6beaqws` (1893–94 1st), `ekyc32zt` (1903 3rd) | | pdm | **Bibliographic-only records — no digitized scan.** Wellcome lists them as online but the IIIF manifest has 0 canvases. Skip. |
| ★ | Piersol's Human Anatomy | `mvaqfjxm` | 1918 | pdm | Major American multi-volume textbook. |
| ★ | Gerrish's Text-book of Anatomy | `dsgx7nzq` / `b3t55k5x` | 1899 | pdm | American multi-author text. |
| ★ | Quain's Elements of Anatomy, 11th ed | `gw75hbbr` | 1908 | cc-by-nc (work itself PD) | Latest pre-1929 edition; comprehensive multi-volume. |
| | Quain's, 8th ed | `jcsn4x8q` | 1890–96 | pdm | Skip in favor of the 11th. |
| | Quain's, 7th ed | `napwfjw9` | 1876 | pdm | Skip. |

**Gap**: a single-volume pre-1929 American Gray's. Wellcome only has 19th-c British editions; the 1918 *Anatomy of the Human Body* (Lewis revision, the famous "Bartleby Gray's") is not on Wellcome. Easily sourced from Internet Archive / Bartleby. **Flag for external ingest.**

## Tier 2 — 19th c regional / dissection / surface anatomy

These are the Victorian dissection-room and topographic-anatomy classics. Smaller, more practical, often with clean OCR because they're typeset in straightforward serif fonts.

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Holden's Manual of the Dissection of the Human Body | `cafpy896` (latest of the available eds; verify edition number) | 1880s+ | pdm | Pick a mature edition with clean OCR. Other PD eds: `acpnj5jn` (1851 1st), `v3dmsd5a`, `kh84m29d`, `cphszmge`. |
| ★ | Ellis's Demonstrations of Anatomy | `dzmjbt9h` | 1887 | pdm | Latest of the 19th-c eds with clean scan. Earlier eds (1852, 1861, 1882) and 1890 also PD on Wellcome — skip. |
| ★ | Gray, *Anatomy descriptive and surgical*, 11th UK ed | `jev9kze2` / `hsck94k8` | 1883 | pdm | The mature Victorian British Gray's. The 1858 1st ed (`tbr7z7kv`) has historical interest but skip in favor of the 11th — you'll have the 1918 American Gray's separately. |

## Tier 3 — atlases (image-heavy, captions in multiple languages)

For atlases the OCR value is in captions and indices; the corpus value is in plates plus the labelled-figure → anatomical-term mapping. **Atlases especially need single-edition discipline** — the same plates get reprinted from edition to edition, only captions and added figures change.

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Spalteholz, *Hand-Atlas* (English), late ed | `d8quuwxg` | 1929/30 | pdm | Last clearly US-PD English Spalteholz; the standard reference edition. Earlier eds skip: `whnrufza` (1900 3rd), `utb2vtpd` (1906? 4th). |
| ★ | Sobotta, *Atlas of Human Anatomy* (English, McMurrich tr.) | `kdckv24y` | 1927–28 | pdm | English McMurrich translation makes captions accessible without German. |
| | Sobotta, *Atlas der deskriptiven Anatomie* (German) | `dy48h43b` (1926–28) | 1926–28 | pdm | Skip if you have the McMurrich English; keep ONE German if you want bilingual indexing. Other German eds (`kkyzwwjs` 1919–20, `h9fafua2` 1922) — skip. |
| ★ | Toldt, *Anatomischer Atlas*, latest pre-1929 | `tgekje3p` | 1919–20 | pdm | Pick the latest. Earlier eds (`u6sgj27q` 1900, `ruxbq7j8` 1903, `snc7atr4` 1914) — skip. |
| ★ | Bourgery & Jacob, *Traité complet de l'anatomie* | `p747b7vs` (Wellcome); Heidelberg `bourgery1831ga` (hub) | 1831–54 | pdm | The 8-volume French illustrated treatise (text + 700+ hand-colored lithographs by N.H. Jacob). **Earlier CORPUS draft incorrectly described as "plates only"** — Wellcome serves the work as 14 child manifests covering ~5,140 canvases of both prose volumes (Tome 1–6 text) and plate volumes (Tome 1–8 atlases). **Wellcome ALTO is structurally broken** (every ALTO URL returns 500) so Wellcome indexes are image-only (`create-index --no-ocr`, 14 sqlites under `p747b7vs_v1..v14`). **Heidelberg has the matching 1st edition with clean ALTO** — 8 text vols (`bourgery1832bd1_1` ... `bourgery1854bd8_1` plus the typo-spelled `bourgey1832bd1_1`) and 8 atlas vols (`bourgey1831bd1_2` ... `bourgey1844bd8_2`); the atlas vols carry the colored chromolithographs in higher fidelity than Wellcome's grayscale scans. Use the Heidelberg indexes for FTS and the colored plate images; the Wellcome indexes remain as a second-copy reference. ~1,032 "Planche N" labeled canvases across the 8 Heidelberg atlas vols (~1,225 plate canvases adjusting for Bd. 3's letter-only labeling), ~15.1M chars of French OCR across the text vols. |

## Tier 4 — early modern foundational works (Tier 4 because heavy in Latin and visual)

These are essential historically but harder to use as LLM-indexable text because of Latin, period typography (long-s, blackletter, etc.) and OCR difficulty. Worth ingesting, but expect OCR cleanup work.

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Vesalius, *Epitome* | `g6b6smge` | 1543 | pdm | Companion abridgement to the *Fabrica*. Distinct work from the *Fabrica* itself — keep. **No ALTO on Wellcome** (pre-1600 woodcut Latin defeats ABBYY); see "OCR / ALTO availability" below. |
| ★ | Valverde, *Historia de la composicion del cuerpo humano* | `nrtzmcfn` | 1556 | pdm | Pick the cleaner-scan record (verify between `nrtzmcfn` and `dc5q26zu`). **No ALTO on Wellcome** — same reason. |
| ★ | Crooke, *Mikrokosmographia* | `resfyxts` | 1618 | pdm | First major English-language anatomy. The 1651 ed (`hxp9yd6a`) — skip unless 1618 OCR is unusable. |
| ★ | Cheselden, *Osteographia* | `jfkydvqm` | 1733 | pdm | English. Bone atlas. |
| ★ | Albinus, *Tabulae sceleti et musculorum* (English ed) | `r3thaf6m` | 1754 | pdm | The English translation makes the captions usable. Latin originals (`a43g5vnz` 1747, `yw45y2s7` 1749) — skip unless you want the Latin. |
| ★ | Albinus, *Tabulae ossium humanorum* | `ugz833qz` | 1753 | pdm | Different work — keep alongside the *Tabulae sceleti*. |
| ★ | Albinus, *Tabulae VII uteri mulieris gravidae* | `t6hqn97a` | 1748–51 | pdm | Different work — keep. Companion to Hunter. |
| ★ | Hunter, *Anatomy of the Human Gravid Uterus* | `wc7gxkcu` | 1815 | pdm | Pick one good scan. Other PD copies on Wellcome (`cacd7ptn` 1843, `eek5cgun` 1843, `mrzj95k6`, `ap6us7er`, `jnxngaem`) — skip. |

**Gap**: full *Fabrica* text. Wellcome has only single-image surrogates (`q4ckuqf9`, `pahtkhab`, `wsdt4jgs` etc.) marked as workType "Digital Images" — these are individual plates, not the paginated book. **Flag for external ingest** from Library of Congress (1555 with IIIF) and BIU Santé Paris (1543 critical edition with translation), per `anatomy_corpus_ia_pulls.md`.

## Tier 5 — neuroanatomy

Specialty extension. The CNS got its own canon and you'll want it as a separate sub-corpus.

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Cajal, *Histologie du système nerveux* | `cfbxq8k8` / `akfqm42j` | 1909–11 | cc-by-nc (work itself PD) | Two-volume set — keep both. The foundational cellular neuroanatomy. **Wellcome catalogue quirk:** `cfbxq8k8` (b2129592x) and `akfqm42j` (b21270879) are two bibliographic records for the same 2-vol scan, with mirror-imaged metadata completeness — `cfbxq8k8` has populated printed page numbers for vol 1 but blank for vol 2; `akfqm42j` is the reverse. Cherry-pick `cfbxq8k8_v1` + `akfqm42j_v2` to get the better-cataloged half of each volume; the other two are redundant. OCR quality is equivalent across both records (same ABBYY pipeline, same diacritic-loss patterns). |
| ★ | Cajal, *Les nouvelles idées* | `gsfwgf65` / `n3hcmcax` | 1894 | pdm | Different work — earlier synthesis. Keep alongside the *Histologie*. |
| ★ | Edinger, *Vorlesungen*, latest pre-1929 | `z8w4cbad` | 1911 | inc → PD override | Mature form of his neuroanatomy. |
| | Edinger, earlier eds — skip | `uemusv2h` (1885), `fejjqpys` (1892), `vekxmjwg` (1896), `vjf4gsqc` (1900), `k3wmr2wp` (1908) | | mixed | *Optional historical pair*: if you specifically want to track how his thinking evolved, add `uemusv2h` (1885) — but otherwise the 1911 alone is sufficient. |
| ★ | Ranson, *Anatomy of the Nervous System*, 3rd ed | `bjsh27ua` | 1927 | inc → PD override: pre-1929 US PD | Last clearly US-PD edition; the most polished. |
| | Ranson 1st/2nd eds — skip | `zreqdbsa` (1920), `aqzvxwx8` (1923) | | inc → PD override | |
| ★ | Brodmann, *Vergleichende Lokalisationslehre der Grosshirnrinde* | `vrnkkxtj` | 1909 | inc → PD override: pre-1929 US PD; Brodmann d.1918 → UK life+70 PD since 1989 | The source of Brodmann areas. *Originally flagged as missing — actually on Wellcome under stale rights metadata.* |

**Gaps**: Tilney & Riley *The Form and Functions of the Central Nervous System* (1921, US PD); Herrick *Introduction to Neurology* (1915, US PD) — both genuinely not on Wellcome, both confirmed PD on HathiTrust and IA. See `anatomy_corpus_ia_pulls.md` for identifiers.

## Tier 6 — histology / embryology

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Schäfer, *Essentials of Histology*, 11th ed | `b69dh6vk` | 1920 | inc → PD override: pre-1929 US PD | Latest pre-1929 edition. Earlier eds (1887, 1892, 1894, 1898, 1902) — skip. |
| ★ | Bailey, *Text-book of Histology* | `n8dz65uv` | 1913 | pdm | Latest pre-1929. Earlier eds (`un8e5s7e` 1904, `xzbubvwy` 1906, `vxauc2nz` 1910) — skip. |
| ★ | Sobotta, *Lehrbuch und Atlas der Histologie* | `v43geect` | 1929 | pdm | Borderline US PD; latest. Earlier histology atlases (`vhhspy2u` 1902 German, `qxagpvan` 1903 French) — skip. |
| ★ | Keith, *Human Embryology and Morphology*, 3rd ed | `w8yhh68k` | 1913 | inc → PD override: pre-1929 US PD | Latest mature edition before 1929. The 1st ed (`yww7sdgp` 1902) — skip. |
| ★ | McMurrich, *Development of the Human Body* | `g9my2acs` | 1910 | inc → PD override: pre-1929 US PD | Different work from Keith — keep both. |

## Tier 7 — French, German, and other continental references

| Pick | Work | Wellcome ID | Date | lic | Notes |
|------|------|-------------|------|-----|-------|
| ★ | Sappey, *Traité d'anatomie descriptive*, 5th ed | `h9n43hma` | 1888–89 | pdm | Latest pre-Sappey-death edition; multi-volume — keep all volumes. Earlier eds (`drf88mes`, `r7rp29vx`, `bfuhheek`, `xqpc728h`) — skip. |
| ★ | Sappey, *Traité d'anatomie générale* | `dnbmq5p3` | 1894 | pdm | Different work from the descriptive *Traité* — keep alongside. |
| ★ | Hyrtl, *Lehrbuch der Anatomie des Menschen*, latest | `xugmyg7r` | 1889 | pdm | Latest of Hyrtl's many editions. Earlier eds (1846, 1855, 1857, 1878, 1882, 1885) — skip. |
| ★ | Henle, *Handbuch der systematischen Anatomie* — full set | `e5pwrbf9` (Knochen 1855), `xs8jejsy` (Bänder 1856), `cz73pq6c` (Muskel 1858), `veuxugxf` (Eingeweide 1862–66), `ywgnwrfg` (Gefäss 1868), `g84rzrx7` (Nerven 1879) | | pdm | **All six volumes** — these are different volumes of one multi-volume work, not editions. Exceptional coverage. |
| ★ | Henle, *Anatomischer Hand-Atlas zum Gebrauch im Secirsaal* (Braunschweig, Vieweg) | Heidelberg `henle1871bd1` (Knochen 1874), `henle1874bd2` (Bänder 1874), `henle1874bd3` (Muskeln 1874), `henle1874bd4` (Gefäße 1874), `henle1876bd5` (Nerven 1876), `henle1877bd6` (Eingeweide 1877) | 1874–77 | pdm | **Different work from the *Handbuch* above** — same author, similar volume titles, but the Hand-Atlas is a compact dissection-room companion designed for the table. 6 vols on Heidelberg with clean ALTO. Not on Wellcome. |
| ★ | Rauber-Kopsch, *Lehrbuch der Anatomie des Menschen*, latest pre-1929 | `h8cwyqvx` | 1912 | inc → PD override: pre-1929 US PD; Kopsch d.1955 → UK life+70 just newly PD as of 2025/26 | Latest mature multi-volume edition. Earlier eds (`amrrjwe7` 1892–94, `zyexwx6z` 1897–98 pre-Kopsch; `vabcqrwy` 1908, `jzccguzc` 1909) — skip. |
| ★ | Bardeleben *Handbuch der Anatomie* — chapter-volumes on Wellcome | Holl 1897 (`z3ny6kad`, pdm), Krause 1909 (`wcjvv3n2`, inc → PD override), Tandler 1913 (`f3xd4cyt`, inc → PD override) | various | mixed | These are **different chapter-volumes** of the multi-volume *Handbuch* — keep all. Different work from Bardeleben's atlas. **Bartels' *Lymphgefässsystem* (Bd. 3, Abt. 4, 1909) was the conspicuous gap — now in hand from Google Books, see `bartels_lymphgefasssystem_1909.pdf`.** |
| ★ | Poirier–Cunéo, *The Lymphatics* (English) | `yd8qmy94` / `z5tphefg` | 1903 | pdm | Specialised but valuable — different work from Sappey's lymphatic *Traité*. |

## What Wellcome doesn't have, that you'd want anyway

These are textbooks I would include in a serious anatomy corpus that are missing or only partial on Wellcome. **Companion file `anatomy_corpus_ia_pulls.md` has IA identifiers, HathiTrust verifications, and concrete pull paths for everything in this section.**

| Missing work | Why include | Where to find |
|--------------|-------------|---------------|
| Gray's *Anatomy of the Human Body*, 1918 (Lewis rev., aka "Bartleby Gray's") | The single most-referenced PD anatomy text in modern usage. Pre-1929 US PD. | Internet Archive (`anatomyofhumanbo1918gray`); LOC item 18017427; Bartleby HTML at `bartleby.com/lit-hub/anatomy-of-the-human-body/` (296 chapters, with figures at `legacy-cms-media.bartleby.com/.../sites/7/107/image{N}.gif`). **Note**: contrary to widespread belief, Gray's is *not* on Project Gutenberg — verified against the PG catalog dump. |
| Vesalius, *De humani corporis fabrica*, 1543 or 1555 (full text) | The foundational text. Wellcome has only individual plate images. | Library of Congress for the complete 1555 (item 2021667096, 450 pages, IIIF v2 via `tile.loc.gov`). BIU Santé Paris for the 1543 critical edition with Latin transcription and French translation, books I, II, III, IV, VII at `numerabilis.u-paris.fr/editions-critiques/vesale/pdf/livre{N}.pdf` (V and VI not yet published as of 2026). NLM Historical Anatomies has selected highlights, not the full book. |
| Bartels, *Das Lymphgefässsystem*, 1909 | The major early-20th-c German lymphatic monograph. Not on Wellcome. Bardeleben *Handbuch* Bd. 3, Abt. 4. | **Resolved**: full PDF (302 pp, 33.9 MB) pulled from Google Books via the signed-token method, file `bartels_lymphgefasssystem_1909.pdf`. Source copy: University of California Medical School Library (gift of H.E. Fraser, M.D., in memoriam Edward W. Twitchell, M.D.). Google Books volume ID `-tsEAQAAIAAJ`. DDB also lists it (item `KA7R2JEMUMCZOLMD4M3YIRVXVFMCCLAA` → ZB MED `digital.zbmed.de/physische_anthropologie/id/554928`) as a backup source. |
| Tilney & Riley, *The Form and Functions of the Central Nervous System*, 1921 | US PD. Functional neuroanatomy pair to Ranson. | IA `formfunctionsofc00tiln`; HT Cornell `coo1.ark:/13960/t6f19ht1p`. |
| Herrick, *Introduction to Neurology*, 1915 | US PD; comparative-evolutionary perspective. | HT UIUC `uiug.30112037286041` (OCLC 6082876); IA likely under a similar identifier. |
| Eycleshymer & Schoemaker, *Anatomical Names, especially the Basle Nomina Anatomica* (BNA), 1917 | The terminology Rosetta Stone. On Wellcome but not online. | IA `cu31924024790648`; HT Cornell `coo1.ark:/13960/t5gb2ns97`, Harvard `hvd.hc2ur6` (OCLC 1528887). |
| Eycleshymer & Schoemaker, *A Cross-Section Anatomy*, 1911 | Pre-radiology cross-sectional reference; useful for terminology grounding. | HT Harvard `hvd.hnqmqr` (OCLC 1359519); IA likely under a `crosssectionana` pattern. |
| Sappey, *Anatomie, physiologie, pathologie des vaisseaux lymphatiques*, 1874 | Sappey's standalone lymphatic monograph (distinct from his *Traité* — folio plates of cutaneous lymphatic drainage). Not on Wellcome as a standalone. | IA `BIUSante_01562`; BIU Santé Medica reference 01562. |
| Sobotta, *Atlas* — multiple early editions before those Wellcome has | Earlier eds desirable for completeness; Wellcome's earliest is 1919–20. | Internet Archive; HathiTrust. |
| Spalteholz earlier eds (German 1898) | Wellcome's earliest is 1900 English. | IA `handatlasderana01spalgoog` (German 2nd ed Vol 1); NLM holds three Spalteholz items. |
| Bardeleben *Handbuch* Vols. 2, 3, 4, 6, 8 | Wellcome has individual chapter-volumes (Holl, Krause, Tandler) but not the whole *Handbuch*. BHL has Vols. 1, 5:1, 5:2, 7. **Vol. 3 (Gefässystem) is the most important gap — it contains Bartels' Lymphgefässsystem.** | Vol 1: IA `handbuchderanato11bard`. Other vols not located in this sweep — worth a determined search of HathiTrust and IA from outside. |
| Cunningham *Manual of Practical Anatomy*, 1920 ed | Wellcome has 1889/1912/1914; this fills the post-WWI edition. | BHL title-id 30040. |

**Removed from this list since the previous draft** — these items I had flagged as missing turned out to be on Wellcome under stale "in-copyright" metadata (PD overrides), now relocated to their proper tier above:

- *Brodmann 1909* — Wellcome `vrnkkxtj` (now in Tier 5, neuroanatomy)
- *Rauber-Kopsch later editions* — Wellcome `vabcqrwy`, `jzccguzc`, `h8cwyqvx` (now in Tier 7, with the early Rauber editions also called out)

**External-OCR fixes that landed since this list was first written:**

- *Bourgery & Jacob text* — Wellcome's ALTO is broken for the whole work. **Resolved via Heidelberg** — `bourgery1831ga` hub with 8 text + 8 atlas vols, all with clean ALTO. See the updated Bourgery row in Tier 3.
- *Henle Anatomischer Hand-Atlas (1874–77)* — different work from Henle's *Handbuch*, **added from Heidelberg** as a new ★ pick in Tier 7. 6 vols.

**Heidelberg holds later Vesalius editions but not the 1543 or 1555 critical ones we care about:** `vesalius1568`, `vesalius1604`, `vesalius1617` are available — useful for tracking post-Vesalius resets of the *Fabrica* if scope ever expands, but not a substitute for the 1543/1555 gap.

## OCR / ALTO availability — practical notes

ALTO coverage across ★ picks audited 2026-05-11
(see `experiments/alto_coverage/`). Headlines:

1. **Wellcome has backfilled ALTO across the 19th–20th-c picks.** Every Sobotta 1927–28 (English + German + histology), Rauber-Kopsch 1912, Piersol 1918, Crooke 1618, Cheselden 1733, Albinus 1754, and Hunter 1815 sampled has **100% ALTO coverage**. Earlier editions of this document said Sobotta 1927–28 and "some 1912 items" lacked ALTO — that claim is now stale; Wellcome's pipeline has caught up. **Bourgery 1831–54 is the conspicuous exception:** every advertised ALTO URL returns HTTP 500 across all 14 child manifests; the work's metadata claims ALTO coverage but the endpoint is broken. We ingest Bourgery image-only on the Wellcome side (`create-index --no-ocr`) and pair with Heidelberg for OCR. ALTO is the structured XML carrying `<TextBlock>` (with per-block bboxes) plus often `<Illustration>` regions; coordinates are in image-native pixels.

2. **Genuine ALTO-less cases on Wellcome: pre-1600 books only.** Confirmed in our sample:
   - **Vesalius *Epitome* 1543** (`g6b6smge`): 55 canvases, 0 ALTO
   - **Valverde 1556** (`nrtzmcfn`): 374 canvases, 0 ALTO

   Both are 16th-century woodcut/letterpress in Latin/Spanish; Wellcome's ABBYY pipeline doesn't handle pre-1600 typography. Crooke 1618 (English) is the boundary case where coverage resumes. For these works, `iiif-utils create-index` will produce a metadata-only index with `text_blocks` and `illustrations` empty; full-text search isn't possible from Wellcome's pipeline. Two paths to recover text:
   - **External ingest** — the Vesalius *Fabrica* is already flagged for LoC / BIU Santé external pull below; the *Epitome* could follow a similar pattern.
   - **Local re-OCR** — `iiif-utils ocr-pages` (planned) would run Tesseract on each canvas. Note Tesseract's Latin model is trained on modern Latin typography; 1543 woodcut Latin remains hard.

3. **The `seeAlso` element** on each canvas is the universal signal for per-canvas ALTO availability. We match `format == "text/xml"` AND a `profile` containing `alto` (Wellcome advertises the v3 profile string but serves v2 XML — both name-spaces handled).

4. **OCR quality** is generally good for late-19th/early-20th-c serif typesetting (95%+ word accuracy), degrades on blackletter (Henle, some German atlases) and on the 16th–17th-c works where ALTO exists but accuracy drops to 60–80%. Budget for re-OCR or hand correction on critical pages in those tiers.

5. **For corpus indexing**, treat Tier 1–2 as text-primary and Tier 3 as image-primary. Tier 4 is image-primary plus selectively OCR'd captions and headings.

6. **Wellcome record completeness gotchas.** A Wellcome work record marked "Online" doesn't always mean the IIIF manifest contains a full scan. Three patterns to watch for:
   - **Bibliographic-only records**: the record exists but the IIIF manifest has 0 canvases. Several Cunningham *Manual* editions (1893, 1903, 1889) are like this. Always check canvas count before assuming the work is digitized.
   - **Partial digitizations**: e.g. Cunningham *Text-book* 1906 (`ppy5p9uc`) is explicitly "Section 2" only — pages 316-811. Title carries the warning but the work-record can read as a normal record.
   - **Multi-volume sets concatenated into one manifest**: e.g. Cunningham *Manual* 1914 (`kw6vt8gv`) is a 2-volume work served as one 752-canvas manifest. The volume break is identifiable by the second "Cover" entry in the manifest's `structures` array. When chunking for indexing, splitting at the second "Cover" gives you clean per-volume boundaries. The `physicalDescription` field saying "volumes" (plural) is the bibliographic hint.
   - **Multi-volume sets exposed as IIIF Collections** (not concatenated manifests): e.g. Piersol `mvaqfjxm` resolves to a Collection of 2 child manifests; Bourgery `p747b7vs` to a Collection of 14; Quain, Spalteholz, Sappey, Toldt, Sobotta English/Histo, Cajal *Histologie* (×2 duplicate records) similarly. `iiif-utils create-index` refuses Collections directly; use `get-pages --manifest <ID> --child N` to inspect, or expand the Collection and run `create-index` per child.
   - **Duplicate bibliographic records.** Cajal *Histologie* is on Wellcome under two work IDs (`cfbxq8k8` / `akfqm42j`, b-numbers `b2129592x` / `b21270879`) — the same 2-volume scan with mirror-imaged page-number metadata completeness. Cherry-pick `cfbxq8k8_v1` + `akfqm42j_v2` for the better-cataloged half of each volume. CORPUS.md row notes this explicitly.

7. **Heidelberg University Library (digi.ub.uni-heidelberg.de)** added as a provider (`-P heidelberg`) for the Bourgery rescue. Heidelberg manifests are IIIF v2 with per-page ALTO referenced from a manifest-level METS (not in canvas-level `seeAlso`); the adapter fetches manifest + METS and injects per-canvas ALTO URLs. Clean ABBYY-class OCR with French diacritics preserved. Cataloging quirk: text vols use stem `bourgery...` (two r's), atlas vols use `bourgey...` (one r) — typo preserved in permalinks.

## Suggested ingestion order

After applying the one-edition rule, the corpus shape is roughly:

- Tier 1 (textbook backbone): **8 picks** plus volumes — Morris, Cunningham *Text-book*, Cunningham *Manual*, Piersol, Gerrish, Quain's (multi-vol), Gray's 1918 (external).
- Tier 2 (Victorian dissection): **3 picks** — Holden, Ellis, Gray UK.
- Tier 3 (atlases): **5 picks** — Spalteholz, Sobotta English, optionally Sobotta German, Toldt, Bourgery (multi-vol).
- Tier 4 (early modern): **8 picks** — Vesalius *Epitome* + *Fabrica* full text (external), Valverde, Crooke, Cheselden, Albinus (3 different works), Hunter.
- Tier 5 (neuroanatomy): **5 picks** + 2 external — Cajal *Histologie*, Cajal *Nouvelles idées*, Edinger 1911, Ranson 1927, Brodmann; Tilney + Herrick external.
- Tier 6 (histology/embryology): **5 picks** — Schäfer, Bailey, Sobotta histology, Keith, McMurrich.
- Tier 7 (continental): **7 picks** — Sappey *Traité* (multi-vol), Sappey *générale*, Hyrtl, Henle *Handbuch* six-volume, Henle *Hand-Atlas* six-volume (Heidelberg), Rauber-Kopsch 1912, Bardeleben chapter-volumes (Holl + Krause + Tandler + Bartels), Poirier-Cunéo.

Roughly **40 distinct works** (counting multi-volume sets as one work each), expanding to perhaps 70-90 individual volumes when you count separately-bound parts. Rough order to ingest:

1. Start with Tier 1 + Tier 2 — the textbook backbone gives the LLM a representative sample of standard anatomical prose and terminology in roughly current form.
2. Add Tier 3 atlases for visual grounding.
3. Add Tier 6 (histology/embryology) for cellular- and developmental-scale coverage.
4. Add Tier 5 (neuroanatomy) if your use case touches CNS.
5. Add Tier 7 (continental references) for terminology-history depth and multilingual reach.
6. Add Tier 4 last — the rewards are great but the OCR work is heaviest.

External ingestion (Gray's 1918, Vesalius full text, Bartels, Tilney, Herrick, Eycleshymer pair, Sappey 1874, Spalteholz 1898) can be done in parallel using the IA / LOC / BIU Santé / HathiTrust / Google Books paths documented in `anatomy_corpus_ia_pulls.md`.

## What's actually indexed (as of 2026-05-12)

The corpus has been built out incrementally. Current on-disk state:

**`corpus/wellcome/` — 72 sqlite indexes, 416 MB:**

- 36 single-manifest works (the bulk of Tier 1–7 ★ picks with full ALTO/FTS)
- 25 child indexes from Wellcome multi-vol Collections, named `<work_id>_v<N>.sqlite`:
  Cajal *Histologie* (`akfqm42j_v2`, `cfbxq8k8_v1` — cherry-picked half; see Tier 5 row),
  Piersol (`mvaqfjxm_v1..v2`), Quain (`gw75hbbr_v1..v4`), Sappey descriptive (`h9n43hma_v1..v4`),
  Spalteholz (`d8quuwxg_v1..v3`), Toldt (`tgekje3p_v1..v3`), Sobotta English (`kdckv24y_v1..v2`),
  Sobotta Histologie (`v43geect_v1..v2`)
- 14 Bourgery image-only indexes (`p747b7vs_v1..v14` via `--no-ocr` — ALTO endpoint is broken)
- 2 metadata-only indexes for pre-1600 works with no ALTO at all (Vesalius *Epitome* `g6b6smge`, Valverde `nrtzmcfn`)
- Totals: ~39,486 canvases, ~272,103 text blocks, ~18,080 illustration regions

**`corpus/heidelberg/` — 22 sqlite indexes:**

- 8 Bourgery text vols (`bourgey1832bd1_1` + `bourgery1834bd2_1`...`bourgery1854bd8_1`) — ~2,312 canvases, ~15.1M chars of French OCR
- 8 Bourgery atlas vols (`bourgey1831bd1_2`...`bourgey1844bd8_2`) — ~1,485 canvases with the colored chromolithographs and Planche-N labeled plates
- 6 Henle *Hand-Atlas* vols (`henle1871bd1`...`henle1877bd6`)

**Known unindexed gaps** (external sources flagged earlier): Gray's 1918, Vesalius *Fabrica* 1543/1555 full text, Bartels 1909 (PDF in hand), Tilney & Riley, Herrick, Eycleshymer pair, Sappey 1874, Spalteholz 1898 German.

**Known OCR-quality outliers** (still usable, but noted):
- Hyrtl 1889 (`xugmyg7r`): patchy — most pages clean, some pages mangled with multiple-character drops. Common terms FTS-hit cleanly (`Histologie`, `Anatomie`, `Sinneslehre`); selective pages may need local Tesseract re-OCR.
- Tier 4 early modern English (Crooke 1618, Cheselden 1733, Albinus 1754): long-s endemic — OCR reads `ſ` as `f` consistently. Search queries on these works need s↔f variant expansion to match modern spellings.
- Atlas works (Toldt, Sobotta atlases, Albinus plates, Hunter): low average block length because OCR correctly captures figure-callout labels as tiny text_blocks. Not a defect.
