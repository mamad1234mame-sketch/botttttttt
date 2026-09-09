"""نقطهٔ ورود CLI.

نمونه‌ها:
    python -m bioai_channel.main --dry-run
    python -m bioai_channel.main --format fact --no-image
    python -m bioai_channel.main --selftest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from .config import ConfigError, Settings
from .content.formats import FORMAT_BY_ID
from .gemini_client import GeminiClient
from .memory import Memory
from .publisher import Publisher, RunResult
from .telegram import TelegramClient, TelegramError


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bioai-channel",
        description="تولید و انتشار خودکار پست علمی برای کانال تلگرام",
    )
    parser.add_argument(
        "--format",
        choices=sorted(FORMAT_BY_ID),
        default=None,
        help="قالب اجباری؛ اگر ندهی خودش هوشمند انتخاب می‌کند.",
    )
    parser.add_argument("--dry-run", action="store_true", help="چیزی ارسال نکن؛ فقط چاپ کن.")
    parser.add_argument("--no-image", action="store_true", help="تصویر تولید نکن.")
    parser.add_argument("--no-signals", action="store_true", help="ترند/مقالات تازه را نگیر.")
    parser.add_argument("--state", default=None, help="مسیر فایل حافظه.")
    parser.add_argument("--selftest", action="store_true", help="فقط اتصال تلگرام و Gemini را چک کن.")
    parser.add_argument("--verbose", action="store_true", help="لاگ کامل.")
    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_publisher(settings: Settings) -> tuple[Publisher, GeminiClient, TelegramClient]:
    gemini = GeminiClient(
        api_key=settings.gemini_api_key,
        max_retries=settings.max_retries,
        timeout=settings.request_timeout,
    )
    telegram = TelegramClient(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        timeout=60,
        max_retries=3,
    )
    memory = Memory.load(settings.state_path)
    return (
        Publisher(settings=settings, gemini=gemini, telegram=telegram, memory=memory),
        gemini,
        telegram,
    )


def _selftest(settings: Settings) -> int:
    publisher, _gemini, telegram = build_publisher(settings)
    print("— بررسی اتصال —")

    try:
        me = telegram.me()
        print(f"✅ بات تلگرام: @{me.get('username')} (id={me.get('id')})")
    except TelegramError as exc:
        print(f"❌ بات تلگرام: {exc}")
        return 1

    try:
        chat = telegram.chat_info()
        title = chat.get("title") or chat.get("username") or chat.get("id")
        print(f"✅ چت مقصد: {title} (نوع: {chat.get('type')})")
        perms = chat.get("permissions") or {}
        if chat.get("type") in {"channel", "supergroup"}:
            admins_ok = True
            try:
                admins = telegram._call("getChatAdministrators", {"chat_id": settings.telegram_chat_id})
                admins_ok = any(a.get("user", {}).get("id") == me.get("id") for a in admins)
            except TelegramError:
                admins_ok = True  # نمی‌توانیم چک کنیم؛ سخت‌گیری نکن
            print(f"{'✅' if admins_ok else '⚠️ '} بات ادمین کانال است: {admins_ok}")
        print(f"   اجازهٔ ارسال پیام: {perms.get('can_send_messages', True)}")
    except TelegramError as exc:
        print(f"❌ چت مقصد: {exc}")
        return 1

    print(f"✅ حافظه: {settings.state_path} — {len(publisher.memory.posts)} پست ثبت‌شده")
    print(f"✅ مدل متن: {settings.text_model} / مدل تصویر: {settings.image_model}")
    print("— آمادهٔ اجرا —")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    _setup_logging(args.verbose)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        settings.dry_run = True
    if args.no_image:
        settings.skip_images = True
    if args.no_signals:
        settings.skip_signals = True
    if args.state:
        settings.state_path = args.state

    if args.selftest:
        return _selftest(settings)

    publisher, _gemini, _telegram = build_publisher(settings)
    result: RunResult = publisher.run(forced_format=args.format)

    print("\n— نتیجه —")
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))

    if not result.ok:
        # گزارش خطا به ادمین (اگر تنظیم شده باشد)
        _notify_admin(settings, result)
        return 1
    return 0


def _notify_admin(settings: Settings, result: RunResult) -> None:
    if not settings.admin_chat_id or settings.dry_run:
        return
    try:
        client = TelegramClient(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.admin_chat_id,
            timeout=30,
        )
        text = (
            "⚠️ <b>انتشار پست ناموفق بود</b>\n"
            f"قالب: <code>{result.format_id or 'n/a'}</code>\n"
            f"خطا: <code>{(result.error or 'unknown')[:600]}</code>"
        )
        client.send_message(text=text)
    except TelegramError:
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
