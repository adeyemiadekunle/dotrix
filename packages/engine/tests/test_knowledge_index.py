from pmagent_engine.knowledge_index import describe


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
