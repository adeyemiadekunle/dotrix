"""Host-owned routing for durable tasks in either Chat runtime."""
from dotrix_engine.runtimes import ModelPolicy, ModelSelection


def specialist_model(project, parent, task, spec, preference=None) -> str:
    # Explicit choices remain authoritative, regardless of the automatic policy.
    if explicit := ((preference.model if preference else None) or spec.model):
        return explicit
    strong = parent.conversation_model or project.model
    routine = project.specialist_model or strong
    if not project.automatic_model_routing:
        return routine
    policy = ModelPolicy(
        tiers={"strong": ModelSelection(strong), "routine": ModelSelection(routine)},
        agents={"architecture": "strong", "reviewer": "strong"}, default="routine",
    )
    # This decision uses validated task fields, not model-supplied provider names
    # or keywords in untrusted repository/document text.
    return policy.resolve(task.agent, task_tier="strong" if task.changes_project else None).model
