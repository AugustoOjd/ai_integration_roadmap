# 🔧 Mini 8: LLM Tool Calling
 
Enable LLMs to call functions via tool use.
 
## 🎯 Learning Objectives
 
- ✅ Tool definition and schema
- ✅ Tool calling pattern
- ✅ Function registry
- ✅ Tool execution
- ✅ Result feedback to LLM
- ✅ LLM reasoning loop basics
 
## 🏗️ Architecture
 
````
LLM Request
    ↓
LLM reasons + chooses tool
    ↓
Execute tool
    ↓
Send result back to LLM
    ↓
LLM generates response
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - LLM
- **Pydantic** - Schema validation
 
## 🚀 Quick Start
 
```bash
# 1. Install
poetry add anthropic
 
# 2. Create .env
export ANTHROPIC_API_KEY=sk-ant-...
 
# 3. Run app
poetry run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Simple tool calling
POST /agent/tool-calling
{
  "prompt": "What is 42 times 2?"
}
 
Response:
{
  "prompt": "What is 42 times 2?",
  "reasoning": "I need to calculate 42 * 2",
  "final_answer": "42 times 2 equals 84",
  "tools_used": ["calculate"]
}
```
 
## 🛠️ Defining Tools
 
### Tool Schema
 
```python
tool = {
  "name": "calculate",
  "description": "Calculate mathematical expression",
  "input_schema": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "Math expression (e.g., '2 + 2')"
      }
    },
    "required": ["expression"]
  }
}
```
 
### Tool Implementation
 
```python
def calculate(expression: str) -> dict:
    """Execute math expression"""
    try:
        result = eval(expression)
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}
```
 
### Tool Registry
 
```python
class ToolRegistry:
    def __init__(self):
        self.tools = {}
    
    def register(self, name, desc, schema, func):
        self.tools[name] = {
            "name": name,
            "description": desc,
            "input_schema": schema,
            "func": func
        }
    
    def execute(self, name, input_dict):
        tool = self.tools[name]
        return tool["func"](**input_dict)
```
 
## 🧠 LLM Tool Calling Flow
 
```python
from anthropic import Anthropic
 
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
 
# 1. Send prompt + tools to Claude
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=registry.get_tools_for_api(),
    messages=[{
        "role": "user",
        "content": "Calculate 42 * 2"
    }]
)
 
# 2. Check if Claude wants to use tool
for block in response.content:
    if block.type == "tool_use":
        # Execute tool
        result = registry.execute(block.name, block.input)
        
        # Send result back
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(result)
            }]
        })
```
 
## 📊 Tool Calling vs Function Calling
 
**Tool Calling (Claude):**
```python
tools=[{...}]
# Claude returns: tool_use block
```
 
**Function Calling (OpenAI):**
```python
functions=[{...}]
# GPT returns: function_call object
```
 
Same concept, different API.
 
## 🧪 Testing
 
```bash
# Simple calculation
curl -X POST http://localhost:8000/agent/tool-calling \
  -d '{"prompt": "Calculate 10 + 5"}'
 
# Multiple tool query
curl -X POST http://localhost:8000/agent/tool-calling \
  -d '{"prompt": "What time is it? Also, calculate 100 * 2"}'
 
# Expected: tools_used: ["get_time", "calculate"]
```
 
## 🎓 Available Tools (Mini 8)
 
```python
# 1. Search
def search(query: str) -> dict
 
# 2. Calculate
def calculate(expression: str) -> dict
 
# 3. Get time
def get_current_time() -> dict
```
 
## 📂 Folder Structure
 
````
mini-8-tool-calling/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── tools.py                # NEW: Tool definitions
│   ├── schemas/
│   │   └── agent.py           # NEW: Request/response
│   └── routes/
│       └── agent.py           # NEW: Agent endpoints
└── pyproject.toml
````
 
## ⚡ Key Concepts
 
**Tool Use Block:**
```python
{
  "type": "tool_use",
  "id": "tool_use_123",
  "name": "calculate",
  "input": {"expression": "42 * 2"}
}
```
 
**Tool Result Block:**
```python
{
  "type": "tool_result",
  "tool_use_id": "tool_use_123",
  "content": "84"
}
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 8: LLM tool calling"
git push
```
 
## ❓ Troubleshooting
 
**Tool not being called?**
```bash
# Check tool is in registry
# Check tool description is clear
# Check input schema is correct
```
 
**Tool result not used?**
```bash
# Make sure tool_result block is correct
# Check tool_use_id matches
# Print full response for debugging
```
 
## 📚 Resources
 
- [Claude Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
- [Tool Definition](https://docs.anthropic.com/claude/reference/tool-use)
- [Function Calling Patterns](https://platform.openai.com/docs/guides/function-calling)
 
## ⏱️ Timeline
 
- Setup: 20 min
- Tool registry: 1 hour
- Tool calling: 1.5 hours
- Testing: 30 min
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Install Anthropic SDK
- [ ] Define tool schemas
- [ ] Implement tool functions
- [ ] Create tool registry
- [ ] Implement tool calling
- [ ] Test basic queries
- [ ] Test multiple tools
- [ ] Push to GitHub
 
## 🎯 Next: Mini 9
 
Ready for full agent loop? Go to `../mini-9-agent-loop/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
