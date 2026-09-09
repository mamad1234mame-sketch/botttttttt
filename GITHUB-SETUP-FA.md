# راهنمای گیت‌هاب — فقط با مرورگر، بدون ترمینال

کل کار حدود ۲۰ دقیقه. هیچ نرم‌افزاری لازم نیست نصب کنی.

---

## مرحلهٔ ۰ — دانلود فایل آماده

فایل `bio-ai-channel.zip` را دانلود کن و در کامپیوترت **Extract / از حالت
فشرده خارج** کن. یک پوشه به اسم `bio-ai-channel` می‌گیری که داخلش اینها هست:

```
bio-ai-channel/
├── .github/          ← پوشهٔ مخفی! (workflow ها اینجا هستند)
├── .env.example      ← مخفی
├── .gitignore        ← مخفی
├── README.md
├── SETUP.md
├── bioai_channel/
├── state/
├── tests/
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

> ⚠️ سه مورد بالا **مخفی** هستند (با نقطه شروع می‌شوند). در ویندوز باید از
> File Explorer → View → تیک **Hidden items** را بزنی تا دیده شوند.
> در مک: `Cmd + Shift + .`

---

## مرحلهٔ ۱ — توکن بات تلگرام

1. در تلگرام برو به [@BotFather](https://t.me/BotFather)
2. اگر بات داری: `/mybots` → باتت → **API Token** → **Revoke current token**
3. اگر نداری: `/newbot` و یک username بساز
4. توکن را کپی کن، جایی نگه دار: `1234567890:AA...`

> 🔒 توکن و کلید قبلی‌ات لو رفته بود. **حتماً** revoke کن.

## مرحلهٔ ۲ — بات را ادمین کانال کن

1. کانال `Bio_with_AI` را باز کن → **Edit** → **Administrators**
2. **Add Admin** → باتت را پیدا کن
3. تیک **Post Messages** را بزن → Save

---

## مرحلهٔ ۳ — کلید Gemini

1. برو به https://aistudio.google.com/apikey
2. **Create API key** → کلید را کپی کن
3. کلیدهای قدیمی را **Delete** کن

---

## مرحلهٔ ۴ — ساخت ریپو در گیت‌هاب

1. برو به https://github.com/new
2. **Repository name**: `bio-ai-channel` (یا هر اسمی)
3. **Private** یا Public — فرقی نمی‌کند (Actions در هر دو رایگان است)
4. تیک **Add a README file** را **نزن**. هیچ چیز اضافه نکن.
5. **Create repository**

---

## مرحلهٔ ۵ — آپلود فایل‌ها

1. در صفحهٔ ریپو، روی **uploading an existing file** کلیک کن
   (یا **Add file** → **Upload files**)
2. حالا **کل محتویات** پوشهٔ `bio-ai-channel` را بکش و بنداز
   (drag & drop). یعنی اینها را:
   - پوشهٔ `.github`
   - پوشهٔ `bioai_channel`
   - پوشهٔ `state`
   - پوشهٔ `tests`
   - فایل‌های `.env.example`، `.gitignore`، `README.md`، `SETUP.md`،
     `pyproject.toml`، `requirements.txt`، `requirements-dev.txt`

   > ❗ خودِ پوشهٔ `bio-ai-channel` را نکش؛ **محتویاتش** را بکش.
   > اگر پوشهٔ اصلی را بکشی، یک لایهٔ اضافی درست می‌شود و Actions کار نمی‌کند.

3. صبر کن تا لیست پر شود. باید **۴۵ فایل** ببینی.
4. **چک کن** این سه تا در لیست باشند:
   - `.github/workflows/post.yml`
   - `.github/workflows/ci.yml`
   - `.github/workflows/keep-alive.yml`

   > اگر `.github` را نمی‌بینی، یعنی فایل‌های مخفی انتخاب نشده‌اند.
   > در آن صورت برو مرحلهٔ ۵-ب.

5. پایین صفحه: **Commit changes**

### مرحلهٔ ۵-ب — اگر `.github` آپلود نشد

فقط ۳ فایل را دستی بساز:

1. **Add file** → **Create new file**
2. در کادر اسم بنویس: `.github/workflows/post.yml`
   (گیت‌هاب خودش پوشه‌ها را می‌سازد)
3. محتوای `post.yml` را از کامپیوترت با Notepad باز کن، کپی کن، آنجا paste کن
4. **Commit changes**
5. همین کار را برای `ci.yml` و `keep-alive.yml` تکرار کن

---

## مرحلهٔ ۶ — Secrets

1. در ریپو برو به **Settings** (تب بالا، سمت راست)
2. منوی چپ: **Secrets and variables** → **Actions**
3. تب **Secrets** → **New repository secret**

این سه تا را **حتماً** اضافه کن:

| Name | Secret |
|---|---|
| `GEMINI_API_KEY` | کلیدی که از AI Studio گرفتی |
| `TELEGRAM_BOT_TOKEN` | توکن بات |
| `TELEGRAM_CHAT_ID` | `@Bio_with_AI` |

و این یکی **توصیه می‌شود**:

| Name | Secret |
|---|---|
| `ADMIN_CHAT_ID` | آیدی عددی خودت — گزارش خطاها برایت می‌آید |

> آیدی عددی‌ات را از [@userinfobot](https://t.me/userinfobot) بگیر.

> ⚠️ اسم‌ها را **دقیقاً** همین‌طور بنویس. حروف بزرگ و زیرخط مهم است.

---

## مرحلهٔ ۷ — فعال کردن Actions

1. تب **Actions** را باز کن
2. اگر پیامی دیدی که می‌گوید workflow ها غیرفعال‌اند، روی
   **I understand my workflows, go ahead and enable them** کلیک کن
3. باید سه workflow ببینی: `post`، `ci`، `keep-alive`

---

## مرحلهٔ ۸ — اولین تست (بدون ارسال به کانال)

1. در تب **Actions**، از لیست چپ **post** را انتخاب کن
2. بالا سمت راست: **Run workflow**
3. در کادر باز شده:
   - Branch: `main`
   - format: خالی بگذار
   - **`dry_run`: تیک بزن** ✅
   - skip_image: تیک نزن
4. **Run workflow**
5. روی اجرای تازه کلیک کن و منتظر بمان (۲ تا ۵ دقیقه)

> ⏳ workflow اول یک تأخیر تصادفی ۰ تا ۲۰ دقیقه‌ای دارد. این عمدی است تا
> الگوی انتشار طبیعی به نظر برسد. برای تست می‌توانی صبر کنی.

6. اگر سبز شد ✅ → برو مرحلهٔ ۹
7. اگر قرمز شد ❌ → روی job کلیک کن و متن خطا را برایم بفرست

---

## مرحلهٔ ۹ — اولین پست واقعی

1. دوباره **Run workflow**
2. این بار **`dry_run` را تیک نزن**
3. **Run workflow**
4. چند دقیقه صبر کن → پست در کانال ظاهر می‌شود 🎉

---

## مرحلهٔ ۱۰ — تنظیم زمان‌بندی خودکار

به‌صورت پیش‌فرض **هر ۳ ساعت** یک پست می‌رود. برای **هر ساعت**:

1. در ریپو، فایل `.github/workflows/post.yml` را باز کن
2. بالا سمت راست، آیکون مداد ✏️ (**Edit this file**)
3. این خط را پیدا کن:
   ```yaml
       - cron: "5 */3 * * *"
   ```
4. تغییرش بده به:
   ```yaml
       - cron: "5 */1 * * *"
   ```
5. **Commit changes** → **Commit directly to the `main` branch** → Commit

> ⏰ **نکتهٔ مهم:** زمان‌بند خودکار گیت‌هاب معمولاً **چند ساعت بعد از اولین
> اجرای دستی** فعال می‌شود. اگر تا فردا اجرای زمان‌بندی‌شده ندیدی، یک بار
> دیگر دستی Run workflow بزن تا زمان‌بند ثبت شود.
>
> **cron گیت‌هاب UTC است.** تهران = UTC+3:30.

---

## چطور بفهمم سالم کار می‌کند

تب **Actions** → اگر اجراها سبز هستند، همه‌چیز درست است.

برای دیدن اینکه چه پستی ساخته شده: روی اجرای سبز کلیک کن → job `post` →
قدم **Publish post** → لاگ را بخوان.

---

## جدول خطاها

| خطا در لاگ | علت | راه‌حل |
|---|---|---|
| `GEMINI_API_KEY تنظیم نشده` | Secret اضافه نشده | مرحلهٔ ۶ را چک کن؛ اسم دقیق |
| `chat not found` | `TELEGRAM_CHAT_ID` غلط | `@Bio_with_AI` یا آیدی عددی `-100...` |
| `CHANNEL_CHAT_ADMIN_REQUIRED` | بات ادمین نیست | مرحلهٔ ۲ |
| `models/... is not found` | مدل روی اکانتت نیست | Settings → Variables → `GEMINI_MODEL` را `gemini-2.5-flash` بگذار |
| `429 RESOURCE_EXHAUSTED` | سهمیهٔ رایگان تمام شده | هر ۳ ساعت نگه دار، هر ساعت نکن |
| تصویر نیامد | مدل تصویر نبود | پست بدون تصویر می‌رود؛ اجرا نمی‌میرد |
| workflow اصلاً اجرا نمی‌شود | `.github/workflows` آپلود نشده | مرحلهٔ ۵-ب |

---

## یک نکتهٔ امنیتی

هیچ secret ای داخل فایل‌ها نیست. خودِ گیت‌هاب هم در هر push با یک اسکنر
چک می‌کند (`ci.yml`). ولی **هرگز** توکن یا کلید را در commit message یا
در فایلی ننویس.
