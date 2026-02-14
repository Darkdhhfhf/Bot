import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request

import sender
import client_sender
import telegram_client

app = Flask(__name__)

STOP_EVENT = threading.Event()
SEND_LOCK = threading.Lock()
SEND_THREAD: threading.Thread | None = None
SEND_STATUS: dict[str, Any] = {
    "active": False,
    "logs": [],
    "stats": {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0},
    "error": None,
    "success": None,
    "mode": None,
}

CONFIG_PATH = os.getenv("BOT_CONFIG_PATH", "config.json")
ENV_PATH = os.getenv("BOT_ENV_PATH", ".env")


def _parse_targets(raw_text: str) -> list[int]:
    ids: list[int] = []
    for raw in raw_text.replace(",", "\n").splitlines():
        value = raw.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Некорректный ID: {value}") from exc
    return ids


def _get_form_value(key: str, fallback: str = "") -> str:
    value = request.form.get(key)
    return value if value is not None else fallback


def _parse_schedule_time(raw_value: str) -> tuple[int, int]:
    parts = raw_value.strip().split(":")
    if len(parts) < 2:
        raise ValueError("Некорректный формат времени. Используйте HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Некорректное время расписания")
    return hour, minute


def _get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _reset_send_status(mode: str | None = None) -> None:
    with SEND_LOCK:
        SEND_STATUS["active"] = True
        SEND_STATUS["logs"] = []
        SEND_STATUS["stats"] = {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0}
        SEND_STATUS["error"] = None
        SEND_STATUS["success"] = None
        SEND_STATUS["mode"] = mode


def _append_log(message: str) -> None:
    with SEND_LOCK:
        SEND_STATUS["logs"].append(message)
        stats = SEND_STATUS["stats"]
        if message.startswith("sent "):
            stats["sent"] += 1
        elif message.startswith("failed "):
            stats["failed"] += 1
        elif message.startswith("skip "):
            stats["skipped"] += 1
        elif message.startswith("dry-run "):
            stats["dry_run"] += 1


def _set_send_status(**updates: Any) -> None:
    with SEND_LOCK:
        SEND_STATUS.update(updates)


def _snapshot_send_status() -> dict[str, Any]:
    with SEND_LOCK:
        return {
            "active": SEND_STATUS["active"],
            "logs": list(SEND_STATUS["logs"]),
            "stats": dict(SEND_STATUS["stats"]),
            "error": SEND_STATUS["error"],
            "success": SEND_STATUS["success"],
            "mode": SEND_STATUS["mode"],
        }


def _run_scheduled_send(config: dict[str, Any], env_data: dict[str, str]) -> bool:
    STOP_EVENT.clear()
    payload = config.get("last_payload", {})
    mode = payload.get("mode")
    message_raw = (payload.get("message") or "").strip()
    if not mode or not message_raw:
        logging.warning("Schedule skipped: missing payload")
        return False

    message = sender.render_template(message_raw)

    if mode == "client":
        api_id = int(env_data.get("TELEGRAM_API_ID", 0))
        api_hash = env_data.get("TELEGRAM_API_HASH", "")
        phone = env_data.get("TELEGRAM_PHONE", "")
        client_interval = float(config.get("settings", {}).get("client_interval_seconds", 2))
        client_max_messages = config.get("settings", {}).get("client_max_messages")
        client_max_messages = int(client_max_messages) if client_max_messages not in (None, "") else None
        if not api_id or not api_hash or not phone:
            logging.error("Schedule error: missing client credentials")
            return False
        telegram_client.send_to_all_chats_sync(
            api_id=api_id,
            api_hash=api_hash,
            phone=phone,
            message=message,
            log_fn=logging.info,
            dry_run=bool(payload.get("dry_run", False)),
            skip_archived=bool(payload.get("skip_archived", False)),
            interval_seconds=client_interval,
            stop_flag=STOP_EVENT.is_set,
            max_messages=client_max_messages,
        )
        return True

    settings = config.get("settings", {})
    interval = float(settings.get("interval_seconds", 2))
    max_messages = settings.get("max_messages")
    max_messages = int(max_messages) if max_messages not in (None, "") else None
    sender.send_all(
        message=message,
        config=config,
        telegram_token=env_data.get("TELEGRAM_BOT_TOKEN"),
        vk_token=env_data.get("VK_ACCESS_TOKEN"),
        interval=interval,
        dry_run=bool(payload.get("dry_run", False)),
        log_fn=logging.info,
        stop_flag=STOP_EVENT.is_set,
        max_messages=max_messages,
    )
    return True


