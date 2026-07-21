# Porting DeclaratorLM to other countries

DeclaratorLM was built for Ukraine's [NAZK](https://public.nazk.gov.ua/public_api) declaration register. But the hard part of the project — cleaning a messy declaration into a compact form and having an LLM flag corruption risk — is **not Ukraine-specific**. This document explains how to point the tool at another country's data, which countries are the easiest and hardest to adapt, and the practical routes to get there.

> **Reading note.** Country-format claims below are marked by confidence. **Verified** = checked against a primary/authoritative source this project cited. **Plausible** = consistent with known systems but not independently verified — treat as a lead, and confirm on the country's official portal before writing an adapter.

---

## 1. The core idea: the concept is universal, the format is the barrier

In almost every country with a public declaration system, a declaration records the same things:

**declarant → family members → real estate → vehicles/valuables → bank accounts & cash → securities → business/corporate interests → income → liabilities → (sometimes) gifts, expenses, interests.**

That is essentially NAZK's structure. So the *conceptual schema* transfers almost everywhere. What actually differs — and what decides how much work an adapter is — is **how the data is published**:

- a machine-readable **API / JSON** (easiest),
- structured **XML**,
- **HTML** pages you can parse,
- **PDF/DOC** forms (need document parsing),
- **scanned images** (need OCR — a different project entirely),
- or **not published at all** (impossible without the data).

Globally this is the norm, not the exception: the World Bank reports 160+ countries have declaration systems, but **fewer than a third publish** politicians' declarations, and **less than one-sixth** of the useful information is actually available in practice ([World Bank/StAR](https://star.worldbank.org/focus-area/asset-declarations)).

---

## 2. Architecture: adapters → one canonical format → unchanged pipeline

The clean way to support many countries is a thin **adapter layer** in front of the existing pipeline:

```
  ┌─────────────────────┐
  │  per-country source │   ukraine_json / france_xml / georgia_html / ...
  └──────────┬──────────┘
             │  adapter.parse(source)
             ▼
  ┌─────────────────────┐
  │   canonical format  │   ← the compact v2 shape (see §3)
  └──────────┬──────────┘
             │
             ▼
  ┌─────────────────────────────────────────────┐
  │  UNCHANGED: LLM call, response normalization, │
  │  reports (HTML/CSV), dossier charts, GUI      │
  └─────────────────────────────────────────────┘
```

A suggested layout:

```
sources/
    ukraine_json.py        # native — already exists as compact_declaration()
    france_xml.py          # direct, high-fidelity
    georgia_html.py
    moldova_html.py
    opensanctions_ftm.py   # "bulk" adapter — many countries at once (see §6)
    romania_pdf.py
    usa_pdf.py
```

Each adapter implements a single contract:

```python
canonical = adapter.parse(source)   # -> a compact-v2-shaped dict
```

Everything downstream — the prompts, the risk analysis, the anomaly detection, the reports, the dossier mode — stays **exactly the same**, because it already speaks the canonical format.

---

## 3. The canonical format is `compact v2` — not raw NAZK JSON

There are two "Ukrainian JSONs", and the distinction matters:

- **Raw NAZK API JSON** — a poor canonical target. It's the *messy* input: `step_N` wrappers, cryptic field names, ownership encoded as `rightBelongs` codes. This is exactly what the project spends effort cleaning up.
- **`compact v2`** — the **right** canonical target. It's the normalized, de-duplicated, human-readable structure that `compact_declaration()` produces and the LLM actually consumes: named sections, resolved owners, quick totals. See [`raw-compact.md`](raw-compact.md) for its full shape.

So a foreign adapter should **emit compact-v2-shaped objects directly**, rather than trying to reconstruct raw NAZK JSON. The canonical boundary is the *output* of `compact_declaration`, not its input. Its sections are, in short:

```
meta.declarant · quick_totals · step_0_interpreted · family_members ·
real_estate · unfinished_construction · vehicles · corporate_rights ·
incomes · cash_assets · liabilities · major_changes · expenses ·
financial_institutions · raw_extras
```

