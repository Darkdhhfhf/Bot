import datetime as dt
import json
import os
import secrets
import time
from typing import Any, Callable, Dict, List, Tuple

import requests


DEFAULT_CONFIG: Dict[str, Any] = {
    "settings": {
        "interval_seconds": 2,
        "client_interval_seconds": 2,
        "max_messages": None,
        "client_max_messages": None,
        "telegram_interval_seconds": None,
        "vk_interval_seconds": None,
        "avoid_duplicate": True,
        "state_file": ".state.json",
        "telegram_parse_mode": "HTML",
        "vk_api_version": "5.199",
    },
    "telegram": {
        "enabled": True,
        "targets": [],
    },
    "vk": {
        "enabled": True,
        "targets": [],
    },
}


def default_config() -> Dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config(path: str, allow_missing: bool = False) -> Dict[str, Any]:
    if not os.path.exists(path):
        if allow_missing:
            return default_config()
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(path: str, config: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"telegram": {}, "vk": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_env(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    data: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def write_env(path: str, updates: Dict[str, str]) -> None:
    data = read_env(path)
    data.update(updates)

    preferred = ["TELEGRAM_BOT_TOKEN", "VK_ACCESS_TOKEN"]
    ordered: List[str] = []
    for key in preferred:
        if key in data:
            ordered.append(key)
    for key in sorted(k for k in data if k not in preferred):
        ordered.append(key)

    with open(path, "w", encoding="utf-8") as f:
        for key in ordered:
            f.write(f"{key}={data[key]}\n")


def render_template(text: str) -> str:
    now = dt.datetime.now()
    values = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        return text.format(**values)
    except KeyError as exc:
        raise ValueError(f"Unknown template field: {exc}") from exc


def send_telegram(
    token: str,
    chat_id: int,
    text: str,
    parse_mode: str | None,
    timeout: int = 10,
) -> Tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        data["parse_mode"] = parse_mode
    response = requests.post(url, data=data, timeout=timeout)
    if not response.ok:
        return False, response.text
    payload = response.json()
    if not payload.get("ok"):
        return False, json.dumps(payload)
    return True, "ok"


def send_vk(
    token: str,
    peer_id: int,
    text: str,
    api_version: str,
    timeout: int = 10,
) -> Tuple[bool, str]:
    url = "https://api.vk.com/method/messages.send"
    data = {
        "access_token": token,
        "peer_id": peer_id,
        "message": text,
        "random_id": secrets.randbits(31),
        "v": api_version,
    }
    response = requests.post(url, data=data, timeout=timeout)
    if not response.ok:
        return False, response.text
    payload = response.json()
    if "error" in payload:
        return False, json.dumps(payload)
    return True, "ok"


def build_tasks(config: Dict[str, Any]) -> List[Tuple[str, int]]:
    tasks: List[Tuple[str, int]] = []
    telegram = config.get("telegram", {})
    vk = config.get("vk", {})
    if telegram.get("enabled"):
        for chat_id in telegram.get("targets", []):
            tasks.append(("telegram", int(chat_id)))
    if vk.get("enabled"):
        for peer_id in vk.get("targets", []):
            tasks.append(("vk", int(peer_id)))
    return tasks


def send_all(
    message: str,
    config: Dict[str, Any],
    telegram_token: str | None,
    vk_token: str | None,
    interval: float,
    dry_run: bool,
    log_fn: Callable[[str], None],
    stop_flag: Callable[[], bool] | None = None,
    max_messages: int | None = None,
) -> None:
    settings = config.get("settings", {})
    telegram_parse_mode = settings.get("telegram_parse_mode") or None
    vk_api_version = str(settings.get("vk_api_version", "5.199"))
    avoid_duplicate = bool(settings.get("avoid_duplicate", True))
    state_path = str(settings.get("state_file", ".state.json"))
    state = load_state(state_path) if avoid_duplicate else {"telegram": {}, "vk": {}}

    tasks = build_tasks(config)
    if not tasks:
        raise ValueError("No targets configured")

    processed = 0
    for index, (platform, target_id) in enumerate(tasks, start=1):
        if stop_flag and stop_flag():
            log_fn("stopped by user")
            break
        if max_messages is not None and processed >= max_messages:
            log_fn("limit reached")
            break
        platform_interval = settings.get(f"{platform}_interval_seconds")
        delay_seconds = interval if platform_interval in (None, "") else float(platform_interval)

        last_entry = state.get(platform, {}).get(str(target_id), {}) if avoid_duplicate else {}
        if avoid_duplicate and last_entry.get("message") == message:
            log_fn(f"skip {platform} -> {target_id} (duplicate)")
            if index < len(tasks):
                time.sleep(delay_seconds)
            continue

        if dry_run:
            log_fn(f"dry-run {platform} -> {target_id}")
        else:
            if platform == "telegram":
                if not telegram_token:
                    raise ValueError("TELEGRAM_BOT_TOKEN is not set")
                ok, detail = send_telegram(telegram_token, target_id, message, telegram_parse_mode)
            else:
                if not vk_token:
                    raise ValueError("VK_ACCESS_TOKEN is not set")
                ok, detail = send_vk(vk_token, target_id, message, vk_api_version)
            if ok:
                log_fn(f"sent {platform} -> {target_id}")
                if avoid_duplicate:
                    state.setdefault(platform, {})[str(target_id)] = {
                        "message": message,
                        "at": dt.datetime.now().isoformat(timespec="seconds"),
                    }
                    save_state(state_path, state)
            else:
                log_fn(f"failed {platform} -> {target_id}: {detail}")
        processed += 1
        if index < len(tasks):
            if stop_flag and stop_flag():
                log_fn("stopped by user")
                break
            if max_messages is not None and processed >= max_messages:
                log_fn("limit reached")
                break
            time.sleep(delay_seconds)
