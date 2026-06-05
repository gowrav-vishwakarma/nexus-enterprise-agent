"""Concrete channel adapters (Telegram, WhatsApp, ...).

Adapters use ``httpx`` lazily, so importing this package never requires it.
"""

from nexus.channels.adapters.telegram import TelegramAdapter
from nexus.channels.adapters.whatsapp import WhatsAppAdapter

__all__ = ["TelegramAdapter", "WhatsAppAdapter"]
