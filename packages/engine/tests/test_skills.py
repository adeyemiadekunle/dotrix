

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
