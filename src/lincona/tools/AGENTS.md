# Tools Authoring Guide

All tools must follow the OpenAI Agents tooling spec and declare inputs/outputs
with **Pydantic v2** models. Each tool module owns its models and registers
itself via `tool_registrations(...)`; `ToolRouter` aggregates these and builds
schemas automatically.

## Required pattern

1) Define models and a handler in the tool module:
```python
from pydantic import BaseModel, Field
from lincona.tools.registry import ToolRegistration

class MyToolInput(BaseModel):
    query: str = Field(description="What to search for")

class MyToolOutput(BaseModel):
    results: list[str]

def tool_registrations(boundary, pty_manager=None):
    def handler(data: BaseModel) -> BaseModel:
        typed = MyToolInput.model_validate(data)
        return MyToolOutput(results=[typed.query.upper()])

    return [
        ToolRegistration(
            name="my_tool",
            description="Describe what it does",
            input_model=MyToolInput,
            output_model=MyToolOutput,
            handler=handler,
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

Reference: <https://openai.github.io/openai-agents-python/tools/>
