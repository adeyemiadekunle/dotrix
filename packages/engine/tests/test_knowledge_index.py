from pmagent_engine.knowledge_index import describe, find_section, sections


def test_title_summary_and_outline() -> None:
    d = describe(
        "requirements/product.md",
        "# Product requirements\n\n_What Kumove must do for drivers and dispatch._\n\n"
        "## Goals\n\n- Multi-zone drivers\n\n## Non-goals\n\n### Later\n\nText.\n",
    )
    assert d.title == "Product requirements"
    assert d.summary == "What Kumove must do for drivers and dispatch."
    assert d.outline == ["## Goals", "## Non-goals", "### Later"]


def test_falls_back_to_the_file_name_and_skips_code_tables_and_notes() -> None:
    d = describe(
        "docs/normalized/hub-list.md",
        "> Imported from `Hub List.xlsx` on 2026-09-28.\n\n| Hub | State |\n|---|---|\n| Ikeja | Lagos |\n\n"
        "```python\nprint('not prose')\n```\n\nIkeja and Lekki hubs serve **Lagos**; see [the map](http://x).\n",
    )
    assert d.title == "Hub list"
    assert d.summary == "Ikeja and Lekki hubs serve Lagos; see the map."


def test_only_a_quoted_note_is_still_a_summary() -> None:
    assert describe("docs/normalized/x.md", "> Imported from `x.pdf` on 2026-09-28.\n").summary.startswith("Imported from")


def test_long_summaries_are_cut_at_a_word() -> None:
    d = describe("a.md", "# A\n\n" + "word " * 100)
    assert len(d.summary) <= 241 and d.summary.endswith("…")


def test_empty_and_front_matter() -> None:
    assert describe("empty.md", "").summary == "(empty)"
    d = describe("issues/KUN-1.md", "---\nkey: KUN-1\nstatus: todo\n---\n# KUN-1 Ship it\n\nThe work.\n")
    assert d.title == "KUN-1 Ship it" and d.summary == "The work."


DOC = """Intro before any heading.

# Requirements

## Goals
- Multi-zone drivers

### Later
Night deliveries.

## Non-goals
```
# not a heading
```
"""


def test_sections_nest_and_own_text() -> None:
    nested = sections(DOC)
    assert [(s.heading, s.trail, s.start_line, s.end_line) for s in nested] == [
        (None, "", 1, 2),
        ("# Requirements", "Requirements", 3, 15),
        ("## Goals", "Requirements > Goals", 5, 10),
        ("### Later", "Requirements > Goals > Later", 8, 10),
        ("## Non-goals", "Requirements > Non-goals", 11, 15),
    ]
    assert "Night deliveries." in nested[2].text  # an H2 includes its H3s
    own = {s.trail: s.text for s in sections(DOC, nested=False)}
    assert "Night deliveries." not in own["Requirements > Goals"]  # indexing: no text twice
    assert "# not a heading" in own["Requirements > Non-goals"]  # headings in code don't count


def test_find_section_by_heading_or_trail() -> None:
    assert find_section(DOC, "## Goals").trail == "Requirements > Goals"
    assert find_section(DOC, "goals").heading == "## Goals"
    assert find_section(DOC, "Goals > Later").heading == "### Later"
    assert find_section(DOC, "Requirements > Non-goals").start_line == 11
    assert find_section(DOC, "Pricing") is None
