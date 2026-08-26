# TGSHORT Tasks

Telegram Mini App — ছোট টাস্ক করে কয়েন অর্জন, Django দিয়ে বানানো, ডাটাবেজ ছাড়া
(সব ডাটা in-memory, admin backup/restore দিয়ে সুরক্ষিত)।

## ফিচার
- Telegram Mini App (webview), `initData` HMAC verify করে authenticate করে
- টাস্ক টাইপ: manual (লিংক/ভিডিও), channel/group join (বট API দিয়ে সত্যিকারের যাচাই), ad_watch (Monetag / GigaPub)
- কয়েন সিস্টেম + Withdraw request (admin manual approve করে)
- Admin panel: শুধু `OWNER_TELEGRAM_ID` দেখতে পারে — task তৈরি/বন্ধ/ডিলিট, withdrawal approve/reject, ডাটা backup (JSON ডাউনলোড) ও restore (JSON আপলোড)

## লোকাল রান
```bash
pip install -r requirements.txt
cp .env.example .env   # তারপর মান বসান, এবং export করুন বা python-dotenv ব্যবহার করুন
python manage.py runserver
```
> নোট: কোনো migration লাগবে না — এই প্রজেক্টে ডাটাবেজ নেই।

## Telegram বট সেটআপ
1. `@BotFather` কে `/newbot` দিয়ে বট বানান, `BOT_TOKEN` কপি করুন।
2. `@userinfobot` কে মেসেজ দিয়ে নিজের Telegram user id বের করুন — এটাই `OWNER_TELEGRAM_ID`।
3. `@BotFather` → `/mybots` → আপনার বট → **Bot Settings → Menu Button** → Render-এ deploy করা URL বসান। এতে ইউজাররা bot চ্যাটের মেনু বাটন থেকে Mini App খুলতে পারবে।
4. Channel-join টাস্ক ঠিকভাবে যাচাই করতে হলে **বটকে সংশ্লিষ্ট চ্যানেল/গ্রুপে admin বানাতে হবে** — নাহলে `getChatMember` কল সঠিক তথ্য দেবে না।

## Render এ Deploy
1. এই কোড GitHub repo তে পুশ করুন।
2. Render এ **New → Web Service** → repo সিলেক্ট করুন (`render.yaml` স্বয়ংক্রিয়ভাবে detect হবে)।
3. এনভায়রনমেন্ট ভ্যারিয়েবল বসান (দেখুন `.env.example`):
   - `BOT_TOKEN`
   - `OWNER_TELEGRAM_ID`
   - `DJANGO_SECRET_KEY` (Render auto-generate করতে পারে)
   - `ALLOWED_HOSTS` → আপনার `.onrender.com` ডোমেইন
   - `MONETAG_ZONE_ID` (ডিফল্ট: 11646009)
   - `GIGAPUB_PROJECT_ID` (ডিফল্ট: 7860)
   - `TELEGRAM_WEBHOOK_SECRET` (Render auto-generate করবে — মান পরে দরকার হবে)
4. Deploy হয়ে গেলে URL টা বট মেনু বাটনে বসান (উপরে দেখুন)।

## /start কমান্ড চালু করা (একবারই করতে হবে)
বট চ্যাটে `/start` দিলে রিপ্লাই পেতে হলে Telegram কে জানাতে হবে কোথায় আপডেট পাঠাতে হবে
(webhook)। Deploy হওয়ার পর, নিজের কম্পিউটার থেকে একবার এই কমান্ডটা চালান
(`<BOT_TOKEN>`, `<your-app>.onrender.com` ও `<TELEGRAM_WEBHOOK_SECRET>` — নিজের মান বসান,
শেষেরটা Render dashboard → Environment ট্যাব থেকে কপি করা যাবে):

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<your-app>.onrender.com/telegram-webhook/<TELEGRAM_WEBHOOK_SECRET>/"
```

সফল হলে `{"ok":true,"result":true,...}` রিটার্ন করবে। এরপর থেকে `/start` দিলেই বট
স্বাগত বার্তা ও "🚀 অ্যাপ খুলুন" বাটনসহ রিপ্লাই করবে।

## ডেইলি ফিচার
- **ডেইলি চেক-ইন**: ড্যাশবোর্ড ট্যাবে প্রতিদিন একবার চেক-ইন করে কয়েন নেওয়া যায়; পরপর
  চেক-ইন করলে ৭ দিনের সাইকেলে রিওয়ার্ড বাড়ে (১০ → ১৫ → ২০ → ২৫ → ৩০ → ৪০ → ৬০), একদিন
  বাদ পড়লে স্ট্রিক আবার ১ থেকে শুরু হয়।
- **ডেইলি টাস্ক**: অ্যাডমিন প্যানেলে টাস্ক তৈরির ফর্মে "ডেইলি টাস্ক" চেকবক্স টিক দিলে
  সেই টাস্ক প্রতি ২৪ ঘন্টায় (বাংলাদেশ সময় অনুযায়ী) আবার claim করা যাবে। প্রথমবার
  অ্যাপ চালু হলে এমনই একটা ডিফল্ট ডেইলি অ্যাড-ওয়াচ টাস্ক এমনিতেই তৈরি হয়ে থাকে।

## ⚠️ ডাটা পার্সিস্টেন্স সম্পর্কে জরুরি নোট
এই প্রজেক্টে **কোনো ডাটাবেজ নেই** — সব ইউজার/টাস্ক/উইথড্র ডাটা প্রসেসের RAM-এ থাকে।
Render এ প্রতিবার নতুন deploy বা instance রিস্টার্ট হলে **সব ডাটা মুছে যাবে**।

এজন্য Admin প্যানেলে দুটো বাটন আছে:
- **📥 ব্যাকআপ ডাউনলোড** — এখনকার সব ডাটার একটা JSON ফাইল ডাউনলোড হবে। এটা নিয়মিত (যেমন দিনে একবার) ডাউনলোড করে রাখুন।
- **📤 রিস্টোর আপলোড** — Render রিস্টার্ট হওয়ার পর সবশেষ ব্যাকআপ ফাইল আপলোড করলে আগের সব ডাটা ফিরে আসবে।

ভবিষ্যতে সত্যিকারের persistence চাইলে PostgreSQL/Redis যোগ করে `core/store.py` এর ফাংশনগুলো (get_user, create_task, ইত্যাদি) ওই DB দিয়ে রিপ্লেস করলেই বাকি কোড অপরিবর্তিত থাকবে।

## প্রজেক্ট স্ট্রাকচার
```
tgshort_tasks/
├── manage.py
├── requirements.txt
├── render.yaml
├── Procfile
├── .env.example
├── tgshort_tasks/         # Django settings, urls, wsgi
├── core/                  # Mini App UI + user-facing API
│   ├── store.py           # in-memory data layer
│   ├── telegram_auth.py   # initData HMAC verify
│   ├── telegram_bot.py    # channel membership check (Bot API)
│   ├── views.py / urls.py
│   ├── templates/core/index.html
│   └── static/core/{style.css, app.js}
└── adminpanel/            # owner-only task/withdrawal/backup API
    └── views.py / urls.py
```
