---
name: refund-policy
description: "Chinook's refund policy for digital purchases and the exact steps to handle a customer's refund request, from the inbox or from the rep. Use whenever a refund, money back, a duplicate or accidental purchase, or a track that won't play comes up."
---

# Refund policy (digital music and video)

## What qualifies
- A track or episode that won't play or is defective (any age).
- A duplicate purchase of the same track.
- An accidental purchase reported within 14 days of the invoice date.

## What does not qualify
- Change of mind, "don't listen to it anymore", or price found lower elsewhere.
- Amounts above the invoice total, or a second refund on an invoice already refunded in full.

A person approves, edits or rejects every refund before it is issued. Never promise a
customer an outcome.

## Steps
1. **Get the facts.** If the request came by email, ask **inbox-clerk** to read it and
   report the sender, invoice number, what went wrong and the amount requested. If the
   rep asked directly, use what they gave you; ask for the invoice number if missing.
2. **Verify the invoice** with **chinook-analyst**: the invoice exists, belongs to the
   customer with that email, its date, total, line items, and the amount already refunded,
   taken from the ledger lookup. If it isn't theirs or doesn't exist, stop: reply that you
   can't find it and ask for the invoice number on their receipt. Don't stop over wording:
   customers say "track", "song", "episode" or "video" loosely. If the invoice is theirs
   and the reason qualifies, continue.
3. **Apply the policy.** If the reason doesn't qualify, do NOT call issue_refund. Calculate
   the remaining refundable amount as the invoice total minus the amount already refunded.
   If nothing remains, politely decline without calling issue_refund. If the requested amount
   exceeds what remains, cap it to the remaining amount or politely decline.
4. **Issue it.** Call issue_refund(invoice_id, amount, reason) with the amount capped at the
   invoice total (partial when only some items are affected) and the reason in one
   sentence. The call pauses for a person; that pause is the approval.
5. **Close the loop.** If the refund was issued, email the customer (send_email) with the
   refund number, amount and "5-7 business days to appear on your statement". If the
   reviewer rejected it, say so politely and offer the rep's contact. Ask **inbox-clerk** to
   mark the message processed with the outcome.
6. **Report to the rep** in two lines: what was decided and why.
