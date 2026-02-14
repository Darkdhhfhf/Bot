import asyncio
import os
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser
from typing import Callable


async def send_to_all_chats(
    api_id: int,
    api_hash: str,
    phone: str,
    message: str,
    skip_archived: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    """Отправить сообщение во все чаты аккаунта через Client API."""
    if log_fn is None:
        log_fn = lambda x: None

    session_file = "telethon_session"
    client = TelegramClient(session_file, api_id, api_hash)

    stats = {"total": 0, "sent": 0, "failed": 0, "skipped": 0}

    try:
        log_fn("Подключение к Telegram...")
        await client.start(phone=phone)
        log_fn("Подключено ✓")

        log_fn("Получение списка чатов...")
        dialogs = await client.get_dialogs()
        
        if skip_archived:
            dialogs = [d for d in dialogs if not d.archived]

        stats["total"] = len(dialogs)
        log_fn(f"Найдено чатов: {stats['total']}")

        for idx, dialog in enumerate(dialogs, 1):
            try:
                entity = dialog.entity
                chat_name = dialog.name or f"Chat {idx}"
                
                log_fn(f"[{idx}/{stats['total']}] {chat_name}...")
                await client.send_message(entity, message)
                stats["sent"] += 1
                log_fn(f"✓ sent to {chat_name}")
            except Exception as e:
                stats["failed"] += 1
                log_fn(f"✗ failed {chat_name}: {str(e)}")

        log_fn(f"Готово: {stats['sent']}/{stats['total']} отправлено")
    except Exception as e:
        log_fn(f"Ошибка: {str(e)}")
    finally:
        await client.disconnect()

    return stats
