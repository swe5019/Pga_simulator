# SlateSims lead endpoint

A Cloudflare Worker that collects beta signups, replacing Formspree. Formspree's
free tier stops accepting submissions after 50 a month and drops the rest
without telling you; this has no practical cap on Cloudflare's free plan, and
because the data is yours it can be counted, which is what makes the lead total
on the admin page possible.

The D1 database **already exists** and the schema is **already applied**:

    name  slatesims-leads
    id    ee9dac61-52e6-446f-901c-07cf4af275a4

## Deploy (two commands)

    cd worker
    npx wrangler login        # once, opens a browser
    npx wrangler secret put ADMIN_KEY     # paste any long random string
    npx wrangler deploy

The last command prints a URL like

    https://slatesims-leads.<your-subdomain>.workers.dev

Send me that URL and I will point the site at it. Until then the site keeps
using Formspree, so nothing breaks while this sits undeployed.

## Routes

| Route | Purpose |
|---|---|
| `POST /lead` | `{email, source}` from the site. CORS limited to slatesims.com. |
| `GET /count?key=…` | Totals, by source, last 7 days, 25 most recent. Admin page. |
| `GET /export?key=…` | Every lead as CSV. |

`ADMIN_KEY` guards the two read routes. It is not in this repo and must not go
into `admin.html`, which is a public file — the admin page prompts for it and
keeps it in that browser only.

## Behaviour worth knowing

- **One row per address.** A repeat signup bumps `hits` and `last_seen` instead
  of adding a duplicate, so the total is a subscriber count, not a submission
  count. If the same person arrives from a different part of the site the
  sources are joined, e.g. `NFL+PGA`.
- **Honeypot.** A hidden `company` field; anything that fills it gets a 200 and
  is discarded, so the bot thinks it succeeded and does not retry.
- **Rate limit.** 20 writes per IP per hour.
- **Email validation is loose on purpose.** Over-strict rules reject more real
  addresses than the junk they stop.

## Cost

Free tier: 100,000 requests/day and 5 GB of D1. A signup list will not approach
either.
