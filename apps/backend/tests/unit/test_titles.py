import pytest

from dotrix_backend.modules.agents.titles import title_from_message


@pytest.mark.parametrize(
    ("message", "title"),
    [
        ("Can you please summarise the board in one short paragraph.", "Summarise the board in one short paragraph"),
        ("In three short sentences, what is this project about?", "What is this project about"),
        ("Hi! What's blocked?", "What's blocked"),
        ("Hey, could you tell me about the roadmap", "The roadmap"),
        ("what should we build next? Also, the roadmap.", "What should we build next"),
        ("Add phase 1 to the roadmap", "Add phase 1 to the roadmap"),
        ("I'd like to plan the multi-zone driver epic", "Plan the multi-zone driver epic"),
        # Long requests are cut at seven words; issue keys are kept as written.
        (
            "please create a low-priority task under epic KLL-1 for the migration docs",
            "Create a low-priority task under epic KLL-1…",
        ),
        ("Update the roadmap\nand also the vision", "Update the roadmap"),
        ("Thanks!", "Thanks"),  # nothing but pleasantries: keep what was said
        ("   ", "New conversation"),
    ],
)
def test_titles_come_from_the_first_message(message: str, title: str) -> None:
    assert title_from_message(message) == title


def test_titles_stay_short() -> None:
    title = title_from_message("Supercalifragilisticexpialidocious " * 3 + "architecture overview")
    assert len(title) <= 61 and title.endswith("…")
