# 🔁 Mini 9: Agent Reasoning Loop
 
Full agent loop with multi-step reasoning.
 
## 🎯 Learning Objectives
 
- ✅ Agent loop pattern
- ✅ Stop conditions
- ✅ Multi-step reasoning
- ✅ Tool chaining
- ✅ Max iterations safety
- ✅ Error recovery
 
## 🏗️ Architecture
 
````
While not done:
  1. Send prompt + tools to LLM
  2. LLM thinks and chooses tool(s)
  3. Execute tool(s)
  4. Feed result back to LLM
  5. Check stop condition
````
 
## 📚 Tech Stack
 
- **FastAPI** - Web framework
- **Anthropic Claude** - LLM
- **Tool registry** - From Mini 8
 
## 🚀 Quick Start
 
```bash
# Copy from Mini 8 + add agent executor
uv run uvicorn app.main:app --reload
```
 
## 📝 API Endpoints
 
```bash
# Multi-step agent task
POST /agent/execute-loop
{
  "prompt": "Calculate 50 + 30, then multiply by 2. Also tell me the time."
}
 
Response:
{
  "final_answer": "50 + 30 = 80, multiplied by 2 = 160. Current time is...",
  "iterations": 2,
  "tools_used": ["calculate", "get_time"],
  "execution_log": [...]
}
```
 
## 🧠 Agent Loop Implementation
 
```python
async def execute(self, prompt: str) -> dict:
    messages = [{"role": "user", "content": prompt}]
    iteration = 0
    
    while iteration < self.max_iterations:
        iteration += 1
        
        # 1. Call LLM
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            tools=registry.get_tools_for_api(),
            messages=messages
        )
        
        # 2. Check stop condition
        if response.stop_reason == "end_turn":
            # LLM decided it's done
            return extract_text_response(response)
        
        # 3. Process tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = registry.execute(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)
                })
        
        # 4. Feed back to LLM
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    
    # Max iterations reached
    return {"error": "Max iterations exceeded"}
```
 
## 📊 Execution Flow Example
 
````
User: "Find flights BA→Barcelona under $800, and notify me"
 
Iteration 1:
  LLM: "I need to search for flights"
  Call: search_flights("BA", "Barcelona", 800)
  Result: [Flights found: LATAM $750]
  
Iteration 2:
  LLM: "Found flights under budget. Send notification."
  Call: send_notification("user123", "Found LATAM $750")
  Result: Notification sent
  
Iteration 3:
  LLM: "Task complete"
  Stop: end_turn
  
Final: "I found a LATAM flight for $750 and sent notification"
````
 
## 🎓 Key Concepts
 
**Stop Reason:**
- "end_turn": LLM finished reasoning
- "tool_use": LLM wants to use tool(s)
- "max_tokens": Hit token limit
 
**Max Iterations:**
- Safety mechanism
- Prevent infinite loops
- Default: 10 iterations
 
**Execution Log:**
```python
{
  "iteration": 1,
  "stop_reason": "tool_use",
  "tools_called": ["search_flights"],
  "text": "I'll search for flights..."
}
```
 
## 🧪 Testing Complex Scenarios
 
```bash
# Simple task (1 iteration)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "What time is it?"}'
 
# Medium task (2 iterations)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "Calculate 50 + 30, then tell me the time"}'
 
# Complex task (3+ iterations)
curl -X POST http://localhost:8000/agent/execute-loop \
  -d '{"prompt": "Search for Python, calculate 10 * 5, get time, then summarize"}'
```
 
## 📂 Folder Structure
 
````
mini-9-agent-loop/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── tools.py                 # From Mini 8
│   ├── services/
│   │   └── agent_executor.py   # NEW: Agent loop
│   ├── schemas/
│   │   └── agent.py
│   └── routes/
│       └── agent.py             # UPDATED: Add loop endpoint
└── pyproject.toml
````
 
## 📈 Performance
 
**Expected:**
- Iteration 1: ~500-1000ms (LLM call + tool)
- Iteration 2: ~500-1000ms
- Total for 2-3 tools: ~1-3 seconds
 
## ⚡ Advanced Patterns
 
**With Database Persistence:**
```python
# Save execution log
task = Task(
    id=task_id,
    prompt=prompt,
    status="running",
    execution_log=[]
)
db.add(task)
 
# Update after each iteration
task.execution_log.append(iteration_log)
db.commit()
```
 
**With Error Recovery:**
```python
try:
    result = registry.execute(tool_name, tool_input)
except Exception as e:
    # Don't break loop, inform LLM
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"Error: {e}",
        "is_error": True
    })
    # LLM will try different approach
```
 
## 🚢 Deploy
 
```bash
git add .
git commit -m "Mini 9: Agent reasoning loop"
git push
```
 
## ❓ Troubleshooting
 
**Agent stuck in loop?**
```bash
# Check max_iterations
# Check stop_reason is "end_turn"
# Check tool execution time
 
# Increase timeout if needed
task_time_limit = 60  # seconds
```
 
**Tool not executing next iteration?**
```bash
# Check tool_use_id is correct
# Check tool_result structure
# Look at message history
 
# Debug:
print(f"Messages: {messages}")
print(f"Response: {response}")
```
 
## 📚 Resources
 
- [ReAct Pattern](https://arxiv.org/abs/2210.03629)
- [Agent Frameworks](https://python.langchain.com/docs/modules/agents/)
- [Anthropic Tool Use](https://docs.anthropic.com/claude/docs/tool-use)
 
## ⏱️ Timeline
 
- Setup: 20 min (from Mini 8)
- Agent loop: 1.5 hours
- Testing: 1 hour
- **Total: 3-4 hours**
 
## ✅ Checklist
 
- [ ] Copy from Mini 8
- [ ] Implement agent executor
- [ ] Handle multi-iteration
- [ ] Implement stop conditions
- [ ] Add max iterations safety
- [ ] Test simple queries
- [ ] Test complex workflows
- [ ] Push to GitHub
 
## 🎯 Next: PROJECT 2
 
Ready to combine Celery + Agents? Go to `../../PROYECTOS_COMPLETOS/project-2-agentic-backend/`
 
---
 
**Made as part of Sr Backend Roadmap** 🚀
