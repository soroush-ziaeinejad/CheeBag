"""Generate one customer-policy handbook PDF per seller, plus manifest.json and policy_facts.json.

Run:  python generate_policies.py   (after assign_sellers.py; needs: pip install reportlab pandas)
Output (in data/policies/):
  <Seller_Name>_Policies.pdf   one handbook per seller
  manifest.json                maps each PDF to its database seller (id, categories, checksum, ...)
  policy_facts.json            the key policy values per seller: ground truth for RAG evaluation

All policies are fictional demonstration data, not legally reviewed documents.
"""
import hashlib
import json
import os
import re
from xml.sax.saxutils import escape

import pandas as pd
from reportlab import rl_config

rl_config.invariant = 1  # same input -> byte-identical PDF -> stable checksums

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, ListFlowable, ListItem, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

from policy_facts import PLATFORM, POLICIES
from policy_text import CARE, DESCRIPTOR, EXTRA_FAQ, PARCEL_NOTE, RETURN_TABLE, SETUP, WARRANTY_EXCLUSIONS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the data/ folder (scripts live in data/src/)
OUT_DIR = os.path.join(HERE, "policies")
PROJECT_ROOT = os.path.dirname(HERE)

ACCENT = colors.HexColor("#a4471f")
INK = colors.HexColor("#1f1c18")
MUTED = colors.HexColor("#6f675d")
LINE = colors.HexColor("#e6dfd4")
SOFT = colors.HexColor("#f7f4ef")
MARGIN = 0.9 * inch

STYLES = {
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.8, leading=14, textColor=INK, spaceAfter=6),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.8, leading=11.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5, textColor=INK),
    "H1": ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=14.5, leading=19, textColor=ACCENT, spaceBefore=14, spaceAfter=8, keepWithNext=1),
    "H2": ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=INK, spaceBefore=9, spaceAfter=4, keepWithNext=1),
    "Q": ParagraphStyle("Q", fontName="Helvetica-Bold", fontSize=9.8, leading=14, textColor=INK, spaceBefore=6, spaceAfter=2),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=26, leading=31, textColor=INK, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=14, leading=19, textColor=ACCENT, spaceAfter=18),
    "tochead": ParagraphStyle("tochead", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=INK, spaceBefore=9, spaceAfter=4),
    "toc0": ParagraphStyle("toc0", fontName="Helvetica", fontSize=9.5, leading=12.6, textColor=INK, leftIndent=0),
}


# ---------------------------------------------------------------- small formatting helpers
def money(v):
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def days_range(r, unit="business days"):
    return f"{r[0]} {unit}" if r[0] == r[1] else f"{r[0]}-{r[1]} {unit}"


def hours(h):
    if h < 1:
        return f"{round(h * 60)} minutes"
    return "1 hour" if h == 1 else f"{h:g} hours"


def months(m):
    if m == "lifetime":
        return "Lifetime"
    if m == 1:
        return "1 month (30 days)"
    if m % 12 == 0 and m >= 24:
        return f"{m} months ({m // 12} years)"
    return f"{m} months"


def P(text, style="body"):
    return Paragraph(escape(text), STYLES[style])


def M(markup, style="body"):  # already-escaped markup (for <b>)
    return Paragraph(markup, STYLES[style])


def B(label, text):
    return M(f"<b>{escape(label)}</b> {escape(text)}")


def bullets(items):
    return ListFlowable([ListItem(P(i), leftIndent=12, value="•") for i in items],
                        bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8, spaceAfter=6)