def _run_send_worker(payload: dict[str, Any]) -> None:
    try:
        mode = payload["mode"]
        STOP_EVENT.clear()
        _reset_send_status(mode=mode)

        if mode == "client":
            result_stats = telegram_client.send_to_all_chats_sync(
                api_id=payload["api_id"],
                api_hash=payload["api_hash"],
                phone=payload["phone"],
                message=payload["message"],
                log_fn=_append_log,
                dry_run=payload["dry_run"],
                skip_archived=payload["skip_archived"],
                interval_seconds=payload["interval_seconds"],
                stop_flag=STOP_EVENT.is_set,
                max_messages=payload["max_messages"],
            )
            _set_send_status(stats=result_stats)
            _set_send_status(success="Рассылка по аккаунту выполнена")
        else:
            tasks = sender.build_tasks(payload["config"])
            _set_send_status(stats={"total": len(tasks), "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0})

            sender.send_all(
                message=payload["message"],
                config=payload["config"],
                telegram_token=payload["telegram_token"],
                vk_token=payload["vk_token"],
                interval=payload["interval"],
                dry_run=payload["dry_run"],
                log_fn=_append_log,
                stop_flag=STOP_EVENT.is_set,
                max_messages=payload["max_messages"],
            )
            _set_send_status(success="Рассылка выполнена")
    except Exception as exc:
        logging.exception("Send error")
        _set_send_status(error=str(exc))
    finally:
        if STOP_EVENT.is_set():
            with SEND_LOCK:
                if SEND_STATUS.get("error") is None:
                    SEND_STATUS["success"] = "Рассылка остановлена"
        _set_send_status(active=False)


def _start_send_thread(payload: dict[str, Any]) -> None:
    global SEND_THREAD
    with SEND_LOCK:
        if SEND_STATUS["active"]:
            raise ValueError("Рассылка уже выполняется")
        SEND_STATUS["active"] = True
        SEND_STATUS["error"] = None
        SEND_STATUS["success"] = None
        SEND_STATUS["logs"] = []
        SEND_STATUS["stats"] = {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0}
        SEND_STATUS["mode"] = payload.get("mode")

    SEND_THREAD = threading.Thread(target=_run_send_worker, args=(payload,), daemon=True)
    SEND_THREAD.start()


def _schedule_loop() -> None:
    while True:
        try:
            config = sender.load_config(CONFIG_PATH, allow_missing=True)
            settings = config.setdefault("settings", {})
            if settings.get("schedule_enabled"):
                schedule_time = settings.get("schedule_time", "").strip()
                tz_name = settings.get("schedule_timezone", "UTC").strip() or "UTC"
                if schedule_time:
                    hour, minute = _parse_schedule_time(schedule_time)
                    now = datetime.now(_get_timezone(tz_name))
                    today = now.strftime("%Y-%m-%d")
                    last_run = settings.get("schedule_last_run")
                    if now.hour == hour and now.minute == minute and last_run != today:
                        env_data = sender.read_env(ENV_PATH)
                        success = _run_scheduled_send(config, env_data)
                        settings["schedule_last_run"] = today
                        settings["schedule_last_status"] = "ok" if success else "failed"
                        settings["schedule_last_at"] = now.isoformat()
                        sender.save_config(CONFIG_PATH, config)
            time.sleep(20)
        except Exception:
            logging.exception("Schedule loop error")
            time.sleep(30)


def start_scheduler() -> None:
    thread = threading.Thread(target=_schedule_loop, daemon=True)
    thread.start()


@app.route("/check_auth", methods=["POST"])
def check_auth() -> dict[str, Any]:
    """Проверить, авторизован ли клиент."""
    try:
        data = request.get_json()
        api_id = int(data.get("api_id", 0))
        api_hash = data.get("api_hash", "").strip()
        
        if not api_id or not api_hash:
            return jsonify({"authorized": False, "error": "API ID и API Hash обязательны"})
        
        is_authorized = telegram_client.check_authorization_sync(api_id, api_hash)
        return jsonify({"authorized": is_authorized})
    except Exception as e:
        return jsonify({"authorized": False, "error": str(e)})


@app.route("/request_code", methods=["POST"])
def request_code() -> dict[str, Any]:
    """Запросить код подтверждения."""
    try:
        data = request.get_json()
        api_id = int(data.get("api_id", 0))
        api_hash = data.get("api_hash", "").strip()
        phone = data.get("phone", "").strip()
        
        if not api_id or not api_hash or not phone:
            return jsonify({"success": False, "error": "Заполните все поля"})
        
        result = telegram_client.request_code_sync(api_id, api_hash, phone)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/sign_in", methods=["POST"])
def sign_in() -> dict[str, Any]:
    """Авторизоваться с кодом."""
    try:
        data = request.get_json()
        api_id = int(data.get("api_id", 0))
        api_hash = data.get("api_hash", "").strip()
        phone = data.get("phone", "").strip()
        code = data.get("code", "").strip()
        phone_code_hash = data.get("phone_code_hash", "").strip()
        password = data.get("password", "").strip()
        
        if not api_id or not api_hash or not phone or not code:
            return jsonify({"success": False, "error": "Заполните все поля"})
        if not phone_code_hash:
            return jsonify({"success": False, "error": "Не найден phone_code_hash. Сначала запросите код."})
        
        result = telegram_client.sign_in_sync(api_id, api_hash, phone, code, phone_code_hash, password)
        
        # Сохраняем credentials при успешной авторизации
        if result.get("success"):
            env_data = sender.read_env(ENV_PATH)
            env_data.update({
                "TELEGRAM_API_ID": str(api_id),
                "TELEGRAM_API_HASH": api_hash,
                "TELEGRAM_PHONE": phone,
            })
            sender.write_env(ENV_PATH, env_data)
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/stop_send", methods=["POST"])
def stop_send() -> dict[str, Any]:
    STOP_EVENT.set()
    return {"success": True}


@app.route("/send_status", methods=["GET"])
def send_status() -> dict[str, Any]:
    return _snapshot_send_status()


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    config = sender.load_config(CONFIG_PATH, allow_missing=True)
    env_data = sender.read_env(ENV_PATH)
    logs: list[str] = []
    error: str | None = None
    success: str | None = None
    stats = {"total": 0, "sent": 0, "failed": 0, "skipped": 0, "dry_run": 0}

    if request.method == "POST":
        try:
            action = _get_form_value("action", "send")
            schedule_enabled = request.form.get("schedule_enabled") == "on"
            schedule_time = _get_form_value("schedule_time", "").strip()
            schedule_timezone = _get_form_value("schedule_timezone", "Europe/Moscow").strip() or "Europe/Moscow"
            if schedule_enabled and not schedule_time:
                raise ValueError("Укажите время для расписания")
            if schedule_enabled:
                _parse_schedule_time(schedule_time)

            # Определяем режим: bot или client
            mode = _get_form_value("mode", "bot")
            
            if mode == "client":
                # Режим Client API (подключение к аккаунту)
                api_id = _get_form_value("telegram_api_id", "").strip()
                api_hash = _get_form_value("telegram_api_hash", "").strip()
                phone = _get_form_value("telegram_phone", "").strip()
                skip_archived = request.form.get("skip_archived") == "on"
                client_interval_raw = _get_form_value("client_interval_seconds", "2").strip()
                client_interval = float(client_interval_raw or 2)
                client_max_messages_raw = _get_form_value("client_max_messages", "").strip()
                client_max_messages = int(client_max_messages_raw) if client_max_messages_raw else None
                
                if not api_id or not api_hash or not phone:
                    raise ValueError("Укажите API ID, API Hash и номер телефона")
                
                message_raw = _get_form_value("message", "").strip()
                if not message_raw:
                    raise ValueError("Введите текст сообщения")
                
                dry_run = request.form.get("dry_run") == "on"

                settings = config.setdefault("settings", {})
                settings["schedule_enabled"] = schedule_enabled
                settings["schedule_time"] = schedule_time
                settings["schedule_timezone"] = schedule_timezone
                settings["client_interval_seconds"] = client_interval
                settings["client_max_messages"] = client_max_messages
                config["last_payload"] = {
                    "mode": "client",
                    "message": message_raw,
                    "dry_run": dry_run,
                    "skip_archived": skip_archived,
                    "max_messages": client_max_messages,
                }

                sender.write_env(
                    ENV_PATH,
                    {
                        "TELEGRAM_API_ID": api_id,
                        "TELEGRAM_API_HASH": api_hash,
                        "TELEGRAM_PHONE": phone,
                    },
                )

                if action == "save_schedule":
                    sender.save_config(CONFIG_PATH, config)
                    success = "Расписание сохранено"
                    raise StopIteration

                message = sender.render_template(message_raw)
                payload = {
                    "mode": "client",
                    "api_id": int(api_id),
                    "api_hash": api_hash,
                    "phone": phone,
                    "message": message,
                    "dry_run": dry_run,
                    "skip_archived": skip_archived,
                    "interval_seconds": client_interval,
                    "max_messages": client_max_messages,
                }

                sender.save_config(CONFIG_PATH, config)
                _start_send_thread(payload)
                success = "Рассылка запущена"
            else:
                # Режим Bot API (текущая логика)
                existing_settings = config.get("settings", {})
                interval_value = float(_get_form_value("interval_seconds", "2"))
                telegram_interval_raw = _get_form_value("telegram_interval_seconds", "").strip()
                vk_interval_raw = _get_form_value("vk_interval_seconds", "").strip()
                max_messages_raw = _get_form_value("max_messages", "").strip()
                max_messages = int(max_messages_raw) if max_messages_raw else None

                config = sender.default_config()
                config["settings"]["interval_seconds"] = interval_value
                config["settings"]["telegram_interval_seconds"] = (
                    None if telegram_interval_raw == "" else float(telegram_interval_raw)
                )
                config["settings"]["vk_interval_seconds"] = None if vk_interval_raw == "" else float(vk_interval_raw)
                config["settings"]["telegram_parse_mode"] = _get_form_value("telegram_parse_mode", "").strip()
                config["settings"]["vk_api_version"] = _get_form_value("vk_api_version", "5.199").strip() or "5.199"
                config["settings"]["avoid_duplicate"] = request.form.get("avoid_duplicate") == "on"
                config["settings"]["schedule_enabled"] = schedule_enabled
                config["settings"]["schedule_time"] = schedule_time
                config["settings"]["schedule_timezone"] = schedule_timezone
                config["settings"]["schedule_last_run"] = existing_settings.get("schedule_last_run")
                config["settings"]["schedule_last_status"] = existing_settings.get("schedule_last_status")
                config["settings"]["schedule_last_at"] = existing_settings.get("schedule_last_at")
                config["settings"]["client_interval_seconds"] = existing_settings.get("client_interval_seconds", 2)
                config["settings"]["client_max_messages"] = existing_settings.get("client_max_messages")
                config["settings"]["max_messages"] = max_messages

                config["telegram"]["enabled"] = request.form.get("telegram_enabled") == "on"
                config["telegram"]["targets"] = _parse_targets(_get_form_value("telegram_targets", ""))

                config["vk"]["enabled"] = request.form.get("vk_enabled") == "on"
                config["vk"]["targets"] = _parse_targets(_get_form_value("vk_targets", ""))

                telegram_token = _get_form_value("telegram_token", "").strip()
                vk_token = _get_form_value("vk_token", "").strip()
                dry_run = request.form.get("dry_run") == "on"

                sender.write_env(
                    ENV_PATH,
                    {
                        "TELEGRAM_BOT_TOKEN": telegram_token,
                        "VK_ACCESS_TOKEN": vk_token,
                    },
                )

                message_raw = _get_form_value("message", "").strip()
                if not message_raw:
                    raise ValueError("Введите текст сообщения")

                config["last_payload"] = {
                    "mode": "bot",
                    "message": message_raw,
                    "dry_run": dry_run,
                    "max_messages": max_messages,
                }

                if action == "save_schedule":
                    sender.save_config(CONFIG_PATH, config)
                    success = "Расписание сохранено"
                    raise StopIteration

                message = sender.render_template(message_raw)

                settings = config.get("settings", {})
                interval = float(settings.get("interval_seconds", 2))

                payload = {
                    "mode": "bot",
                    "message": message,
                    "config": config,
                    "telegram_token": telegram_token or env_data.get("TELEGRAM_BOT_TOKEN"),
                    "vk_token": vk_token or env_data.get("VK_ACCESS_TOKEN"),
                    "interval": interval,
                    "dry_run": dry_run,
                    "max_messages": max_messages,
                }

                sender.save_config(CONFIG_PATH, config)
                _start_send_thread(payload)
                success = "Рассылка запущена"
        except Exception as exc:
            if isinstance(exc, StopIteration):
                pass
            else:
                logging.exception("Send error")
                error = str(exc)

        wants_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.accept_mimetypes.best == "application/json"
        )
        if wants_json:
            if action == "send" and not error:
                status = _snapshot_send_status()
                return jsonify({
                    "success": success,
                    "error": error,
                    "active": status["active"],
                    "logs": status["logs"],
                    "stats": status["stats"],
                })
            return jsonify({"success": success, "error": error, "logs": logs, "stats": stats})

    settings = config.get("settings", {})
    telegram = config.get("telegram", {})
    vk = config.get("vk", {})

    return render_template(
        "index.html",
        config=config,
        settings=settings,
        telegram=telegram,
        vk=vk,
        env_data=env_data,
        logs=logs,
        error=error,
        success=success,
        stats=stats,
    )


@app.route("/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


if __name__ == "__main__":
    start_scheduler()
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
