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
DEFAULT_COMPACTOR_PROMPT = """You are a context compression assistant. Summarize the following tool result concisely.
Preserve: key numbers, names, URLs, code snippets, critical findings.
Omit: verbose output, repeated information, formatting artifacts.
Keep it under 100 words unless the result is extremely dense with important information.

Tool result to summarize:
{raw_response}

Return ONLY the summary text, nothing else."""

# Default system prompt template (Jinja2)
DEFAULT_SYSTEM_TEMPLATE = """You are {{ persona.role }}.

Goal: {{ persona.goal }}

{% if persona.backstory %}
Background: {{ persona.backstory }}
{% endif %}

{% if working_memory %}
## Your Working Notes
{{ working_memory }}
{% endif %}

{% if entity_memory %}
## Known Facts
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

# Default tool call schema description for RCS
DEFAULT_CONTEXT_UPDATES_PARAM_DESC = """_context_updates (list of dict, optional): Context compression updates for previous tool call results.
Each dict has: {"tc_id": "TC{n}", "summary": "brief summary"}.
Pass [] if no compression needed. Only summarize TCs tagged with [TC{n}] in your context.
This is OPTIONAL - include it to compress historical tool results and save context space."""
