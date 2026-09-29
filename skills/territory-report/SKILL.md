---
name: territory-report
description: "Build a sales rep's territory report as an HTML page with a revenue-by-country chart, top customers, trends and next-quarter focus. Use when asked for a territory report, 'my numbers', a pipeline review pack, or revenue by country for a rep."
---

# Territory report

The territory is the set of customers whose SupportRepId equals the rep's employee id
(the signed-in rep by default; another rep only if asked and named).

## 1. Numbers (chinook-analyst), all in one request
- Revenue and invoice count by country for the territory, for the latest full year (2025),
  ordered by revenue.
- The same by country for the prior year (2024), so growth can be computed.
- Top 5 customers by lifetime revenue: name, company, country, revenue, last invoice date.
- Top 3 genres by revenue in the territory for 2025.
- Territory totals for 2025 and 2024.

## 2. Chart
Call render_bar_chart with the 2025 revenue by country: filename
`territory-<rep-firstname>-2025`, title "Revenue by country, 2025", labels = countries,
values = revenue. Use the returned file name in the report.

## 3. Report
Save with write_html_report as `/output/territory-<rep-firstname>-<yyyymmdd>.html`. Title:
"Territory report: <Rep full name>". Subtitle: "<n> customers in <k> countries, 2025 vs 2024".
Body, in this order:
- "Summary" - 3 sentences: total 2025 revenue, growth vs 2024 (compute % from the two
  totals, 1 decimal), and the biggest mover.
- "Revenue by country" - the chart image, then a table `| Country | 2025 | 2024 | Change |`.
- "Top customers" - a table `| Customer | Company | Country | Lifetime revenue | Last order |`.
- "What's selling" - the top 3 genres with their revenue.
- "Focus for next quarter" - exactly 3 recommendations, each tied to a number above
  (a declining country to revisit, a top customer to upsell, a genre to push).

## 4. Hand it back
Tell the rep the file path, the 2025 total and growth, and the 3 recommendations in one
line each. Don't email it unless asked.
