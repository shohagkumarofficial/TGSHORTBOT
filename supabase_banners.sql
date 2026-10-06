-- Run this ONCE in Supabase → SQL Editor to enable the viewer-page banners.
-- (Until you run it the app keeps working; banners just stay off and custom
-- ads can't be saved.)

create table if not exists banner_settings (
  id integer primary key,
  header_source text not null default 'off',
  header_mode text not null default 'rotate',
  header_pinned_ad_id text,
  header_adsterra_code text not null default '',
  footer_source text not null default 'off',
  footer_mode text not null default 'rotate',
  footer_pinned_ad_id text,
  footer_adsterra_code text not null default '',
  updated_at text,
  updated_by bigint
);

create table if not exists custom_ads (
  ad_id text primary key,
  title text not null default '',
  image_url text not null,
  link_url text not null,
  slot text not null default 'header',
  active boolean not null default true,
  view_count integer not null default 0,
  click_count integer not null default 0,
  created_at text
);

-- The app uses the service key, so Row Level Security can stay as it is for
-- your other tables; if you enabled RLS on them, enable it here too:
-- alter table banner_settings enable row level security;
-- alter table custom_ads enable row level security;
