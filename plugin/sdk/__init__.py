"""SDK v2 root namespace.

The root package is intentionally conservative: it provides namespace-level
navigation for the primary facades plus SDK-wide constants/version metadata.
Developer-facing APIs should normally be imported from one of:
- `plugin.sdk.plugin`
- `plugin.sdk.extension`
- `plugin.sdk.adapter`
- `plugin.sdk.shared` (advanced)
"""

from __future__ import annotations

from . import adapter, extension, plugin, shared
from .shared.constants import (
    EVENT_META_ATTR,
    HOOK_META_ATTR,
    NEKO_PLUGIN_META_ATTR,
    NEKO_PLUGIN_TAG,
    PERSIST_ATTR,
)
from .shared.constants import SDK_VERSION

__all__ = [
    "plugin",
    "extension",
    "adapter",
    "shared",
    "SDK_VERSION",
    "NEKO_PLUGIN_META_ATTR",
    "NEKO_PLUGIN_TAG",
    "EVENT_META_ATTR",
    "HOOK_META_ATTR",
    "PERSIST_ATTR",
]
