# راه‌اندازی روی GitHub Actions — قدم به قدم

کل فرایند حدود ۱۵ دقیقه طول می‌کشد. **هیچ سروری لازم نیست.**

---

## ۱) توکن بات تلگرام

1. در تلگرام به [@BotFather](https://t.me/BotFather) برو.
2. اگر بات داری: `/mybots` → باتت را انتخاب کن → **API Token** → **Revoke current token**.
   > ⚠️ اگر توکن قبلی را جایی لو داده بودی، این مرحله اجباری است.
3. اگر بات نداری: `/newbot` و یک نام و username بساز.
4. توکن را نگه دار: `1234567890:AA...`

## ۲) بات را ادمین کانال کن

1. بات را به کانال اضافه کن.
2. در تنظیمات کانال → **Administrators** → بات را ادمین کن.
3. اجازه‌های لازم: **Post Messages** (و اگر تصویر می‌خواهی، همین کافی است).

## ۳) `TELEGRAM_CHAT_ID` را پیدا کن

برای کانال عمومی، همان username کافی است **با @**:

```
TELEGRAM_CHAT_ID=@Bio_with_AI
```

برای کانال خصوصی یا وقتی می‌خواهی مطمئن باشی، آیدی عددی را بگیر:

```bash
# بات را در کانال ادمین کردی، سپس:
curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
# یا اگر کانال خصوصی است:
curl "https://api.telegram.org/bot<TOKEN>/getChat?chat_id=@Bio_with_AI"
```

آیدی عددی کانال با `-100` شروع می‌شود، مثلاً `-1001234567890`.

## ۴) کلید Gemini API

1. به [Google AI Studio](https://aistudio.google.com/apikey) برو.
2. **Create API key** → کلید را کپی کن.
3. کلیدهای قدیمی و لو رفته را حذف کن.

> 🔒 **اگر کلید یا توکن قبلی را در جایی عمومی گذاشته بودی، همین الان
> باطلش کن.** پاک کردن فایل از ریپو کافی نیست؛ در تاریخچهٔ git می‌ماند.

## ۵) ریپو را بساز و push کن

```bash
cd bio-ai-channel
git init -b main
git add .
git commit -m "feat: self-hosted AI x biology Telegram publisher"
git remote add origin git@github.com:<username>/bio-ai-channel.git
git push -u origin main
```

## ۶) Secrets را در گیت‌هاب تنظیم کن

به `Settings → Secrets and variables → Actions` برو:

### تب **Secrets** (اجباری)

| نام | مقدار |
|---|---|
| `GEMINI_API_KEY` | کلید Gemini |
| `TELEGRAM_BOT_TOKEN` | توکن بات |
| `TELEGRAM_CHAT_ID` | `@Bio_with_AI` یا `-100...` |

### تب **Secrets** (اختیاری ولی توصیه‌شده)

| نام | مقدار |
|---|---|
| `ADMIN_CHAT_ID` | آیدی عددی خودت؛ گزارش شکست‌ها برایت می‌آید |
| `NCBI_API_KEY` | کلید رایگان NCBI؛ سقف PubMed را ۳ → ۱۰ درخواست/ثانیه می‌برد |

### تب **Variables** (اختیاری)

| نام | پیش‌فرض | توضیح |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.7-flash` | مدل نوشتن متن |
| `IMAGE_MODEL` | `gemini-3.1-flash-image` | مدل تولید تصویر |
| `CHANNEL_SIGNATURE` | `@Bio_with_AI` | امضای پایان پست |

## ۷) Actions را فعال کن

1. تب **Actions** → اگر بنری دیدی، **I understand my workflows, go ahead and enable them**.
2. workflow `post` را باز کن → **Run workflow** → تیک `dry_run` را بزن → اجرا کن.
3. لاگ را نگاه کن؛ باید ببینی پست نوشته شده ولی ارسال نشده.
4. حالا دوباره **Run workflow** بدون `dry_run` → اولین پست واقعی در کانال می‌رود.

> ⏰ **نکتهٔ مهم:** زمان‌بند خودکار گیت‌هاب معمولاً چند ساعت بعد از اولین
> اجرای دستی فعال می‌شود. اگر بعد از چند ساعت اجرای زمان‌بندی‌شده ندیدی،
> یک بار دیگر دستی اجرا کن تا زمان‌بند ثبت شود.

---

## تنظیم دفعات انتشار

فایل `.github/workflows/post.yml`:

```yaml
on:
  schedule:
    - cron: "5 */3 * * *"    # پیش‌فرض: هر ۳ ساعت
```

| می‌خواهی | cron |
|---|---|
| هر ۳ ساعت (پیش‌فرض) | `5 */3 * * *` |
| **هر ساعت** | `5 */1 * * *` |
| هر ۶ ساعت | `5 */6 * * *` |
| روزی دو بار، ۹ و ۲۱ به وقت UTC | `0 9,21 * * *` |
| روزی یک بار، ۶:۳۰ صبح تهران (۳:۰۰ UTC) | `30 3 * * *` |

**cron گیت‌هاب UTC است.** تهران = UTC+3:30.

حداقل بازهٔ پشتیبانی‌شده ۵ دقیقه است، ولی اجرای زمان‌بندی‌شدهٔ گیت‌هاب
**تضمینی نیست** و ممکن است ۵ تا ۳۰ دقیقه تأخیر داشته باشد. برای کانال علمی
این کاملاً قابل قبول است.

---

## چطور مطمئن شوم سالم کار می‌کند

```bash
# لوکال
set -a; source .env; set +a
python -m bioai_channel.main --selftest
```

خروجی سالم:

```
✅ بات تلگرام: @your_bot (id=1234567890)
✅ چت مقصد: Bio with AI (نوع: channel)
✅ بات ادمین کانال است: True
✅ حافظه: state/memory.json — 0 پست ثبت‌شده
✅ مدل متن: gemini-3.7-flash / مدل تصویر: gemini-3.1-flash-image
— آمادهٔ اجرا —
```

در گیت‌هاب: تب **Actions** → فیلتر `Event: schedule`. اگر اجراها سبز بودند،
همه‌چیز درست است.

---

## عیب‌یابی

| علامت | علت | راه‌حل |
|---|---|---|
| `chat not found` | `TELEGRAM_CHAT_ID` غلط | با `@username` یا `-100...` درستش کن |
| `CHANNEL_CHAT_ADMIN_REQUIRED` | بات ادمین نیست | بات را ادمین کن + اجازهٔ Post Messages |
| `bot was kicked` | بات از کانال بیرون شده | دوباره اضافه و ادمین کن |
| `models/... is not found` | مدل روی اکانتت نیست | `GEMINI_MODEL` را در Variables عوض کن |
| `429 RESOURCE_EXHAUSTED` | سهمیه تمام شده | فاصلهٔ انتشار را بیشتر کن (هر ۳ ساعت کافی است) |
| تصویر نیامد | مدل تصویر در دسترس نبود | `IMAGE_MODEL` را عوض کن؛ پست بدون تصویر می‌رود و اجرا نمی‌میرد |
| اجرای زمان‌بندی‌شده نمی‌آید | workflow روی برنچ پیش‌فرض نیست / ریپو ۶۰ روز بی‌فعال بوده | یک commit بزن و دستی اجرا کن |

---

## امنیت

- هیچ secret ای داخل کد نیست. CI در هر push با یک اسکنر ساده چک می‌کند.
- `.env` در `.gitignore` است.
- اگر secret ای لو رفت: **اول باطلش کن**، بعد تاریخچهٔ git را پاک کن
  (`git filter-repo`) یا ریپوی تازه بساز.
