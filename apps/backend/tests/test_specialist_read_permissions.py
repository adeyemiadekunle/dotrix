"""Project specialist reads stay scoped without widening cross-project contracts."""
from dotrix_backend.modules.agents.fx_pilot import _specialist_directory
from dotrix_backend.modules.agents.runner import _read_only_specialist
from dotrix_backend.modules.agents.workspace_runs import read_only
from dotrix_engine.builtins import builtin, builtin_specs


def test_project_specialist_keeps_authorized_reads_but_no_writes():
    spec = builtin("product")
    project = _read_only_specialist(spec)
    cross = read_only(spec)
    assert {"code.read", "graph.read"} <= set(project.tools)
    assert not {"code.read", "graph.read"} & set(cross.tools)
    assert not {"knowledge.write", "issues.create", "issues.update", "issues.comment", "graph.link"} & set(project.tools)
    assert project.pipeline is None


def test_specialist_does_not_gain_disabled_reads():
    spec = builtin("product")
    spec.tools = [tool for tool in spec.tools if tool not in {"code.read", "graph.read"}]
    assert not {"code.read", "graph.read"} & set(_read_only_specialist(spec).tools)


def test_fx_directory_respects_delegation_contract():
    specs = builtin_specs()
    nova = specs[0].model_copy(update={"can_call": ["product"]})
    assert _specialist_directory(nova, specs) == "Lyra → product"
