---
name: weekly-newsletter
description: "Write the weekly customer newsletter as a one-page HTML file: top sellers for a genre or the whole store, plus a short, sourced intro. Use when asked for the newsletter, a genre spotlight, or 'what's selling this week'."
---

# Weekly newsletter

## 0. Delegate it if the newsletter-writer is available
If start_async_task lists `newsletter-writer`, start it with the focus genre and period
(section 1), tell the rep the task id and that the file will land in /output/, and stop.
The rep can keep working meanwhile. Check it with check_async_task only when the rep asks;
then report the file path and the headline facts it returned. Otherwise, do sections 1-5
yourself.

## 1. Scope
- Focus genre: whatever the rep (or Nancy's email) asked for. No focus given -> whole store.
- Period: the most recent full year in the data (2025) unless told otherwise. Say which
  period you used.

## 2. Get the numbers (chinook-analyst)
Ask for, in one request:
- the top 8 tracks by units sold in the focus genre (track, artist, album, units, revenue);
- the top 3 artists by revenue in the focus genre;
- the focus genre's revenue and its share of store revenue for the period.
Every figure in the newsletter comes from this answer. Keep track names exactly as given.

## 3. Get the story (genre-researcher)
Ask for 3 bullets of outside context on the focus genre and one marketing angle. If the
researcher says its notes are from the offline corpus, keep the intro general and don't
cite a source.

## 4. Write it
Save with write_html_report as `/output/newsletter-<genre>-<yyyymmdd>.html`. Title:
"Chinook Weekly: <Genre> spotlight". Body, in this order:
- "This week" - a 3-4 sentence intro that blends the outside context with our own numbers
  (share of revenue, top artist). One page total; no filler.
- "Top sellers" - a table `| # | Track | Artist | Album | Units |` with the 8 tracks.
- "Artists to know" - one line each for the 3 artists.
- "Deal of the week" - one bundle idea from the analyst's numbers (e.g. the top album at 10% off).
  Don't invent prices; use catalog unit prices.
- A one-line footer: "Numbers: Chinook sales, <period>."

## 5. Hand it back
Tell the rep the file path and the three headline facts. Only send it by email if asked;
sending pauses for review.
