"""Default prompt templates and constants for the Nexus Agent Framework."""

# RCS System Block - appended to system prompt when RCS is enabled
DEFAULT_RCS_SYSTEM_BLOCK = """## Context Compression Instructions (_context_updates)

You have access to an optional parameter `_context_updates` in every tool call.
This parameter allows you to compress historical tool results to save context window space.

### How it works:

1. Tool results in your context may be tagged with `[TC{n}]` (e.g., `[TC1]`, `[TC2]`)
2. These tags indicate results that have NOT yet been summarized
3. When calling your next tool, you CAN include `_context_updates` to summarize old TCs
4. Pass an empty list `[]` if you don't want to summarize anything this turn

### Format:

```
_context_updates = [
    {"tc_id": "TC1", "summary": "Brief summary of TC1's result"},
    {"tc_id": "TC2", "summary": "Brief summary of TC2's result"},
]
```

### Rules:
- Only summarize TCs that are tagged with `[TC{n}]` in your current context
- Summaries should be CONCISE but preserve KEY information (numbers, names, URLs, code snippets)
- If a TC result is empty or not useful, pass `"[]"` (empty sentinel) to drop it from context
- You may summarize 0, some, or all tagged TCs each turn
- Do NOT reference TCs from other sessions or groups

### Example:

Instead of keeping full 5000-token file content:
  TC1 summary: "main.py: Flask app with 3 routes (/health, /users, /orders), uses SQLAlchemy, 247 lines"

Instead of keeping full test output:
  TC2 summary: "Tests: 12 passed, 2 failed (validation and auth tests)"

This compression is done IN-LINE with your tool call - no extra API calls needed.
"""

# Compact prompt - used by ServerCompactor fallback (separate LLM call)
DEFAULT_COMPACTOR_PROMPT = """A tool call was made during an AI agent run and returned the result below.
The agent has not yet compressed this result and the context window is at risk of overflowing.

Your job: Write a 1-3 sentence factual summary of the most important information in the result.
Focus on facts that an agent would need to reference later.
If the result contains nothing useful (errors, empty responses, irrelevant data), output exactly: []

Tool: {tool_name}
Input: {tool_input}
Result:
---
{raw_response}
---

Compact summary (or []):"""

# Default system prompt template (Jinja2)
DEFAULT_SYSTEM_TEMPLATE = """You are {{ persona.role }}.

Goal: {{ persona.goal }}

{% if persona.backstory %}
Background: {{ persona.backstory }}
{% endif %}

{% if cross_session_entity_memory %}
## About this user (across conversations)
{% for key, value in cross_session_entity_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

{% if working_memory %}
## Your Working Notes
{{ working_memory }}
{% endif %}

{% if entity_memory %}
## Known Facts (this conversation)
{% for key, value in entity_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

Today's date: {{ current_date }}"""

# Entity extraction prompt
DEFAULT_ENTITY_EXTRACTION_PROMPT = """Extract key facts and entities from the following conversation. Return as a JSON object with string keys and string values.

Conversation:
{conversation}

Extract: names, numbers, dates, URLs, key findings, decisions made.
Return ONLY valid JSON, no markdown formatting."""

# Memory curator prompt - used by MemoryCurator (separate LLM call).
# Placeholders {existing_entities}, {existing_working}, {conversation} are filled via
# str.replace (NOT str.format), so literal JSON braces below are safe.
DEFAULT_SESSION_MEMORY_CURATOR_PROMPT = """You are a memory curator for an AI agent. Read the recent conversation and decide what durable information is worth remembering for future turns. Keep memory MINIMAL and high-signal.

Return ONLY a JSON object with this exact shape (no markdown fences, no commentary):
{"entities": {"fact_key": "concise fact value"}, "working_memory": "short notes for the current task (or empty string)"}

Rules:
- entities: durable, stable facts (names, ids, preferences, decisions). Use short, stable keys so updates overwrite cleanly. Omit ephemeral details.
- working_memory: a brief scratchpad for the ACTIVE task. Return the full updated value, not a diff. Keep it short. Return "" to leave it unchanged.
- If nothing is worth remembering, return {"entities": {}, "working_memory": ""}.
- Prefer updating existing keys over adding near-duplicates.

Existing entities (JSON, may be empty):
{existing_entities}

Existing working memory (may be empty):
{existing_working}

Recent conversation:
{conversation}

JSON:"""

# Default tool call schema description for RCS
DEFAULT_CONTEXT_UPDATES_PARAM_DESC = """_context_updates (list of dict, optional): Context compression updates for previous tool call results.
Each dict has: {"tc_id": "TC{n}", "summary": "brief summary"}.
Pass [] if no compression needed. Only summarize TCs tagged with [TC{n}] in your context.
This is OPTIONAL - include it to compress historical tool results and save context space."""
