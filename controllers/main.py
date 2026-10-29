# -*- coding: utf-8 -*-
import re

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
       "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


class VoiceAssistantController(http.Controller):
    """All queries run with the logged-in user's rights (no sudo),
    so Odoo access rules and record rules are respected."""

    @http.route("/voice_assistant/process", type="json", auth="user")
    def process(self, text="", confirmed=False, pending=None):
        try:
            if confirmed and pending:
                return self._create_draft_invoice(pending["partner_id"], pending.get("amount"))
            return self._route((text or "").lower().strip())
        except AccessError:
            return {"message": "Sorry, you don't have access rights for that."}
        except UserError as e:
            return {"message": str(e)}

    # ------------------------------------------------------------ router
    def _route(self, text):
        t = re.sub(r"[?.!,]+", " ", text).strip()
        t = re.sub(r"\s+", " ", t)
        if "overdue" in t:
            return self._overdue(t)
        if re.search(r"\b(owe|payable|payables)\b", t) or ("vendor" in t and "bill" in t):
            return self._vendors_owe(t)
        if "invoice" in t and re.search(r"\b(create|make|new)\b", t):
            return self._ask_create(t)
        if re.search(r"\b(last|latest|recent)\b.*\binvoices?\b.*\b(from|of|for)\b", t):
            return self._last_invoices(t)
        if re.search(r"\b(sales|revenue)\b", t):
            return self._sales(t)
        return {"message": "Sorry, I didn't understand. Try: 'what was our total sales last month' "
                           "or 'show invoices overdue by more than 60 days'."}

    # ----------------------------------------------------------- helpers
    def _fmt(self, amount):
        cur = request.env.company.currency_id
        return "{:,.2f} {}".format(amount, cur.name)

    def _period(self, t):
        today = fields.Date.context_today(request.env.user)
        first = today.replace(day=1)
        if "last month" in t:
            return first - relativedelta(months=1), first - relativedelta(days=1), "last month"
        if "this year" in t:
            return today.replace(month=1, day=1), today, "this year"
        if "today" in t:
            return today, today, "today"
        return first, first + relativedelta(months=1, days=-1), "this month"

    # ----------------------------------------------------------- intents
    def _vendors_owe(self, t):
        start, end, label = self._period(t)
        Move = request.env["account.move"]
        base = [("move_type", "=", "in_invoice"), ("state", "=", "posted"),
                ("payment_state", "in", ("not_paid", "partial"))]
        month = Move.search(base + [("invoice_date", ">=", start), ("invoice_date", "<=", end)])
        total_month = sum(abs(m.amount_residual_signed) for m in month)
        total_all = sum(abs(m.amount_residual_signed) for m in Move.search(base))
        return {
            "message": "We owe vendors %s for bills dated %s. Total outstanding payables are %s."
                       % (self._fmt(total_month), label, self._fmt(total_all)),
            "rows": ["%s - %s (%s)" % (m.name, m.partner_id.name, self._fmt(abs(m.amount_residual_signed)))
                     for m in month[:10]],
        }

    def _overdue(self, t):
        m = re.search(r"(\d+)\s*days?", t)
        days = int(m.group(1)) if m else 0
        today = fields.Date.context_today(request.env.user)
        moves = request.env["account.move"].search([
            ("move_type", "=", "out_invoice"), ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
            ("invoice_date_due", "<", today - relativedelta(days=days)),
        ], order="invoice_date_due asc", limit=20)
        if not moves:
            return {"message": "No invoices are overdue by more than %s days." % days}
        total = sum(x.amount_residual for x in moves)
        return {
            "message": "%s invoices are overdue by more than %s days, totalling %s."
                       % (len(moves), days, self._fmt(total)),
            "rows": ["%s - %s - %s days late - %s" % (
                x.name, x.partner_id.name, (today - x.invoice_date_due).days, self._fmt(x.amount_residual))
                for x in moves],
        }

    def _sales(self, t):
        start, end, label = self._period(t)
        moves = request.env["account.move"].search([
            ("move_type", "in", ("out_invoice", "out_refund")), ("state", "=", "posted"),
            ("invoice_date", ">=", start), ("invoice_date", "<=", end),
        ])
        total = sum(m.amount_untaxed_signed for m in moves)  # refunds already negative
        return {"message": "Total sales %s were %s across %s documents."
                           % (label, self._fmt(total), len(moves))}

    def _last_invoices(self, t):
        m = re.search(r"\b(?:last|latest|recent)\s+(\d+|%s)?\s*invoices?\s+(?:from|of|for)\s+(.+)$"
                      % "|".join(NUM), t)
        count = 1
        if m and m.group(1):
            count = NUM.get(m.group(1)) or int(m.group(1))
        name = m.group(2).strip() if m else ""
        partners = request.env["res.partner"].search([("name", "ilike", name)], limit=5)
        if not partners:
            return {"message": "I couldn't find a customer named %s." % name}
        moves = request.env["account.move"].search([
            ("move_type", "=", "out_invoice"), ("state", "=", "posted"),
            ("partner_id", "child_of", partners.ids),
        ], order="invoice_date desc, id desc", limit=count)
        if not moves:
            return {"message": "No posted invoices found for %s." % partners[0].name}
        return {
            "message": "Here are the last %s invoices from %s." % (len(moves), partners[0].name),
            "rows": ["%s - %s - %s - %s" % (x.name, x.invoice_date, self._fmt(x.amount_total),
                                           x.payment_state) for x in moves],
        }

    def _ask_create(self, t):
        m = re.search(r"invoice\s+(?:for|to)\s+(.+)$", t)
        if not m:
            return {"message": "Who is the invoice for? Say: create a draft invoice for <customer>."}
        rest, amount = m.group(1).strip(), None
        a = re.search(r"(?:\bof\b|\bfor\b|\bamount\b|\bworth\b)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*"
                      r"(?:rupees|rs|dollars|usd|pkr)?$", rest)
        if a:
            amount = float(a.group(1).replace(",", ""))
            rest = rest[:a.start()].strip()
        partner = request.env["res.partner"].search([("name", "ilike", rest)], limit=1)
        if not partner:
            return {"message": "I couldn't find a customer named %s." % rest}
        msg = "Create a draft invoice for %s%s?" % (
            partner.name, " of %s" % self._fmt(amount) if amount else "")
        return {"message": msg, "confirm": True,
                "pending": {"partner_id": partner.id, "amount": amount}}

    def _create_draft_invoice(self, partner_id, amount):
        vals = {"move_type": "out_invoice", "partner_id": partner_id}
        if amount:
            vals["invoice_line_ids"] = [(0, 0, {"name": "Created by Voice Assistant",
                                                "quantity": 1, "price_unit": amount})]
        move = request.env["account.move"].create(vals)
        return {"message": "Draft invoice created. Opening it now.",
                "open": {"model": "account.move", "res_id": move.id}}
