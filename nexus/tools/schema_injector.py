"""RCS Schema Injector to add _context_updates to tool parameters."""

from typing import Any
from nexus.config.rcs import RuntimeContextSummarizerConfig


class RCSSchemaInjector:
    """Injects _context_updates parameters into JSON Schemas of tools."""

    @staticmethod
    def inject(
        schema: dict[str, Any],
        rcs_config: RuntimeContextSummarizerConfig,
    ) -> dict[str, Any]:
        """Inject the _context_updates parameters schema into the tool's schema.

        Modifies the schema in-place or returns a copy with the parameter injected.
        """
        if not rcs_config or not rcs_config.enabled:
            return schema

        if "properties" not in schema:
            schema["properties"] = {}

        description = rcs_config.context_updates_param_description or (
            "(Optional) Compress previous tool results you no longer need in full."
        )

        schema["properties"][rcs_config.context_updates_param_name] = {
            "type": "array",
            "description": description,
            "items": {
                "type": "object",
                "required": ["tc_id", "summary"],
                "properties": {
                    "tc_id": {
                        "type": "string",
                        "description": "The TC tag of the result to compress, e.g. 'TC1', 'TC3'"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Your compact summary of that result. Pass '[]' if the result had nothing useful and should be dropped."
                    }
                }
            },
            "default": []
        }

        return schema
