"""اعتبارسنجی فایل‌های GitHub Actions.

هم با pytest اجرا می‌شود، هم مستقیم:  python tests/test_workflows.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(path: pathlib.Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        raise SystemExit("pyyaml نصب نیست: pip install pyyaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _cron_fields(expression: str) -> list[str]:
    return expression.split()


def _check(path: pathlib.Path) -> list[str]:
    errors: list[str] = []
    data = _load(path)
    if not isinstance(data, dict):
        return [f"{path.name}: ساختار YAML معتبر نیست"]

    # کلید trigger در YAML به `on` تبدیل می‌شود که پایتون آن را True می‌خواند
    triggers = data.get("on", data.get(True))
    if not triggers:
        errors.append(f"{path.name}: هیچ trigger ای تعریف نشده")

    if "jobs" not in data:
        errors.append(f"{path.name}: هیچ job ای تعریف نشده")

    for job_name, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict):
            errors.append(f"{path.name}: job {job_name} معتبر نیست")
            continue
        if "runs-on" not in job:
            errors.append(f"{path.name}: job {job_name} مقدار runs-on ندارد")
        if "steps" not in job:
            errors.append(f"{path.name}: job {job_name} هیچ step ای ندارد")

    return errors


def _check_schedule(path: pathlib.Path) -> list[str]:
    errors: list[str] = []
    data = _load(path)
    triggers = data.get("on", data.get(True)) or {}
    if isinstance(triggers, list):
        triggers = {t: None for t in triggers}
    schedule = triggers.get("schedule") if isinstance(triggers, dict) else None
    if not schedule:
        return errors

    for entry in schedule:
        cron = (entry or {}).get("cron", "")
        fields = _cron_fields(cron)
        if len(fields) != 5:
            errors.append(f"{path.name}: cron «{cron}» پنج فیلد ندارد")
            continue
        for field in fields:
            if not re.fullmatch(r"[\d*,/\-]+", field):
                errors.append(f"{path.name}: فیلد نامعتبر «{field}» در cron «{cron}»")
        minute, hour = fields[0], fields[1]
        # گیتهاب بازهٔ زیر ۵ دقیقه را پشتیبانی نمی‌کند
        if minute.startswith("*/") and minute[2:].isdigit() and int(minute[2:]) < 5:
            errors.append(f"{path.name}: بازهٔ زیر ۵ دقیقه در cron پشتیبانی نمی‌شود")
        if minute == "*" and hour == "*":
            errors.append(f"{path.name}: cron هر دقیقه اجرا می‌شود؛ منطقی نیست")
    return errors


def _check_no_secrets(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors = []
    patterns = [
        (r"\b\d{8,10}:AA[0-9A-Za-z_-]{30,}", "توکن بات تلگرام"),
        (r"\bAIza[0-9A-Za-z_-]{30,}", "کلید Google"),
        (r"\bAQ\.[0-9A-Za-z_-]{30,}", "توکن OAuth گوگل"),
        (r"ghp_[0-9A-Za-z]{30,}", "توکن شخصی گیت‌هاب"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            errors.append(f"{path.name}: {label} داخل فایل workflow نوشته شده!")
    return errors


def _check_required_secrets(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors = []
    if path.name == "post.yml":
        for secret in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if f"secrets.{secret}" not in text:
                errors.append(f"{path.name}: secret {secret} استفاده نشده")
    return errors


def validate_all() -> list[str]:
    if not WORKFLOWS.exists():
        return [f"پوشهٔ {WORKFLOWS} وجود ندارد"]

    errors: list[str] = []
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        return ["هیچ فایل workflow ای پیدا نشد"]

    for path in files:
        errors += _check(path)
        errors += _check_schedule(path)
        errors += _check_no_secrets(path)
        errors += _check_required_secrets(path)
    return errors


def test_workflows_are_valid():
    errors = validate_all()
    assert not errors, "\n".join(errors)


def test_post_workflow_has_concurrency_guard():
    data = _load(WORKFLOWS / "post.yml")
    concurrency = data.get("concurrency") or {}
    assert concurrency.get("cancel-in-progress") is False


def test_post_workflow_commits_memory():
    text = (WORKFLOWS / "post.yml").read_text(encoding="utf-8")
    assert "state/memory.json" in text
    assert "git commit" in text


def test_ci_workflow_runs_pytest():
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in text


def main() -> int:
    errors = validate_all()
    if errors:
        print("❌ مشکل در workflow ها:\n- " + "\n".join(errors))
        return 1
    files = sorted(p.name for p in WORKFLOWS.glob("*.yml"))
    print(f"✅ workflow ها معتبرند: {', '.join(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
