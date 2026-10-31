

def test_every_default_skill_names_its_agents_and_they_exist() -> None:
    from dotrix_engine.layout import AGENTS
    from dotrix_engine.skills import SKILLS, describe_skill, skill_agents, skills_for

    for name, text in SKILLS.items():
        agents = skill_agents(text)
        assert agents and agents <= set(AGENTS), (name, agents)
        assert describe_skill(text), name
    assert set(skills_for(SKILLS, "coding")) == {
        "threat-model-a-feature", "security-review", "design-an-api", "plan-a-schema-change",
        "review-a-backend-change", "review-a-frontend-change", "build-a-ui-change", "definition-of-done"}
    assert "evaluate-a-library" in skills_for(SKILLS, "research") and "write-a-runbook" in skills_for(SKILLS, "documentation")
    assert skills_for({"ours": "# Ours\nDescription: for all\n"}, "product") == {"ours": "# Ours\nDescription: for all\n"}


def test_a_skill_s_words_pick_it_for_an_issue() -> None:
    from dotrix_engine.skills import SKILLS, skill_matches

    assert skill_matches(SKILLS["plan-a-schema-change"], "Add an index to the issues table")
    assert skill_matches(SKILLS["review-a-frontend-change"], "Fix the spacing in apps/web/src/Chat.tsx")
    assert skill_matches(SKILLS["security-review"], "Report a vulnerability in the upload")
    assert not skill_matches(SKILLS["security-review"], "Fix the typo in the README")
    assert not skill_matches(SKILLS["design-an-api"], "Rapid fixes")  # "api" as a word, not inside one
    assert skill_matches("# Ours\nDescription: always\n", "anything")  # no When: line: always


def test_a_change_s_files_and_diff_pick_its_review_skills() -> None:
    from dotrix_engine.skills import review_skills

    assert review_skills("Add sign-in\n- apps/api/auth.py (+40 -2)\n+    token = issue_token(user)") == [
        "design-an-api", "review-a-backend-change", "security-review", "threat-model-a-feature"]
    assert review_skills("Tidy the header\n- apps/web/src/Header.tsx (+3 -3)") == ["review-a-frontend-change"]
    assert review_skills("Fix a typo\n- README.md (+1 -1)") == []
    assert review_skills("Fix a typo\ndiff --git a/README.md b/README.md\nindex 3f2a..9c1b 100644\n-teh\n+the") == []
