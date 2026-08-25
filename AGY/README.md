# 🚀 TGSHORT Tasks — Telegram Micro-Tasks & Coin Reward Bot

**TGSHORT Tasks** হলো একটি পাইথন-ভিত্তিক টেলিগ্রাম বট এবং মাইক্রো-সার্ভিস প্ল্যাটফর্ম, যেখানে ইউজাররা বিভিন্ন শর্ট টাস্ক (টেলিগ্রাম চ্যানেল জয়েন, শর্টলিংক ভিজিট, ডেইলি বোনাস ক্লেইম, রেফারেল ইত্যাদি) সম্পন্ন করে কয়েন রিওয়ার্ড অর্জন করতে পারে।

প্রজেক্টটি **Render** প্ল্যাটফর্মে Free Web Service হিসেবে ২৪/৭ চালু রাখার জন্য অপ্টিমাইজড (FastAPI Health Check + Webhook/Polling সাপোর্ট)।

---

## 🌟 প্রধান ফিচারসমূহ (Key Features)

1. **🎯 মাইক্রো-টাস্ক সিস্টেম (Micro-Tasks)**:
   - **📢 চ্যানেল জয়েন টাস্ক:** টেলিগ্রাম চ্যানেল/গ্রুপ মেম্বারশিপ অটোমেটিক ভেরিফাই করে কয়েন প্রদান।
   - **🔗 শর্টলিংক / সাইট ভিজিট:** ভিজিট শেষে ভেরিফিকেশন কোড সাবমিট করে কয়েন ক্লেইম।
   - **📝 কাস্টম টাস্ক:** অ্যাডমিনের দেওয়া যেকোনো সার্ভে বা লিংক টাস্ক।
2. **🎁 ডেইলি বোনাস (Daily Bonus)**:
   - ২৪ ঘণ্টায় একবার লগইন করে ফ্রি কয়েন ক্লেইম করার সুযোগ।
3. **👥 রেফারেল প্রোগ্রাম (Refer & Earn)**:
   - প্রতিটি ইউজারের ইউনিক ইনভাইট লিংক (`https://t.me/Bot?start=ref_USERID`)।
   - রেফারার এবং নতুন ইউজার উভয়ের জন্যই ইনস্ট্যান্ট ওয়েলকাম ও রেফারেল বোনাস।
4. **👤 প্রোফাইল ও ব্যালেন্স (Profile & Balance)**:
   - বর্তমান ব্যালেন্স, সর্বমোট আয়, সম্পন্ন করা টাস্কের পরিসংখ্যান।
5. **🏆 লিডারবোর্ড (Leaderboard)**:
   - সর্বোচ্চ পয়েন্ট অর্জনকারীদের রিয়েল-টাইম শীর্ষ তালিকা।
6. **⚙️ অ্যাডমিন প্যানেল (Admin Dashboard)**:
   - বট থেকেই সরাসরি নতুন টাস্ক যোগ করা (Interactive Wizard)।
   - টাস্ক তালিকা দেখা এবং ডিলিট করা।
   - সমস্ত ইউজারকে এক ক্লিকে ব্রডকাস্ট মেসেজ পাঠানো।
   - প্ল্যাটফর্মের সার্বিক পরিসংখ্যান দেখা।
7. **💾 মডুলার স্টোরেজ (No DB Needed Initially)**:
   - কোনো এক্সটার্নাল ডাটাবেজ ছাড়াও স্বয়ংক্রিয় ফাইল-ব্যাকড `data.json` স্টোরেজ।
   - Clean Architecture অনুযায়ী ডিজাইন করা, ফলে ভবিষ্যতে MongoDB/PostgreSQL যুক্ত করা অত্যন্ত সহজ।

---

## 📁 প্রজেক্ট স্ট্রাকচার (Project Structure)

```
TGSHORT-Tasks/
├── app/
│   ├── bot/
│   │   ├── handlers/        # start, tasks, profile, admin handlers
│   │   ├── keyboards/       # inline & reply keyboards
│   │   ├── middlewares/     # auth & session middleware
│   │   └── setup.py         # bot & dispatcher initialization
│   ├── services/
│   │   ├── task_service.py  # টাস্ক ও রিওয়ার্ড ম্যানেজমেন্ট লজিক
│   │   └── user_service.py  # ইউজার, ব্যালেন্স, রেফারেল লজিক
│   ├── storage/
│   │   ├── base.py          # Storage Abstract Interface
│   │   └── json_storage.py  # JSON file-backed async storage
│   ├── config.py            # Environment configuration
│   └── main.py              # FastAPI server (Render Entry Point)
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
├── Procfile                 # Render Web Service start command
├── run_local.py             # Local polling script for testing
└── README.md
```

---

## 🛠️ লোকাল সেটআপ ও টেস্টিং (Local Setup)

### ১. ডিপেন্ডেন্সি ইনস্টল করুন:
```bash
pip install -r requirements.txt
```

### ২. কনফিগারেশন সেট করুন:
`.env.example` ফাইলটিকে রিনেম করে `.env` করুন এবং আপনার টেলিগ্রাম বটের টোকেন দিন:
```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
ADMIN_IDS=YOUR_TELEGRAM_USER_ID
DAILY_BONUS_COINS=50
REFERRAL_BONUS_COINS=100
REFEREE_BONUS_COINS=25
```

### ৩. লোকাল পোলিং মোডে বট চালু করুন:
```bash
python run_local.py
```
অথবা FastAPI সার্ভারসহ লোকালি টেস্ট করতে:
```bash
uvicorn app.main:app --reload --port 8000
```

---

## 🌐 Render-এ ফ্রি ডেপ্লয় করার নিয়ম (Deploy to Render)

1. আপনার কোড **GitHub** রিপোজিটরিতে পুশ করুন।
2. **[Render.com](https://render.com)** এ লগইন করে **New +** -> **Web Service** সিলেক্ট করুন।
3. আপনার GitHub রিপোজিটরিটি কানেক্ট করুন।
4. সেটিংস কনফিগার করুন:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables** সেকশনে নিচের ভ্যালুগুলো যোগ করুন:
   - `BOT_TOKEN`: আপনার বটের টোকেন।
   - `ADMIN_IDS`: আপনার টেলিগ্রাম আইডি।
   - `WEBHOOK_URL`: রেন্ডার থেকে প্রাপ্ত URL (যেমন: `https://tgshort-tasks.onrender.com`)
   - `WEBHOOK_SECRET`: একটি সিক্রেট কি (যেমন: `tgshort_super_secret_123`)
6. **Create Web Service** এ ক্লিক করুন। রেন্ডার স্বয়ংক্রিয়ভাবে বিল্ড করে Webhook একটিভ করে দেবে!
