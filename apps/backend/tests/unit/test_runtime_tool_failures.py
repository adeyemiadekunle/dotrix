"""What an fx tool's failure tells the model: the platform's refusals and bad arguments, nothing else."""
import pytest
from pydantic import BaseModel, Field

from dotrix_backend.core.errors import Forbidden
from dotrix_backend.modules.agents.runtime_tools import readable_failures
from dotrix_engine.runtimes import RuntimeTool, RuntimeToolContext, RuntimeToolError
from dotrix_engine.runtimes.fx import _said


class Args(BaseModel):
    key: str = Field(pattern=r"^[a-z]+$")


def _tool(raises: Exception, *, scoped: bool) -> RuntimeTool:
    async def plain(arguments):
        raise raises

    async def scoped_handler(arguments, context):
        raise raises

    return RuntimeTool("t", "A tool", {}, **({"execute_scoped": scoped_handler} if scoped else {"execute": plain}))


async def _call(tool: RuntimeTool):
    if tool.execute_scoped is not None:
        return await tool.execute_scoped({}, RuntimeToolContext("s"))
    return await tool.execute({})


@pytest.mark.parametrize("scoped", [True, False])
async def test_a_refusal_is_said_and_anything_else_is_not(scoped: bool) -> None:
    with pytest.raises(RuntimeToolError, match="You may not do that") as refused:
        await _call(readable_failures(_tool(Forbidden("You may not do that"), scoped=scoped)))
    assert isinstance(refused.value.__cause__, Forbidden)

    try:
        Args.model_validate({"key": "Not Valid"})
    except Exception as invalid:
        with pytest.raises(RuntimeToolError, match=r"Invalid arguments: key: String should match"):
            await _call(readable_failures(_tool(invalid, scoped=scoped)))

    # A crash keeps its own type: the host reports it only as "Tool failed.", with no internals.
    with pytest.raises(RuntimeError, match="connection to 10.0.0.5 refused"):
        await _call(readable_failures(_tool(RuntimeError("connection to 10.0.0.5 refused"), scoped=scoped)))


def test_what_the_model_reads_is_one_bounded_paragraph() -> None:
    assert _said("Not\n  allowed\there") == "Not allowed here"
    assert _said("   ") == "Tool failed."
    long = _said("x" * 5000)
    assert len(long) == 1000 and long.endswith("…")
