-- =====================================================================
-- TGSHORTBOT — Migration: User Policy (Accept/Reject terms) feature
-- Run this once in Supabase's SQL Editor. Safe to re-run (every
-- statement is idempotent) — it only ADDS to your existing schema,
-- nothing here drops or rewrites any existing table/column/data.
-- =====================================================================

-- 1. Two new columns on the existing admins table: which policy version
--    this Admin last accepted, and when.
alter table admins
    add column if not exists policy_accepted_version integer not null default 0,
    add column if not exists policy_accepted_at timestamptz;

-- 2. New single-row table holding the Owner-editable policy text itself
--    (same one-row pattern as cpm_settings).
create table if not exists policy_settings (
    id          integer primary key default 1 check (id = 1),
    version     integer not null default 1,
    text        text not null default '',
    updated_at  timestamptz not null default now(),
    updated_by  bigint
);

-- Seed the default row (only inserts if it doesn't already exist).
insert into policy_settings (id, version, text) values (
    1,
    1,
    E'১. ফেক/বট ট্রাফিক ব্যবহার করলে সাথে সাথে অ্যাকাউন্ট ব্যান করা হবে।\n\n'
    '২. আপনার ট্রাফিক সোর্স অবশ্যই ১০০% নিজের ও অরিজিনাল হতে হবে। কোনো পেমেন্ট '
    'দেওয়ার আগে অ্যাডমিন নিজে যাচাই-বাছাই করে তবেই পেমেন্ট করবে।\n\n'
    '৩. অন্য কারো প্রাইভেট/কপিরাইটেড মুভি বা এমন কোনো কনটেন্ট যা পাবলিকলি শেয়ার '
    'করা বৈধ নয়, এবং যেকোনো ধরনের মড (Mod) APK শেয়ার করা সম্পূর্ণভাবে ব্যবহারকারীর '
    'নিজস্ব দায়িত্ব — এর জন্য বটের মালিক বা কোম্পানি কোনোভাবেই দায়ী থাকবে না।\n\n'
    '৪. Adult/প্রাপ্তবয়স্ক কনটেন্ট এই প্ল্যাটফর্মে সম্পূর্ণভাবে নিষিদ্ধ।\n\n'
    'চালিয়ে যেতে হলে এই শর্তাবলীতে সম্মতি জানাতে হবে।'
)
on conflict (id) do nothing;

-- Same reasoning as every other table: the backend connects with the
-- service_role key, which bypasses RLS anyway, so RLS stays off here too.
alter table policy_settings disable row level security;
