---
name: rfq-quote
description: "Turn a customer's request for quote (RFQ) into a priced, one-page HTML quote and send it. Use when a customer asks for a quote, pricing, a licensed playlist, a bulk order, or an RFQ arrives in the inbox."
---

# RFQ to quote

Keep a todo list; this is a 5-step job.

## 1. Understand the request
- If the RFQ is in the inbox, ask **inbox-clerk** to read it and report: sender email,
  company, what they want (genres, number of tracks, use), and any deadline.
- If anything essential is missing (which genres, how many tracks), ask the rep before
  pricing. Don't guess.

## 2. Identify the customer
- Ask **chinook-analyst** to look up the customer by email: name, company, country,
  support rep, number of invoices and lifetime spend. An RFQ from a customer outside the
  signed-in rep's territory is still quoted; mention the owning rep in the summary.

## 3. Price it
- Ask **chinook-analyst** for the requested number of tracks per genre from the catalog
  with track id, track name, artist and unit price, ordered by popularity (times purchased),
  plus the count of tracks available in each genre.
- If a genre has fewer tracks than requested, fill the remainder from the closest genre
  (Bossa Nova -> Latin, Jazz -> Easy Listening, Metal -> Heavy Metal) and say so in the quote.
- List price = sum of unit prices. Volume discount, applied to the list price:

  | Tracks in the quote | Discount |
  |---|---|
  | 1-24 | 0% |
  | 25-49 | 10% |
  | 50-99 | 15% |
  | 100+ | 20% (requires Nancy's sign-off; say so) |

- Returning customers (at least one prior invoice) get an extra 5 percentage points.
- Quotes are valid for 30 days. Never discount more than 25% in total.

## 4. Build the quote
Save it with write_html_report as `/output/quote-<company-or-lastname>-<yyyymmdd>.html`.
Title: "Quote for <company or customer name>". Body, in this order:
- A two-sentence summary (what, for whom, valid until).
- A "Tracks" table: `| # | Track | Artist | Genre | Price |` with every track.
- A "Pricing" table: list price, discount % and amount, total. Show the math.
- "Terms": license for the stated use, payment on invoice, valid for 30 days.
- "Your contact": the signed-in rep's name and email.

## 5. Send it
- Call send_email to the customer with subject "Your Chinook quote: <n> tracks", a short
  friendly body that repeats the total and validity, and the quote file path in the body.
  A person reviews every outgoing email; that pause is the review, so just make the call.
- Ask **inbox-clerk** to mark the RFQ processed with the quote file name.
- Reply to the rep with: customer, track count, total, discount applied, the file path,
  and whether the email was sent, edited or rejected.
