from nexus.tools.decorators import tool


@tool(name="discovered_one", description="Fixture tool one")
def discovered_one(value: str) -> str:
    return value
