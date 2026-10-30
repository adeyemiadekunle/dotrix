from types import SimpleNamespace as NS

import pytest

from dotrix_backend.modules.agents.model_routing import specialist_model


@pytest.mark.parametrize("automatic,agent,mutates,personal,override,expected", [
    (False, "architecture", False, None, None, "routine"),
    (True, "architecture", False, None, None, "strong"),
    (True, "reviewer", False, None, None, "strong"),
    (True, "research", False, None, None, "routine"),
    (True, "documentation", True, None, None, "strong"),
    (True, "architecture", False, "personal", "override", "personal"),
    (True, "architecture", False, None, "override", "override"),
])
def test_policy_preserves_explicit_models(automatic, agent, mutates, personal, override, expected):
    project = NS(model="project", specialist_model="routine", automatic_model_routing=automatic)
    assert specialist_model(project, NS(conversation_model="strong"), NS(agent=agent, changes_project=mutates),
                            NS(model=override), NS(model=personal)) == expected


def test_unconfigured_routine_model_falls_back_to_conversation():
    project = NS(model="project", specialist_model=None, automatic_model_routing=True)
    assert specialist_model(project, NS(conversation_model="strong"), NS(agent="research", changes_project=False),
                            NS(model=None)) == "strong"