Any country's assets map onto these; anything without a home goes into `raw_extras` (cleaned) exactly as the 5 uncovered NAZK steps do today.

---

## 4. Where to change things in the code

Adapting is mostly about the **interpretation layer**, not the pipeline. Concretely (see also [`raw-compact.md` §8](raw-compact.md#adaptation)):

1. **Data client** — replace `nazk_parser/` with a client for the new source (API, dump, scrape). The pipeline (`main.py`), reports, and GUI don't depend on where the data comes from.
2. **The adapter / section builders** — the country's equivalent of `compact_declaration()`: map the foreign fields onto the canonical sections in §3. This is the heart of the work.
3. **Owner/family resolution** — the analogue of `_build_person_index` / `_resolve_right_holders`, matched to how *that* format encodes family members and asset ownership.
4. **Code dictionaries** — `DECLARATION_TYPE_MAP` and similar lookups, for the new country's codes.
5. **Prompts** — the section names referenced in `SYSTEM_PROMPT` / `USER_PROMPT_TEMPLATE` must match what your adapter produces; the analysis language can be changed here too.

What you do **not** touch: the LLM providers (Ollama/OpenRouter), response normalization, `report.py`, dossier charts, the usage dashboard, the GUI — they operate on already-normalized results.

---

## 5. Country suitability

### Tier 1 — ready or near-ready (structured / open data)

- **🇺🇦 Ukraine (NAZK)** — *verified.* Full public JSON API, ~9 million documents, itemized per-object ownership. The native, already-supported case and the reference schema. ([public.nazk.gov.ua](https://public.nazk.gov.ua/public_api))
- **🇫🇷 France (HATVP)** — *verified.* Structured online filing (the ADEL tool); **interest declarations** published as open data in **XML + CSV**, with a JSON registry, on data.gouv.fr under the Etalab licence. XML → canonical is nearly lossless. *Caveat:* asset (patrimoine) declarations of parliamentarians have tighter access rules than interest declarations, so "everything in XML" is an overstatement. ([HATVP Open Data](https://www.hatvp.fr/open-data/))
- **🇬🇪 Georgia** — *verified (system) / plausible (fields).* Electronic public system (declaration.gov.ge), family assets included, monitored by the Anti-Corruption Bureau. Already normalized by [OpenSanctions](https://www.opensanctions.org/datasets/ge_declarations/), which is the easiest route in. ([acb.gov.ge](https://acb.gov.ge/en))
- **🇲🇩 Moldova (ANI, e-Integritate)** — *verified (system).* Electronic public declarations since 2018; the system itself redacts personal fields. Also reachable via OpenSanctions. ([politia.md](https://politia.md/en/declaration-assets-and-personal-interests))
- **🇨🇱 Chile** — *moderate confidence.* Proactive online disclosure of asset and interest declarations for senior officials, judiciary, and parliament (Law 20.880), verified by the Comptroller General. Exact export format not confirmed. ([OECD](https://www.oecd.org/en/publications/asset-declarations-for-public-officials_9789264095281-en.html))

### Tier 2 — medium (public, but document-shaped)

- **🇷🇴 Romania** — *verified.* Rich, itemized standardized form ("Declaraţie de avere", Annex 1 to Law 176/2010) — but published historically as fixed **PDF/DOC**. The content is structured; the *access* is document-based, so you need PDF parsing (or take it from OpenSanctions). ([SGG.gov.ro](https://sgg.gov.ro/1/interes-public/declaratii-de-avere-si-interese/))
- **🇺🇸 USA (OGE Form 278e)** — *verified.* Public financial disclosure via the "Integrity" e-filing system, but the public output is **PDF** (a machine-readable Excel version exists; there is no single open bulk database — access is via agencies/requests). ([OGE](https://www.oge.gov/))
- **🇲🇽 Mexico (DeclaraNet)** — *plausible.* Electronic filing system; public versions published as PDFs with personal data redacted. Historically much of the detail was opt-in/redacted — verify current openness before building.
- **🇦🇷 Argentina** — *plausible.* Online filing with a public part and a reserved annex; published as PDF forms. Confirm access rules per the Oficina Anticorrupción.
- **🇭🇷 Croatia, 🇱🇻 Latvia** — *plausible.* Public web registers (Croatia's conflict-of-interest commission; Latvia's tax authority publishes public versions), typically HTML/tabular with confidential fields auto-hidden. Good candidates in principle; confirm the export path.

### Tier 3 — hard or unsuitable

- **Scanned images / no structured form** — declarations exist only as scans. This needs OCR + layout parsing before any of the above applies; it's a separate, much harder engineering problem, not a schema remap.
- **"Public on paper, closed in practice"** — e.g. the **🇵🇭 Philippines (SALN)**: legally public, but access has been throttled for years by fees, forms, and outright restrictions (tightened in 2020, only partially reopened in 2025). The bottleneck is *obtaining* the data, not parsing it. ([Philstar](https://www.philstar.com/headlines/2025/10/15/2479872/public-may-again-request-officials-salns-heres-how))
- **Confidential systems** — the global majority. Where declarations are filed only to a regulator and never published, there is simply no data to analyze.

---

## 6. The OpenSanctions / FollowTheMoney shortcut

Instead of writing a bespoke adapter per country, one adapter can cover several at once. [OpenSanctions](https://www.opensanctions.org/datasets/sources/) already collects and normalizes the declarations of **Georgia, Romania, Moldova** (and others) into the [FollowTheMoney](https://github.com/opensanctions/followthemoney) (FtM) data model as structured JSON.

- **Upside:** a single `opensanctions_ftm.py` adapter can ingest multiple jurisdictions that would otherwise each need their own HTML/PDF parser.
- **Caveat:** FtM is a *graph* model — entities (`Person`, `Company`, `Asset`) linked by `Ownership` relationships ([FtM docs](https://www.opensanctions.org/docs/entities/)) — which is a different shape from the flat, section-based `compact v2`. The adapter has to walk that graph and flatten it into the canonical sections. It's more work than a trivial field rename, but it's "write once, get many countries."

Bespoke and bulk adapters are **complementary**, not competing: use a high-fidelity native adapter where the open format is good (Ukraine JSON, France XML), and the FtM adapter as a broad net for the rest.

---

## 7. Data-format tiers at a glance

| Tier | Format | Countries (examples) | Effort |
|------|--------|----------------------|:---:|
| 1 | JSON API | 🇺🇦 Ukraine | ⭐ |
| 1 | XML (open data) | 🇫🇷 France | ⭐ |
| 2 | HTML (parseable) | 🇬🇪 Georgia · 🇲🇩 Moldova · 🇭🇷 Croatia · 🇱🇻 Latvia | ⭐⭐ |
| 3 | PDF/DOC forms | 🇷🇴 Romania · 🇺🇸 USA · 🇲🇽 Mexico · 🇦🇷 Argentina | ⭐⭐⭐ |
| 4 | Scans / OCR | (various) | ⭐⭐⭐⭐⭐ |
| — | Not public / access-blocked | 🇵🇭 Philippines · the global majority | 🔴 |

---

## 8. This is a recognized direction, not a novelty

Automated analysis of asset declarations is an approach the anti-corruption field actively endorses. The World Bank's Stolen Asset Recovery initiative (StAR) has a dedicated publication, **[Automated Risk Analysis of Asset and Interest Declarations of Public Officials](https://star.worldbank.org/publications/automated-risk-analysis-asset-and-interest-declarations-public-officials)** — which is, in essence, what DeclaratorLM does. Porting it to a new country contributes to a well-established international effort.

---

*Sources are linked inline. Confidence labels are honest: verify a specific country's current format and access rules on its official portal before committing to an adapter — publication regimes change, and several entries above are leads rather than confirmed integrations.*
