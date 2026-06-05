"""Skills storage path resolution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from nexus.storage.paths import get_data_root, tenant_user_dir

_SkillsRoot = Union[str, Path]


def get_skills_root() -> Path:
    """Return the global skills root (default ./skills, overridable via NEXUS_SKILLS_ROOT)."""
    return Path(os.getenv("NEXUS_SKILLS_ROOT", "./skills"))


def global_skills_dir(*, skills_root: Optional[_SkillsRoot] = None) -> Path:
    """Return the global skills directory."""
    return Path(skills_root) if skills_root is not None else get_skills_root()


def tenant_skills_dir(
    tenant_id: Optional[str],
    *,
    data_root: Optional[_SkillsRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/skills/ (phase 2)."""
    root = Path(data_root) if data_root is not None else get_data_root()
    from nexus.storage.paths import normalize_tenant_id

    tenant = normalize_tenant_id(tenant_id)
    return root / tenant / "skills"


def user_skills_dir(
    tenant_id: Optional[str],
    user_id: Optional[str],
    *,
    data_root: Optional[_SkillsRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/skills/ (phase 2)."""
    return tenant_user_dir(tenant_id, user_id, data_root=data_root) / "skills"
