

def test_every_default_skill_names_its_agents_and_they_exist() -> None:
    from dotrix_engine.layout import AGENTS
    from dotrix_engine.skills import SKILLS, describe_skill, skill_agents, skills_for

    for name, text in SKILLS.items():
        agents = skill_agents(text)
        assert agents and agents <= set(AGENTS), (name, agents)
        assert describe_skill(text), name
    assert set(skills_for(SKILLS, "coding")) == {
        "threat-model-a-feature", "security-review", "design-an-api", "plan-a-schema-change",
        "review-a-backend-change", "review-a-frontend-change", "build-a-ui-change", "definition-of-done", "write-an-executable-plan"}
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


def test_skill_bundles_and_taxonomy_are_valid_and_pinned() -> None:
    import hashlib

    from dotrix_engine.layout import AGENTS
    from dotrix_engine.skill_bundles import (
        BUILTIN_SKILL_META,
        BUNDLED_SKILLS,
        SKILL_CATEGORIES,
        VALID_CATEGORY_IDS,
    )
    from dotrix_engine.skills import (
        SKILLS,
        describe_skill,
        skill_agents,
        skill_category,
        skill_tags,
    )

    assert ("frontend", "Frontend") in SKILL_CATEGORIES
    assert ("browser", "Browser & Automation") in SKILL_CATEGORIES
    assert set(BUILTIN_SKILL_META) == set(SKILLS)
    for name, (category, tags) in BUILTIN_SKILL_META.items():
        assert category in VALID_CATEGORY_IDS, name
        assert tags, name

    assert {"frontend-modern-web-guidance", "browser-exploratory-verification", "product-requirements-brief"} <= set(BUNDLED_SKILLS)
    for bundle_id, bundle in BUNDLED_SKILLS.items():
        assert bundle.id == bundle_id
        assert bundle.category in VALID_CATEGORY_IDS
        assert bundle.trust == "reviewed"
        assert bundle.agents and set(bundle.agents) <= set(AGENTS)
        assert bundle.tags
        assert describe_skill(bundle.content)
        assert skill_category(bundle.content) == bundle.category
        assert skill_tags(bundle.content) == bundle.tags
        assert tuple(sorted(skill_agents(bundle.content) or ())) == tuple(sorted(bundle.agents))
        assert hashlib.sha256(bundle.content.encode()).hexdigest() == bundle.sha256


def test_skill_registry_merges_builtins_bundles_and_workspace_skills() -> None:
    from dotrix_engine.skill_bundles import BUNDLED_SKILLS
    from dotrix_engine.skills import SKILLS, build_skill_registry

    baseline = build_skill_registry()
    by_id = {item.id: item for item in baseline}
    assert len(baseline) == len(SKILLS) + len(BUNDLED_SKILLS)
    assert by_id["build-a-ui-change"].origin == "builtin"
    assert by_id["build-a-ui-change"].trust == "builtin"
    assert by_id["build-a-ui-change"].enabled is True
    assert by_id["frontend-modern-web-guidance"].origin == "bundle"
    assert by_id["frontend-modern-web-guidance"].trust == "reviewed"
    assert by_id["frontend-modern-web-guidance"].enabled is False
    assert by_id["browser-exploratory-verification"].required_tools == ("browser",)

    bundle = BUNDLED_SKILLS["frontend-modern-web-guidance"]
    merged = build_skill_registry(
        {
            bundle.id: (bundle.content, 2),
            "write-an-adr": ("# Custom ADR\nDescription: Workspace ADR rule.\nCategory: architecture\nTags: adr, custom\n", 1),
            "custom-deploy": ("Description: Deploy check.\nCategory: devops\nTags: deploy, smoke\nAgents: coding\n", 3),
        }
    )
    merged_by_id = {item.id: item for item in merged}
    assert merged_by_id[bundle.id].enabled is True
    assert merged_by_id[bundle.id].origin == "bundle"
    assert merged_by_id[bundle.id].trust == "reviewed"
    assert merged_by_id[bundle.id].version == 2
    assert merged_by_id["write-an-adr"].origin == "workspace"
    assert merged_by_id["write-an-adr"].trust == "workspace"
    assert merged_by_id["write-an-adr"].version == 1
    assert merged_by_id["custom-deploy"].category == "devops"
    assert merged_by_id["custom-deploy"].tags == ("deploy", "smoke")
    assert merged_by_id["custom-deploy"].agents == ("coding",)
