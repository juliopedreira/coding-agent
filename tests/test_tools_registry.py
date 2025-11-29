from lincona.tools.registry import ToolRegistration


def test_tool_registration_fields_are_frozen(dummy_tool_classes):
    EchoRequest, EchoResponse, EchoTool = dummy_tool_classes
    reg = ToolRegistration(
        name="demo",
        description="desc",
        input_model=EchoRequest,
        output_model=EchoResponse,
        handler=lambda req: EchoResponse(msg=req.msg),  # type: ignore[arg-type]
        requires_approval=True,
        result_adapter=lambda out: out.msg,
        end_event_builder=lambda req, res: {"done": res.msg},
    )

    assert reg.name == "demo"
    assert reg.requires_approval is True
    assert reg.result_adapter(EchoResponse(msg="ok")) == "ok"
    assert reg.end_event_builder(EchoRequest(msg="x"), EchoResponse(msg="y"))["done"] == "y"
