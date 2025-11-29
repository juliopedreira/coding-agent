import pytest

from lincona.tools.base import Tool


def test_tool_execute_and_models(dummy_tool_classes):
    EchoRequest, EchoResponse, EchoTool = dummy_tool_classes
    tool = EchoTool()
    res = tool.execute(EchoRequest(msg="hi"))
    assert res.msg == "HI"


def test_tool_abstract_cannot_instantiate(dummy_tool_classes):
    EchoRequest, EchoResponse, _ = dummy_tool_classes

    class IncompleteTool(Tool[EchoRequest, EchoResponse]):
        name = "inc"
        description = ""
        InputModel = EchoRequest
        OutputModel = EchoResponse

    with pytest.raises(TypeError):
        IncompleteTool()  # type: ignore[abstract]
