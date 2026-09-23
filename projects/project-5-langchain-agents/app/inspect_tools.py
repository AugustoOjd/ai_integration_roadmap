"""Print what the model actually sees of each tool, next to your signature.

    uv run python -m app.inspect_tools

No DB, no API call: schemas are built at import time from signature + docstring.
"""

import inspect
import json

from langchain_anthropic.chat_models import convert_to_anthropic_tool

from app.tools.orders import TOOLS


def main() -> None:
    for t in TOOLS:
        print(f"━━ {t.name} " + "━" * 50)

        # 1. What you wrote. `t.coroutine` is the original async function.
        print("your signature:", inspect.signature(t.coroutine))  # type: ignore[arg-type]

        # 2. tool_call_schema: the args the model may fill. Injected params
        #    (ToolRuntime) are filtered out here.
        print("model-facing args:", list(t.tool_call_schema.model_json_schema()["properties"]))  # type: ignore[union-attr]

        # 3. The exact payload that goes to Anthropic in `tools=[...]`.
        #    This — name, description, input_schema — is the model's whole
        #    knowledge of your function.
        print(json.dumps(convert_to_anthropic_tool(t), indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
