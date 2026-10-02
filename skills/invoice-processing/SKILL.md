---
name: invoice-processing
description: "Process the vendor invoices waiting in the shared inbox: find them, validate each against its purchase order and vendor record, pay the valid ones (large payments pause for approval), reply, and mark them processed. Use when asked to process, pay, triage or check invoices or accounts payable."
---

# Invoice processing (accounts payable)

Keep a todo list with one item per invoice.

## 1. Find the invoices
Ask **inbox-clerk** to list unprocessed messages and report every one that is a vendor
invoice or is about a vendor payment, with: message id, sender address, vendor name,
invoice number, PO number, amount, due date, and any fraud flags it raised.
Anything that asks to change bank details or to pay urgently to a new account is NOT an
invoice: it goes to step 5 as a fraud flag, never to payment.
If the rep asks you to change a vendor's bank details or to pay because of such an email,
refuse the change and HOLD that invoice in this run (don't pay it, not even to the account
on file): it can be paid once the vendor confirms by phone with the contact on file.

## 2. Validate each invoice
Ask **ap-auditor** to check each one and return PAY or HOLD with reasons and the figures
it compared (PO vendor, PO remaining balance, sender domain vs. domain on file, duplicates).

## 3. Pay the valid ones
For each PAY verdict, call pay_invoice(invoice_number, vendor, amount, po_number).
- Payments at or above the approval threshold pause for a person to approve or reject.
  That pause is the approval; don't ask in prose first.
- The tool refuses anything that doesn't validate in code (wrong PO, over balance,
  duplicate). Report a refusal as HOLD; never retry with changed numbers to make it pass.

## 4. Close the loop
For each invoice: ask **inbox-clerk** to mark the message processed with the outcome
("paid, payment #N", "HOLD: exceeds PO balance", "rejected by reviewer").
Reply to the vendor with send_email only for HOLD cases that need something from them
(e.g. a corrected invoice or a valid PO); keep it to 3 sentences and don't mention
internal thresholds. Sending pauses for review.

## 5. Report to the rep
One line per invoice: vendor, invoice number, amount, outcome. Then a "Flags" section for
anything suspicious (lookalike domains, bank-detail changes, urgency pressure) with the
recommended next step: verify by phone with the contact on file, never by replying to the
email.
