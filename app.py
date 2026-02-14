import argparse
import logging
import os

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import sender


def load_message(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    raise ValueError("Message text is required via --text or --text-file")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send messages to Telegram and VK chats")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--text", help="Message text")
    parser.add_argument("--text-file", help="Path to a text file with message")
    parser.add_argument("--interval", type=float, help="Delay between sends in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Do not send, only log")

    args = parser.parse_args()

    if load_dotenv:
        load_dotenv()

    config = sender.load_config(args.config)
    settings = config.get("settings", {})
    interval = args.interval if args.interval is not None else float(settings.get("interval_seconds", 2))

    message = sender.render_template(load_message(args))

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    vk_token = os.getenv("VK_ACCESS_TOKEN")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sender.send_all(
        message=message,
        config=config,
        telegram_token=telegram_token,
        vk_token=vk_token,
        interval=interval,
        dry_run=args.dry_run,
        log_fn=lambda msg: logging.info(msg),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