def table(rows, widths, header=True):
    data = [[Paragraph(escape(str(c)), STYLES["cellb" if header and i == 0 else "cell"]) for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1 if header else 0, hAlign="LEFT")
    style = [("GRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 8)]


def kv_table(pairs, widths=(2.1, 4.6)):
    return table([(k, v) for k, v in pairs], widths, header=False)


# ---------------------------------------------------------------- page layout
class NumberedCanvas(canvas.Canvas):
    """Draws 'Page N of M' once the total page count is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(MUTED)
            self.drawRightString(letter[0] - MARGIN, 0.55 * inch, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


class PolicyDoc(BaseDocTemplate):
    def __init__(self, path, seller, facts):
        super().__init__(path, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=0.95 * inch, bottomMargin=0.9 * inch,
                         title=f"{seller['name']} Customer Policy Handbook (version {facts['policy_version']})",
                         author=seller["legal_name"], subject="Customer policies - fictional demonstration data",
                         keywords=f"Chideman seller {seller['seller_id']}; policies; returns; shipping; warranty",
                         creator="Chideman generate_policies.py")
        self.seller, self.facts = seller, facts
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=self.decorate)])

    def decorate(self, c, doc):
        w, h = letter
        c.saveState()
        c.setStrokeColor(LINE)
        c.line(MARGIN, h - 0.7 * inch, w - MARGIN, h - 0.7 * inch)
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(INK)
        c.drawString(MARGIN, h - 0.6 * inch, self.seller["name"])
        c.setFont("Helvetica", 8.5)
        c.setFillColor(MUTED)
        c.drawRightString(w - MARGIN, h - 0.6 * inch, "Customer Policy Handbook")
        c.line(MARGIN, 0.75 * inch, w - MARGIN, 0.75 * inch)
        c.setFont("Helvetica", 8)
        c.drawString(MARGIN, 0.55 * inch, f"Version {self.facts['policy_version']}  |  Effective {self.facts['effective_date']}")
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(MARGIN, 0.38 * inch, "Fictional demonstration document for the Chideman AI portfolio project. Not a legally reviewed policy.")
        c.restoreState()

    def beforeDocument(self):
        self._heading = 0

    def afterFlowable(self, flowable):
        """Add a PDF bookmark for every heading and a table-of-contents entry for every section."""
        if isinstance(flowable, Paragraph) and flowable.style.name in ("H1", "H2"):
            self._heading += 1
            key, text = f"h{self._heading}", flowable.getPlainText()
            level = 0 if flowable.style.name == "H1" else 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=True)
            if level == 0:
                self.notify("TOCEntry", (0, text, self.page, key))


# ---------------------------------------------------------------- the handbook, section by section
class Handbook:
    def __init__(self, seller, facts, catalog):
        self.s, self.f, self.cat = seller, facts, catalog
        self.n = 0

    def h1(self, title):
        self.n += 1
        self.sub = 0
        return Paragraph(f"{self.n}. {escape(title)}", STYLES["H1"])

    def h2(self, title):
        self.sub += 1
        return Paragraph(f"{self.n}.{self.sub} {escape(title)}", STYLES["H2"])

    # ---- cover and contents
    def cover(self):
        s, f = self.s, self.f
        toc = TableOfContents()
        toc.levelStyles = [STYLES["toc0"]]
        toc.dotsMinLevel = 0
        return [Spacer(1, 0.1 * inch), P(s["name"], "title"), P("Customer Policy Handbook", "subtitle"),
                *kv_table([("Seller", f"{s['name']} ({s['legal_name']})"),
                           ("Chideman seller ID", str(s["seller_id"])),
                           ("Policy version", f["policy_version"]),
                           ("Effective date", f["effective_date"]),
                           ("Applies to", f"All orders for products sold by {s['name']} on the Chideman marketplace")]),
                P(f"This handbook explains how {s['name']} handles orders, payments, shipping, returns, refunds, "
                  "warranties and customer service. Please read it before you buy. Section 18 summarizes the key numbers "
                  "on one page."),
                P("This is a fictional document created as demonstration data for the Chideman AI portfolio project. "
                  "It is not a legally reviewed policy and does not describe a real company.", "small"),
                Spacer(1, 6), P("Contents", "tochead"), toc, PageBreak()]

    # ---- 1
    def about(self):
        s, f, cat = self.s, self.f, self.cat
        brands = ", ".join(cat["top_brands"][:5])
        return [self.h1(f"About {s['name']} and These Policies"),
                self.h2("Who we are"),
                P(f"{s['name']} ({s['legal_name']}) is an independent retailer founded in {s['founded_year']} and based in "
                  f"{s['headquarters']}. {s['description']} We sell and ship our products through the Chideman online "
                  "marketplace, and every order is packed and shipped by our own team."),
                *kv_table([("Legal name", s["legal_name"]), ("Headquarters", s["headquarters"]),
                           ("Founded", str(s["founded_year"])), ("Chideman seller ID", str(s["seller_id"])),
                           ("Customer support", f"{s['support_email']}  |  {s['support_phone']}"),
                           ("Support hours", f["service"]["hours"]),
                           ("Product categories", "; ".join(cat["categories"])),
                           ("Products listed", f"{cat['count']} products")]),
                self.h2("Sellers and brands"),
                P(f"{s['name']} is the seller of the products listed under our name on Chideman. The products themselves are "
                  f"made by many different brands, such as {brands}. Your purchase is from {s['legal_name']}, and this "
                  "handbook governs it. A brand's own manufacturer warranty may apply in addition to the warranty described "
                  "in Section 9."),
                self.h2("Definitions"),
                bullets([f"Business day: Monday to Friday, excluding US federal holidays.",
                         "Order statuses: Pending (payment authorized, not yet being prepared), Processing (being picked and "
                         "packed), Shipped (handed to the carrier, tracking available), Delivered, and Cancelled.",
                         "Delivery date: the date the carrier's tracking shows the package as delivered.",
                         "Return authorization: the approval and return label you receive after requesting a return."]),
                self.h2("Changes to this handbook"),
                P(f"This version ({f['policy_version']}) applies to orders placed on or after {f['effective_date']}. Orders placed "
                  "earlier follow the version in force when they were placed. We announce material changes on our Chideman "
                  "seller page at least 14 days before they take effect.")]

    # ---- 2
    def ordering(self):
        s, f = self.s, self.f
        c = f["cancellation"]
        mod = f["order_modification_window_hours"]
        mod_text = ("You can change the shipping address, quantities or items of an order while its status is Pending."
                    if mod is None else
                    f"You can change the shipping address, quantities or items of an order within {hours(mod)} of placing it, "
                    "as long as it has not shipped.")
        out = [self.h1("Ordering, Order Changes and Cancellation"),
               self.h2("Placing an order"),
               P("When you place an order on Chideman, you receive an order confirmation email with your order number. "
                 "Your payment is authorized immediately and the order starts in the Pending status. You can follow its "
                 "status on the My orders page or by asking the Chideman AI assistant."),
               self.h2("Changing an order"),
               P(mod_text + " After that, we cannot change the order; if it can still be cancelled (Section 2.3), you can "
                 "cancel it and place a new one."),
               self.h2("Cancelling an order"),
               P(c["rule"]),
               P("To cancel, open the order on the My orders page or ask the Chideman AI assistant, and confirm the "
                 "cancellation when asked. You receive a confirmation email once it is done."),
               B("Refund of cancelled orders:", f"the payment authorization is released or refunded within "
                 f"{c['refund_business_days']} business day{'s' if c['refund_business_days'] > 1 else ''} of cancellation."
                 + (f" A {money(c['fee_after_window_usd'])} fee applies in the case described above." if c["fee_after_window_usd"] else "")),
               P("Orders that have already shipped cannot be cancelled. You can refuse the delivery or return the items "
                 "under Section 6.")]
        out += [self.h2("Orders we may cancel"),
                bullets(["An item is out of stock after you ordered it. We tell you by email and refund it in full.",
                         "A price or product description on the listing was clearly wrong. We contact you before shipping.",
                         "We cannot verify the payment or suspect fraud."]),
                P(f"{s['name']} does not take backorders: items are only shown as available when we have them in stock.")]
        return out

    # ---- 3
    def payments(self):
        s = self.s
        short = DESCRIPTOR[s["seller_id"]]
        return [self.h1("Payments, Billing and Taxes"),
                self.h2("Payment methods"),
                P(f"We accept {', '.join(PLATFORM['payment_methods'][:-1])} and {PLATFORM['payment_methods'][-1]}, processed "
                  "securely by Chideman. All prices are in US dollars (USD)."),
                self.h2("When you are charged"),
                P("Your payment is authorized when you place the order and captured when the order moves to Processing. "
                  f"Charges appear on your statement as CHIDEMAN*{short}. If a payment cannot be authorized within 48 hours, "
                  "the order is cancelled automatically."),
                self.h2("Taxes"),
                P("Sales tax is calculated from the shipping address at checkout and shown before you pay. When you return "
                  "items, the sales tax on them is refunded in proportion. Tax-exempt purchases are not supported on "
                  "Chideman at this time."),
                self.h2("Billing questions"),
                P(f"For a charge you don't recognize, contact us at {s['support_email']} with the amount and date. We "
                  "never ask for full card numbers by email or phone.")]

    # ---- 4
    def shipping(self):
        s, f = self.s, self.f
        sh = f["shipping"]
        rows = [("Method", "Cost", "Delivery time after dispatch"),
                ("Standard", f"Free on orders of {money(sh['free_threshold_usd'])} or more; otherwise {money(sh['standard_fee_usd'])}",
                 days_range(sh["standard_business_days"])),
                ("Expedited", money(sh["expedited_fee_usd"]), days_range(sh["expedited_business_days"]))]
        if sh["overnight_fee_usd"]:
            rows.append(("Overnight", money(sh["overnight_fee_usd"]), "1 business day (order by 12 pm ET)"))
        return [self.h1("Shipping and Delivery"),
                self.h2("Processing time"),
                P(f"Orders are dispatched within {sh['handling_business_days']} business day{'s' if sh['handling_business_days'] > 1 else ''} "
                  "of being placed. The delivery times below start when the order ships."),
                self.h2("Shipping options and costs"),
                *table(rows, (1.2, 3.2, 2.3)),
                P(f"The free-shipping threshold of {money(sh['free_threshold_usd'])} is based on the order subtotal from "
                  f"{s['name']} after discounts and before tax."),
                self.h2("Where we ship"),
                bullets([f"We ship to {PLATFORM['ships_to']}.",
                         f"Orders to Alaska and Hawaii ship by standard service only, with a {money(sh['alaska_hawaii_surcharge_usd'])} surcharge, "
                         "and take 4 to 6 business days longer.",
                         "We ship to PO boxes (standard shipping only)." if sh["po_boxes"] else "We do not ship to PO boxes.",
                         f"We ship with {', '.join(PLATFORM['carriers'])}, depending on the destination and package size."]),
                self.h2("Tracking and delays"),
                P("You receive a tracking number by email when your order ships, and the order status changes to Shipped. "
                  "Large orders may ship in several packages at no extra cost. Carrier delays caused by weather or holidays "
                  "can extend delivery times; we are not responsible for carrier delays, but we will help you follow up."),
                self.h2("Lost packages and address problems"),
                P(f"If tracking shows your package as delivered but you cannot find it, tell us within "
                  f"{f['lost_package_claim_days']} days of the delivery date. We open an investigation with the carrier, which "
                  "takes up to 5 business days, and then send a replacement or a full refund."),
                P("Please check your shipping address before ordering. If a package is returned to us because the address "
                  "was incorrect, we refund the order minus the original shipping cost.")]

    # ---- 5
    def large_items(self):
        s, f = self.s, self.f
        li = f["large_items"]
        out = [self.h1("Large and Bulky Item Delivery")]
        if not li:
            return out + [P(PARCEL_NOTE[s["seller_id"]])]
        return out + [
            self.h2("Which items are oversized"),
            P(f"Items over {li['threshold_lb']} lb, such as {li['examples']}, are oversized and delivered by a freight carrier "
              "instead of a parcel service."),
            self.h2("Freight delivery"),
            *table([("Detail", "Oversized items"),
                    ("Delivery fee", f"{money(li['fee_usd'])} flat per order ({li['service']}); not covered by free shipping"),
                    ("Delivery time", days_range(li["business_days"]) + " after dispatch"),
                    ("Appointment", f"The carrier calls to book a {li['appointment_window_hours']}-hour delivery window"),
                    ("Signature", "Required; someone 18 or older must be present"),
                    ("In-home placement", f"{money(li['in_home_placement_fee_usd'])} extra: carried to the room of your choice and packaging removed"),
                    ("Not available to", ", ".join(li["excluded_regions"])),
                    ("Expedited shipping", "Not available for oversized items")], (1.6, 5.1)),
            self.h2("Missed deliveries and inspection"),
            P("If nobody is available during the booked window, the carrier reschedules once at no charge. A second missed "
              "appointment incurs a $39 redelivery fee. Inspect the box with the driver and note any visible damage on the "
              "delivery receipt before signing (see Section 8)."),
            self.h2("Returning an oversized item"),
            P(f"Oversized returns are picked up by freight for {money(li['oversized_return_pickup_usd'])}, deducted from the refund. "
              "Pickup is free when the item is defective, damaged or incorrect.")]

    # ---- 6
    def returns(self):
        s, f = self.s, self.f
        r, ex = f["returns"], f["exchanges"]
        fee = (f"A restocking fee of {r['restocking_fee_percent']}% applies to "
               + (r.get("restocking_fee_applies_to") or "opened or used items") + ". It is waived for defective, damaged or incorrect items."
               if r["restocking_fee_percent"] else f"{s['name']} does not charge restocking fees.")
        out = [self.h1("Returns and Exchanges"),
               self.h2("Return window and condition"),
               P(f"You can return most items within {r['window_days']} days of the delivery date. Items must be "
                 f"{r['condition']}, with all parts and accessories."),
               self.h2("Return rules by product type"),
               *table([("Product type", "Return window", "Condition", "Restocking fee")] + RETURN_TABLE[s["seller_id"]],
                      (2.4, 1.1, 2.1, 1.1)),
               self.h2("Items that cannot be returned"),
               bullets([i[0].upper() + i[1:] + "." for i in r["non_returnable"]]),
               P("Defective, damaged or incorrect items are always handled under Section 8, even if they are listed above."),
               self.h2("Restocking fees and return shipping"),
               P(fee),
               P(f"Return shipping: {r['return_shipping']}."),
               self.h2("How to return an item"),
               bullets(["Start the return on the My orders page or ask the Chideman AI assistant, and choose the items and reason.",
                        "You receive a return authorization and, where applicable, a prepaid label by email.",
                        "Pack the items securely, preferably in the original packaging, and ship them within 14 days of receiving the label.",
                        "We inspect the return when it arrives and process the refund as described in Section 7."]),
               self.h2("Exchanges")]
        if ex["allowed"]:
            out.append(P(f"Exchanges are available within {ex['window_days']} days of delivery. Shipping for exchanges: "
                         f"{ex['shipping']}. The replacement ships once we receive the original item."))
        else:
            out.append(P(f"{s['name']} does not offer exchanges. Please return the item for a refund and place a new order."))
        out.append(P("Gifts: items bought as gifts can be returned by the recipient with the order number; the refund is "
                     "issued as a Chideman gift card."))
        return out

    # ---- 7
    def refunds(self):
        s, f = self.s, self.f
        n = f["refund_processing_business_days"]
        return [self.h1("Refunds"),
                self.h2("Refund timeline"),
                P(f"We process refunds within {n} business days of receiving and inspecting your return. Your bank or card "
                  "issuer may take another 3 to 10 business days to show the refund on your statement."),
                self.h2("How you are refunded"),
                bullets(["Refunds go back to the original payment method.",
                         "Amounts paid with a Chideman gift card are refunded to the gift card balance.",
                         f"Cancelled orders are refunded within {f['cancellation']['refund_business_days']} business "
                         f"day{'s' if f['cancellation']['refund_business_days'] > 1 else ''} (Section 2.3)."]),
                self.h2("What is refunded"),
                bullets(["The price paid for the returned items and the sales tax on them.",
                         "Original shipping costs only if the item was defective, damaged or incorrect, or we made an error.",
                         "Deductions, where they apply: the return label cost and any restocking fee (Section 6).",
                         "Items returned incomplete or damaged after delivery may receive a partial refund; we email photos and the amount before refunding."]),
                self.h2("Discounted and bundled items"),
                P("If you return part of a discounted bundle or multi-buy, the refund reflects the discount that applied to "
                  "the returned items, so you only pay for what you keep at its regular price.")]

    # ---- 8
    def damaged(self):
        s, f = self.s, self.f
        d = f["damage_report_days"]
        freight = ([B("Freight deliveries:", "visible damage to an oversized item must be noted on the carrier's delivery "
                      "receipt before signing. Report hidden damage within the same window, with photos.")]
                   if f["large_items"] else [])
        return [self.h1("Damaged, Defective, Missing or Incorrect Items"),
                self.h2("Damaged or defective on arrival"),
                P(f"Report damaged or defective items within {d} days of the delivery date. Send photos of the item, the "
                  "packaging and the shipping label to our support team or through the Chideman AI assistant. We send a "
                  "free replacement or a full refund, including original shipping. In most cases you don't need to send the "
                  "damaged item back; if we need it, we provide a prepaid label."),
                *freight,
                self.h2("Missing items"),
                P(f"If an item is missing, first check whether your order shipped in several packages. Then tell us within "
                  f"{d} days of delivery and we will ship the missing item at no cost."),
                self.h2("Incorrect items"),
                P(f"If you received the wrong item, tell us within {d} days of delivery. We send a prepaid return label and "
                  "ship the correct item by expedited shipping at no extra cost."),
                self.h2("Problems after the reporting window"),
                P("Defects that appear later are handled under the warranty in Section 9.")]

    # ---- 9
    def warranty(self):
        s, f = self.s, self.f
        rows = [("What is covered", "Warranty period", "Details")] + [(w["covers"], months(w["months"]), w["notes"]) for w in f["warranty"]]
        return [self.h1("Product Warranty"),
                self.h2("Coverage"),
                P(f"{s['name']} warrants its products against defects in materials and workmanship under normal home use for "
                  "the periods below, starting on the delivery date."),
                *table(rows, (3.0, 1.5, 2.2)),
                self.h2("What is not covered"),
                bullets(["Normal wear and tear, misuse, accidents, and commercial use.",
                         "Repairs or modifications by anyone other than us or the manufacturer.",
                         "Cosmetic damage that does not affect how the product works."]
                        + [x + "." for x in WARRANTY_EXCLUSIONS[s["seller_id"]]]),
                self.h2("How to make a warranty claim"),
                bullets([f"Contact us at {s['support_email']} or through the Chideman AI assistant with your Chideman order "
                         "number, a description of the problem and a photo or short video.",
                         f"We reply within {f['service']['first_response_hours']} hours and decide whether to repair, replace "
                         "or refund the product.",
                         "Approved replacements ship within 5 business days at no cost. Your Chideman order is your proof of purchase."]),
                P("Manufacturer warranties from the brand may give you additional rights; our warranty does not limit them.")]

    # ---- 10, 11, 12
    def setup(self):
        return [self.h1("Assembly, Installation and Setup"), bullets(SETUP[self.s["seller_id"]])]

    def care(self):
        return [self.h1("Product Care and Maintenance"),
                P("Following these care instructions keeps products working well and protects your warranty."),
                bullets(CARE[self.s["seller_id"]])]

    def custom(self):
        s, p = self.s, self.f["personalization"]
        out = [self.h1("Custom and Personalized Products")]
        if not p:
            return out + [P(f"{s['name']} does not offer custom-made or personalized products. All items are standard "
                            "stock items and follow the normal return rules in Section 6.")]
        window = self.f["cancellation"].get("engraved_window_hours") or self.f["cancellation"].get("monogram_window_hours")
        return out + [
            P(f"We offer {p['what']} for {money(p['fee_usd'])} per item."),
            bullets([f"Personalized orders take {p['extra_business_days']} extra business days before they ship.",
                     f"They can only be cancelled within {hours(window)} of ordering, because work starts right away.",
                     "Personalized items are final sale and cannot be returned or exchanged, unless they arrive damaged or "
                     "defective, or the personalization does not match what you submitted.",
                     "Text is reproduced exactly as entered, so please check spelling before you order."])]

    # ---- 13
    def promotions(self):
        s, f = self.s, self.f
        pr = f["promotions"]
        items = [f"Only {pr['codes_per_order']} promotional code can be used per order, and codes cannot be added after an order is placed.",
                 "Promotions cannot be exchanged for cash and do not apply to Chideman gift cards."]
        if pr.get("welcome_discount_percent"):
            items.insert(0, f"New customers who join our newsletter get {pr['welcome_discount_percent']}% off their first order (once per customer).")
        for key, label in (("bundle", "Bundle offer"), ("bulk_discount", "Bulk discount"), ("multi_buy", "Multi-buy offer"),
                           ("subscription", "Subscription"), ("gift_wrap_usd", "Gift wrap")):
            if key in pr:
                value = f"{money(pr[key])} per item" if key == "gift_wrap_usd" else pr[key]
                items.insert(0, f"{label}: {value}.")
        n = f["price_adjustment_days"]
        adj = (f"If the price of an item drops within {n} days of your order, we refund the difference once per item. Ask "
               "us with your order number. Price adjustments do not apply to flash sales, clearance items or other retailers' prices."
               if n else f"{s['name']} does not offer price adjustments or price matching after an order is placed.")
        return [self.h1("Promotions, Discounts and Price Adjustments"),
                self.h2("Current offers and rules"), bullets(items),
                self.h2("Price adjustments"), P(adj)]

    # ---- 14
    def service(self):
        s, f = self.s, self.f
        sv = f["service"]
        return [self.h1("Customer Service, Complaints and Escalation"),
                self.h2("Contacting us"),
                *kv_table([("Email", s["support_email"]), ("Phone", s["support_phone"]), ("Hours", sv["hours"]),
                           ("Chideman AI assistant", "Available 24/7 for order status, returns and policy questions"),
                           ("First response", f"Within {sv['first_response_hours']} hours")]),
                self.h2("Complaints and escalation"),
                bullets(["Step 1: contact customer service with your order number and a short description.",
                         f"Step 2: if you are not satisfied with the answer, ask for an escalation. A team lead reviews the case "
                         f"and replies within {sv['escalation_business_days']} business days.",
                         f"Step 3: if the issue is still unresolved {sv['marketplace_mediation_after_days']} days after your first "
                         "contact, you can ask Chideman marketplace support to mediate. Chideman reviews both sides and its "
                         "decision on refunds is final for the marketplace."]),
                P("We keep a record of every complaint and use them to improve our products and policies.")]

    # ---- 15
    def privacy(self):
        s, f = self.s, self.f
        return [self.h1("Privacy and Data Handling"),
                self.h2("What we receive"),
                P("To fulfil your order, Chideman shares with us your name, shipping address, email address, phone number "
                  "and the details of your order. Payments are processed by Chideman: we never see or store full card numbers."),
                self.h2("How we use it"),
                bullets(["To pack, ship and track your order and handle returns, refunds and warranty claims.",
                         "To answer your questions and complaints.",
                         "To send marketing emails only if you opted in; you can unsubscribe at any time."]),
                self.h2("Retention and your rights"),
                P(f"We keep order records for {f['data_retention_years']} years for tax, accounting and warranty purposes, and "
                  "then delete or anonymize them. We do not sell your personal information. You can ask to access, correct or "
                  f"delete your data by emailing {s['support_email']}; we respond within 30 days. Residents of some states have "
                  "additional privacy rights under their state's law."),
                self.h2("Security"),
                P("Access to customer data is limited to the staff who need it, and all data is transmitted and stored encrypted.")]

    # ---- 16
    def legal(self):
        s, f = self.s, self.f
        return [self.h1("Legal Terms and Consumer Rights"),
                bullets([f"Your purchase contract is with {s['legal_name']}. Chideman operates the marketplace and processes payments.",
                         "Our liability for any order is limited to the amount you paid for it, except where the law does not allow this limitation.",
                         "If a product is recalled for safety reasons, we contact affected customers and offer a refund, repair or replacement.",
                         f"These policies are governed by the laws of the State of {f['governing_law']}. Disputes are handled first "
                         "through customer service and Chideman mediation (Section 14); you may also bring a claim in small claims court.",
                         "Nothing in this handbook limits your statutory rights as a consumer.",
                         "If any part of this handbook is found unenforceable, the rest remains in effect. If a product page and "
                         "this handbook disagree on a policy, this handbook applies."])]

    # ---- 17
    def faq(self):
        s, f = self.s, self.f
        r, sh, c = f["returns"], f["shipping"], f["cancellation"]
        mod = f["order_modification_window_hours"]
        qa = [
            ("How long do I have to return an item?",
             f"{r['window_days']} days from the delivery date. Items must be {r['condition']}. See Section 6 for items that cannot be returned."),
            ("Can I cancel my order?", c["rule"]),
            ("How much is shipping, and when is it free?",
             f"Standard shipping is free on orders of {money(sh['free_threshold_usd'])} or more and costs {money(sh['standard_fee_usd'])} "
             f"otherwise. Expedited shipping costs {money(sh['expedited_fee_usd'])}."),
            ("How long will my order take to arrive?",
             f"We dispatch within {sh['handling_business_days']} business day{'s' if sh['handling_business_days'] > 1 else ''}; standard "
             f"delivery then takes {days_range(sh['standard_business_days'])} and expedited delivery {days_range(sh['expedited_business_days'])}."),
            ("My item arrived damaged. What should I do?",
             f"Report it within {f['damage_report_days']} days of delivery with photos of the item, packaging and label. We send a free "
             "replacement or a full refund."),
            ("When will I get my refund?",
             f"Within {f['refund_processing_business_days']} business days of receiving your return, plus 3 to 10 business days for your bank."),
            ("Do you charge a restocking fee?",
             (f"Yes, {r['restocking_fee_percent']}% on " + (r.get("restocking_fee_applies_to") or "opened or used items")
              + ". It is waived for defective, damaged or incorrect items.") if r["restocking_fee_percent"] else "No, never."),
            ("Can I change my shipping address after ordering?",
             "Yes, while the order is Pending." if mod is None else f"Yes, within {hours(mod)} of placing the order, if it has not shipped."),
            ("The price dropped after I bought it. Can I get the difference?",
             f"Yes, within {f['price_adjustment_days']} days of your order, once per item." if f["price_adjustment_days"]
             else "No. We do not offer price adjustments after an order is placed."),
            ("Do you ship to Alaska, Hawaii, PO boxes or other countries?",
             f"Alaska and Hawaii: yes, standard shipping only, with a {money(sh['alaska_hawaii_surcharge_usd'])} surcharge. "
             f"PO boxes: {'yes, standard shipping only' if sh['po_boxes'] else 'no'}. We do not ship outside the United States."),
            ("Can I exchange an item?",
             f"Yes, within {f['exchanges']['window_days']} days of delivery; shipping is {f['exchanges']['shipping']}." if f["exchanges"]["allowed"]
             else "We don't offer exchanges. Return the item for a refund and place a new order."),
            ("Tracking says delivered, but I don't have my package.",
             f"Check around your home and with neighbors, then tell us within {f['lost_package_claim_days']} days of the delivery date. "
             "We investigate with the carrier (up to 5 business days) and then replace or refund the order."),
            ("How do I make a warranty claim?",
             f"Email {s['support_email']} or ask the Chideman AI assistant with your order number, a description and a photo or video. "
             f"We reply within {f['service']['first_response_hours']} hours."),
            ("I paid with a Chideman gift card. How am I refunded?",
             "Amounts paid with a gift card are refunded to the gift card balance; the rest goes back to your other payment method."),
        ] + EXTRA_FAQ[s["seller_id"]]
        out = [self.h1("Frequently Asked Questions")]
        for q, a in qa:
            out.append(KeepTogether([P(q, "Q"), P(a)]))
        return out

    # ---- 18
    def summary(self):
        s, f = self.s, self.f
        r, sh, c = f["returns"], f["shipping"], f["cancellation"]
        mod = f["order_modification_window_hours"]
        rows = [("Policy", "Value"),
                ("Return window", f"{r['window_days']} days from delivery"),
                ("Restocking fee", f"{r['restocking_fee_percent']}%" + (f" ({r['restocking_fee_applies_to'] if r.get('restocking_fee_applies_to') else 'opened or used items'})" if r["restocking_fee_percent"] else "")),
                ("Return shipping", r["return_shipping"]),
                ("Exchanges", f"Yes, {f['exchanges']['window_days']} days" if f["exchanges"]["allowed"] else "Not offered"),
                ("Free cancellation", f"Within {hours(c['free_window_hours'])} if not shipped" if c["free_window_hours"] else "While status is " + " or ".join(c["allowed_statuses"])),
                ("Order changes", "While Pending" if mod is None else f"Within {hours(mod)}"),
                ("Refund processing", f"{f['refund_processing_business_days']} business days after the return arrives"),
                ("Free shipping threshold", money(sh["free_threshold_usd"])),
                ("Standard shipping", f"{money(sh['standard_fee_usd'])}, {days_range(sh['standard_business_days'])}"),
                ("Expedited shipping", f"{money(sh['expedited_fee_usd'])}, {days_range(sh['expedited_business_days'])}"),
                ("Dispatch time", f"{sh['handling_business_days']} business day{'s' if sh['handling_business_days'] > 1 else ''}"),
                ("Report damage within", f"{f['damage_report_days']} days of delivery"),
                ("Lost package claims", f"Within {f['lost_package_claim_days']} days of delivery"),
                ("Price adjustment", f"{f['price_adjustment_days']} days" if f["price_adjustment_days"] else "Not offered")]
        if f["large_items"]:
            rows.append(("Oversized delivery", f"{money(f['large_items']['fee_usd'])} curbside, {days_range(f['large_items']['business_days'])}"))
        rows += [("Warranty: " + w["covers"], months(w["months"])) for w in f["warranty"]]
        if f["personalization"]:
            p = f["personalization"]
            rows.append(("Personalization", f"{money(p['fee_usd'])} per item, +{p['extra_business_days']} business days, final sale"))
        rows += [("First response time", f"{f['service']['first_response_hours']} hours"),
                 ("Data retention", f"{f['data_retention_years']} years"), ("Governing law", f["governing_law"])]
        return [self.h1("Key Policies at a Glance"), *table(rows, (2.6, 4.1))]

    def story(self):
        parts = [self.cover(), self.about(), self.ordering(), self.payments(), self.shipping(), self.large_items(),
                 self.returns(), self.refunds(), self.damaged(), self.warranty(), self.setup(), self.care(),
                 self.custom(), self.promotions(), self.service(), self.privacy(), self.legal(), self.faq(), self.summary()]
        return [x for part in parts for x in part]


# ---------------------------------------------------------------- outputs
def pdf_name(seller_name):
    return re.sub(r"[^A-Za-z0-9]+", "_", seller_name).strip("_") + "_Policies.pdf"


def key_values(seller, f):
    """Flat values for RAG evaluation: one expected answer per common customer question."""
    r, sh, c = f["returns"], f["shipping"], f["cancellation"]
    out = {"seller_id": seller["seller_id"], "seller_name": seller["name"], "policy_version": f["policy_version"],
           "effective_date": f["effective_date"],
           "return_window_days": r["window_days"], "restocking_fee_percent": r["restocking_fee_percent"],
           "return_label_fee_usd": r["return_label_fee_usd"], "exchanges_allowed": f["exchanges"]["allowed"],
           "free_cancellation_window_hours": c["free_window_hours"], "cancellable_statuses": c["allowed_statuses"],
           "cancellation_fee_after_window_usd": c["fee_after_window_usd"], "order_modification_window_hours": f["order_modification_window_hours"],
           "refund_processing_business_days": f["refund_processing_business_days"], "cancellation_refund_business_days": c["refund_business_days"],
           "free_shipping_threshold_usd": sh["free_threshold_usd"], "standard_shipping_fee_usd": sh["standard_fee_usd"],
           "standard_delivery_business_days": sh["standard_business_days"], "expedited_shipping_fee_usd": sh["expedited_fee_usd"],
           "expedited_delivery_business_days": sh["expedited_business_days"], "dispatch_business_days": sh["handling_business_days"],
           "alaska_hawaii_surcharge_usd": sh["alaska_hawaii_surcharge_usd"], "ships_to_po_boxes": sh["po_boxes"],
           "damage_report_days": f["damage_report_days"], "lost_package_claim_days": f["lost_package_claim_days"],
           "price_adjustment_days": f["price_adjustment_days"],
           "warranties": [{"covers": w["covers"], "months": w["months"]} for w in f["warranty"]],
           "personalization_offered": bool(f["personalization"]),
           "oversized_delivery_fee_usd": f["large_items"]["fee_usd"] if f["large_items"] else None,
           "first_response_hours": f["service"]["first_response_hours"], "data_retention_years": f["data_retention_years"],
           "governing_law": f["governing_law"]}
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sellers = pd.read_csv(os.path.join(HERE, "sellers.csv"))
    products = pd.read_csv(os.path.join(HERE, "products_clean.csv")).merge(
        pd.read_csv(os.path.join(HERE, "product_sellers.csv")), left_on="id", right_on="product_id")

    manifest, facts_out = [], []
    for seller in sellers.to_dict("records"):
        sid = seller["seller_id"]
        f = POLICIES[sid]
        mine = products[products.seller_id == sid]
        catalog = {"count": len(mine), "categories": sorted(mine.category.unique()),
                   "top_brands": mine.brand.dropna().value_counts().index.tolist()}
        name = pdf_name(seller["name"])
        path = os.path.join(OUT_DIR, name)

        doc = PolicyDoc(path, seller, f)
        doc.multiBuild(Handbook(seller, f, catalog).story(), canvasmaker=NumberedCanvas)

        with open(path, "rb") as fh:
            checksum = hashlib.sha256(fh.read()).hexdigest()
        manifest.append({"seller_id": sid, "seller_name": seller["name"], "legal_name": seller["legal_name"],
                         "pdf_path": os.path.relpath(path, PROJECT_ROOT), "policy_version": f["policy_version"],
                         "effective_date": f["effective_date"], "product_categories": catalog["categories"],
                         "product_count": catalog["count"], "page_count": doc.page,
                         "document_checksum": f"sha256:{checksum}", "is_current": True})
        facts_out.append({"key_values": key_values(seller, f), "details": f})
        print(f"{seller['seller_id']} {seller['name']:28} {catalog['count']:>3} products  {doc.page:>2} pages  {name}")

    note = "Fictional demonstration data for the Chideman AI portfolio project; not legally reviewed policies."
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as fh:
        json.dump({"note": note, "documents": manifest}, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "policy_facts.json"), "w") as fh:
        json.dump({"note": note, "platform": PLATFORM, "sellers": facts_out}, fh, indent=2, ensure_ascii=False)
    print(f"wrote {len(manifest)} PDFs, manifest.json and policy_facts.json -> {OUT_DIR}")


if __name__ == "__main__":
    main()
