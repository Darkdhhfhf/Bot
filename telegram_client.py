"""Telegram Client для рассылки через личный аккаунт."""
import asyncio
import logging
from typing import Any, Callable

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


def check_authorization_sync(
    api_id: int,
    api_hash: str,
    session_name: str = "bot_session",
) -> bool:
    """Проверить, авторизован ли клиент (синхронно)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            check_authorization(api_id, api_hash, session_name)
        )
    finally:
        loop.close()


async def check_authorization(
    api_id: int,
    api_hash: str,
    session_name: str = "bot_session",
) -> bool:
    """Проверить, авторизован ли клиент."""
    client = TelegramClient(session_name, api_id, api_hash)
    try:
        await client.connect()
        return await client.is_user_authorized()
    finally:
        await client.disconnect()


def request_code_sync(
    api_id: int,
    api_hash: str,
    phone: str,
    session_name: str = "bot_session",
) -> dict[str, Any]:
    """Запросить код подтверждения (синхронно)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            request_code(api_id, api_hash, phone, session_name)
        )
    finally:
        loop.close()


async def request_code(
    api_id: int,
    api_hash: str,
    phone: str,
    session_name: str = "bot_session",
) -> dict[str, Any]:
    """Запросить код подтверждения."""
    client = TelegramClient(session_name, api_id, api_hash)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
        return {"success": True, "phone_code_hash": result.phone_code_hash}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.disconnect()


def sign_in_sync(
    api_id: int,
    api_hash: str,
    phone: str,
    code: str,
    phone_code_hash: str | None = None,
    password: str | None = None,
    session_name: str = "bot_session",
) -> dict[str, Any]:
    """Авторизоваться с кодом (синхронно)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            sign_in(api_id, api_hash, phone, code, phone_code_hash, password, session_name)
        )
    finally:
        loop.close()


async def sign_in(
    api_id: int,
    api_hash: str,
    phone: str,
    code: str,
    phone_code_hash: str | None = None,
    password: str | None = None,
    session_name: str = "bot_session",
) -> dict[str, Any]:
    """Авторизоваться с кодом подтверждения."""
    client = TelegramClient(session_name, api_id, api_hash)
    try:
        await client.connect()
        if not phone_code_hash:
            return {"success": False, "error": "Не найден phone_code_hash. Сначала запросите код."}
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        is_authorized = await client.is_user_authorized()
        if is_authorized:
            return {"success": True, "message": "Авторизация успешна"}
        else:
            return {"success": False, "error": "Не удалось авторизоваться"}
    except SessionPasswordNeededError:
        if not password:
            return {"success": False, "error": "Требуется пароль двухфакторной защиты."}
        try:
            await client.sign_in(password=password)
            if await client.is_user_authorized():
                return {"success": True, "message": "Авторизация успешна"}
            return {"success": False, "error": "Не удалось авторизоваться"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.disconnect()


def send_to_all_chats_sync(
    api_id: int,
    api_hash: str,
    phone: str,
    message: str,
    log_fn: Callable[[str], None] | None = None,
    dry_run: bool = False,
    skip_archived: bool = False,
    interval_seconds: float = 2.0,
    stop_flag: Callable[[], bool] | None = None,
    max_messages: int | None = None,
) -> dict[str, Any]:
    """Синхронная обёртка для отправки сообщения во все чаты."""
    if log_fn is None:
        log_fn = lambda x: None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        stats = loop.run_until_complete(
            send_to_all_chats(
                api_id=api_id,
                api_hash=api_hash,
                phone=phone,
                message=message,
                log_fn=log_fn,
                dry_run=dry_run,
                skip_archived=skip_archived,
                interval_seconds=interval_seconds,
                stop_flag=stop_flag,
                max_messages=max_messages,
            )
        )
        return stats
    finally:
        loop.close()


async def send_to_all_chats(
    api_id: int,
    api_hash: str,
    phone: str,
    message: str,
    session_name: str = "bot_session",
    log_fn: Callable[[str], None] | None = None,
    dry_run: bool = False,
    skip_archived: bool = False,
    interval_seconds: float = 2.0,
    stop_flag: Callable[[], bool] | None = None,
    max_messages: int | None = None,
) -> dict[str, Any]:
    """
    Отправить сообщение во все чаты аккаунта.
    
    Args:
        api_id: API ID из my.telegram.org
        api_hash: API Hash из my.telegram.org
        phone: Номер телефона аккаунта
        message: Текст сообщения
        session_name: Имя файла сессии
        log_fn: Функция для логирования
        dry_run: Тестовый режим (не отправлять)
        skip_archived: Пропустить архивные чаты
    
    Returns:
        Статистика отправки
    """
    if log_fn is None:
        log_fn = lambda msg: logging.info(msg)

    stats = {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0}

    client = TelegramClient(session_name, api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            raise ValueError("Не авторизован. Сначала пройдите авторизацию через форму.")
        
        log_fn("Подключение успешно ✓")
        log_fn("Получение списка чатов...")
        
        dialogs = await client.get_dialogs()
        
        if skip_archived:
            dialogs = [d for d in dialogs if not d.archived]
        
        stats["total"] = len(dialogs)
        log_fn(f"Найдено чатов: {stats['total']}")
        
        processed = 0
        for idx, dialog in enumerate(dialogs, 1):
            try:
                if stop_flag and stop_flag():
                    log_fn("stopped by user")
                    break
                if max_messages is not None and processed >= max_messages:
                    log_fn("limit reached")
                    break
                chat_name = dialog.name or f"Chat {idx}"
                
                if dry_run:
                    log_fn(f"dry-run {chat_name}")
                    stats["dry_run"] += 1
                else:
                    log_fn(f"[{idx}/{stats['total']}] Отправляю в {chat_name}...")
                    await client.send_message(dialog.entity, message)
                    stats["sent"] += 1
                    log_fn(f"sent {chat_name}")
                    
            except Exception as e:
                stats["failed"] += 1
                log_fn(f"failed {chat_name}: {str(e)}")

            processed += 1

            if idx < stats["total"]:
                if stop_flag and stop_flag():
                    log_fn("stopped by user")
                    break
                if max_messages is not None and processed >= max_messages:
                    log_fn("limit reached")
                    break
                await asyncio.sleep(interval_seconds)
        
        log_fn(f"✓ Готово: {stats['sent']}/{stats['total']} отправлено")
        
    except Exception as e:
        log_fn(f"Ошибка: {str(e)}")
    finally:
        await client.disconnect()
    
    return stats
