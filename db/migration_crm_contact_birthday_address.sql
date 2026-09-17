-- Adds Birthday and Address to CRM contacts.
-- These mirror buy_interests.customer_birthday / customer_address so contacts
-- created from an interest can carry the values over.
-- Safe to re-run.

alter table if exists public.crm_contacts
  add column if not exists birthday date,
  add column if not exists address text not null default '';
