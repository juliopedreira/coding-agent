# Tools Authoring Guide

All tools must follow the OpenAI Agents tooling spec and declare inputs/outputs
with **[pydantic2](https://pypi.org/project/pydantic2/)** models. Each tool module owns its models and registers
itself via `tool_registrations(...)`; `ToolRouter` aggregates these and builds
schemas automatically.

## Required pattern

1) Define models **and a Tool subclass** in the tool module:
```python
from pydantic import BaseModel, Field
from lincona.tools.registry import ToolRegistration
from lincona.tools.base import Tool, ToolRequest, ToolResponse

class MyToolInput(ToolRequest):
    query: str = Field(description="What to search for")

class MyToolOutput(ToolResponse):
    results: list[str]

class MyTool(Tool[MyToolInput, MyToolOutput]):
    name = "my_tool"
    description = "Describe what it does"
    InputModel = MyToolInput
    OutputModel = MyToolOutput

    def __init__(self, boundary):
        self.boundary = boundary

    def execute(self, request: MyToolInput) -> MyToolOutput:
        return MyToolOutput(results=[request.query.upper()])

def tool_registrations(boundary, pty_manager=None):
    tool = MyTool(boundary)

    return [
        ToolRegistration(
            name="my_tool",
            description="Describe what it does",
            input_model=MyToolInput,
            output_model=MyToolOutput,
            handler=tool.execute,
            requires_approval=False,
            result_adapter=lambda out: out.model_dump(),  # optional legacy shape
        )
    ]
```

2) Add the module’s registrations to `tools/__init__.py` (`get_tool_registrations`).

3) Update `tools/README.md` with a short description and example input/output
whenever you add or modify a tool.

## Rules & best practices
- **Describe every field** with `Field(..., description=...)`; this becomes the
  LLM-facing schema.
- **Typed outputs**: return Pydantic output models; if callers need another
  shape, use `result_adapter`.
- **Respect boundaries/approvals**: handlers run under the injected
  `FsBoundary`; mark mutating/command tools with `requires_approval=True`.
- **No globals**: avoid module-level mutable state; rely on injected
  boundary/pty_manager.
- **Logging**: ToolRouter logs requests at INFO and responses at DEBUG—do not
  print from handlers.
- **Schema source of truth**: never hand-write JSON schemas; `tool_specs()` uses
  `model_json_schema()` from your input model.
- **Examples**: keep `tools/README.md` examples in sync with reality.

## Best practices for defining functions (tools)
* **Write clear and detailed function names, parameter descriptions, and instructions.**
    * **Explicitly describe the purpose of the function and each parameter** (and its format), and what the output represents.
    * **Use the system prompt to describe when (and when not) to use each function**. Generally, tell the model exactly what to do.
    * **Include examples and edge cases**, especially to rectify any recurring failures. (Note: Adding examples may hurt performance for reasoning models.)

* **Apply software engineering best practices.**
    * **Make the functions obvious and intuitive**. (principle of least surprise)
    * **Use enums and object structure to make invalid states unrepresentable**. (e.g. toggle_light(on: bool, off: bool) allows for invalid calls)
    * **Pass the intern test**. Can an intern/human correctly use the function given nothing but what you gave the model? (If not, what questions do they ask you? Add the answers to the prompt.)

* **Offload the burden from the model and use code where possible**.
    * **Don't make the model fill arguments you already know**. For example, if you already have an order_id based on a previous menu, don't have an order_id param – instead, have no params submit_refund() and pass the order_id with code.
    * **Combine functions that are always called in sequence**. For example, if you always call mark_location() after query_location(), just move the marking logic into the query function call.

* **Keep the number of functions small for higher accuracy**.
    * **Evaluate your performance** with different numbers of functions.
    * **Aim for fewer than 20 functions at any one time**, though this is just a soft suggestion.

Reference: <https://openai.github.io/openai-agents-python/tools/>
