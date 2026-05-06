"""
generate_test_invoices.py
Generates 8 synthetic Indian purchase invoice PDFs for parser testing.
Buyer is always: Entvin Labs Private Limited, GSTIN 29AAHCE1996R1ZL
"""

import os
import json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

OUTPUT_DIR = "data/test_invoices"
os.makedirs(OUTPUT_DIR, exist_ok=True)

W, H = A4  # 595.27 x 841.89 pt
BUYER_NAME = "Entvin Labs Private Limited"
BUYER_GSTIN = "29AAHCE1996R1ZL"
BUYER_ADDR = "No. 42, Koramangala 5th Block, Bengaluru, Karnataka - 560095"

ground_truth = {}


# ---------------------------------------------------------------------------
# Helper: draw a horizontal line
# ---------------------------------------------------------------------------
def hline(c, x1, x2, y, width=0.5):
    c.setLineWidth(width)
    c.line(x1, y, x2, y)


# ---------------------------------------------------------------------------
# Invoice A — Zoho-style (Tamil Nadu seller, single line item, CGST+SGST)
# ---------------------------------------------------------------------------
def gen_invoice_a():
    fname = "invoice_A1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    # Header row: company name left, "TAX INVOICE" right
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30 * mm, H - 25 * mm, "NEXGEN SOFTWARE SOLUTIONS PRIVATE LIMITED")
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(W - 30 * mm, H - 25 * mm, "TAX INVOICE")

    c.setFont("Helvetica", 9)
    c.drawString(30 * mm, H - 32 * mm, "45, Anna Nagar, Chennai - 600 040, Tamil Nadu")
    c.drawString(30 * mm, H - 37 * mm, "GSTIN: 33AABCN4521A1Z7   |   PAN: AABCN4521A")
    c.drawString(30 * mm, H - 42 * mm, "Email: accounts@nexgensoftware.in   |   Ph: 044-23456789")

    hline(c, 20 * mm, W - 20 * mm, H - 46 * mm)

    # Invoice meta
    c.setFont("Helvetica-Bold", 9)
    c.drawString(30 * mm, H - 53 * mm, "Invoice No.:")
    c.setFont("Helvetica", 9)
    c.drawString(60 * mm, H - 53 * mm, "INV/2024-25/047")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(30 * mm, H - 59 * mm, "Invoice Date:")
    c.setFont("Helvetica", 9)
    c.drawString(60 * mm, H - 59 * mm, "15/03/2025")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(30 * mm, H - 65 * mm, "Place of Supply:")
    c.setFont("Helvetica", 9)
    c.drawString(60 * mm, H - 65 * mm, "Tamil Nadu (33)")

    # Bill To
    hline(c, 20 * mm, W - 20 * mm, H - 70 * mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30 * mm, H - 77 * mm, "Bill To")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(30 * mm, H - 83 * mm, BUYER_NAME)
    c.setFont("Helvetica", 9)
    c.drawString(30 * mm, H - 89 * mm, BUYER_ADDR)
    c.drawString(30 * mm, H - 95 * mm, f"GSTIN: {BUYER_GSTIN}")

    hline(c, 20 * mm, W - 20 * mm, H - 100 * mm)

    # Line items table
    c.setFont("Helvetica-Bold", 9)
    cols = [30 * mm, 100 * mm, 135 * mm, 160 * mm, W - 30 * mm]
    headers = ["Description", "HSN/SAC", "Qty", "Rate (₹)", "Amount (₹)"]
    row_y = H - 108 * mm
    for i, h_txt in enumerate(headers):
        c.drawString(cols[i], row_y, h_txt)
    hline(c, 20 * mm, W - 20 * mm, row_y - 3 * mm)

    c.setFont("Helvetica", 9)
    row_y -= 9 * mm
    c.drawString(cols[0], row_y, "Annual Software Maintenance Fee")
    c.drawString(cols[1], row_y, "998313")
    c.drawString(cols[2], row_y, "1")
    c.drawString(cols[3], row_y, "10,000.00")
    c.drawString(cols[4], row_y, "10,000.00")

    hline(c, 20 * mm, W - 20 * mm, row_y - 4 * mm)

    # Totals
    ty = row_y - 12 * mm
    tax_rows = [
        ("Subtotal", "10,000.00"),
        ("CGST @ 9%", "900.00"),
        ("SGST @ 9%", "900.00"),
        ("Total", "11,800.00"),
    ]
    for label, val in tax_rows:
        c.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 9)
        c.drawRightString(W - 50 * mm, ty, label + ":")
        c.drawRightString(W - 30 * mm, ty, val)
        ty -= 7 * mm

    hline(c, 20 * mm, W - 20 * mm, ty + 2 * mm)

    c.setFont("Helvetica", 8)
    c.drawString(30 * mm, ty - 8 * mm, "Amount in words: Eleven Thousand Eight Hundred Rupees Only")
    c.drawString(30 * mm, ty - 15 * mm, "Bank: HDFC Bank  |  A/C: 50100123456789  |  IFSC: HDFC0001234")

    c.setFont("Helvetica-BoldOblique", 8)
    c.drawRightString(W - 30 * mm, ty - 20 * mm, "Authorised Signatory")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "NEXGEN SOFTWARE SOLUTIONS PRIVATE LIMITED",
        "vendor_gstin": "33AABCN4521A1Z7",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "INV/2024-25/047",
        "invoice_date": "15/03/2025",
        "total_amount": 11800.00,
        "gst_type": "CGST+SGST"
    }
    print(f"  [A] {fname} — ₹11,800.00")


# ---------------------------------------------------------------------------
# Invoice B — Kodo-style two-column FROM/TO, multiple line items, SAC codes
# ---------------------------------------------------------------------------
def gen_invoice_b():
    fname = "invoice_B1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(W / 2, H - 22 * mm, "KONNECT FINTECH SERVICES LLP")
    c.setFont("Helvetica", 9)
    c.drawCentredString(W / 2, H - 28 * mm, "Unit 501, DLF Cyber City, Gurugram, Haryana - 122 002")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, H - 35 * mm, "INVOICE")
    hline(c, 20 * mm, W - 20 * mm, H - 39 * mm, width=1.5)

    # FROM / TO side by side
    mid = W / 2
    c.setFont("Helvetica-Bold", 9)
    c.drawString(25 * mm, H - 46 * mm, "FROM")
    c.drawString(mid + 5 * mm, H - 46 * mm, "TO")
    hline(c, 20 * mm, W - 20 * mm, H - 48 * mm)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(25 * mm, H - 55 * mm, "KONNECT FINTECH SERVICES LLP")
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, H - 61 * mm, "Unit 501, DLF Cyber City, Gurugram")
    c.drawString(25 * mm, H - 66 * mm, "Haryana - 122 002")
    c.drawString(25 * mm, H - 71 * mm, "GSTIN: 06AABCK8823B1ZQ")
    c.drawString(25 * mm, H - 76 * mm, "SAC: 997159")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(mid + 5 * mm, H - 55 * mm, BUYER_NAME)
    c.setFont("Helvetica", 8)
    c.drawString(mid + 5 * mm, H - 61 * mm, "No. 42, Koramangala 5th Block")
    c.drawString(mid + 5 * mm, H - 66 * mm, "Bengaluru, Karnataka - 560 095")
    c.drawString(mid + 5 * mm, H - 71 * mm, f"GSTIN: {BUYER_GSTIN}")

    hline(c, 20 * mm, W - 20 * mm, H - 80 * mm)

    # Invoice meta row
    c.setFont("Helvetica-Bold", 8)
    c.drawString(25 * mm, H - 87 * mm, "Invoice No.:")
    c.setFont("Helvetica", 8)
    c.drawString(55 * mm, H - 87 * mm, "KFS-2025-0312")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(mid + 5 * mm, H - 87 * mm, "Invoice Date:")
    c.setFont("Helvetica", 8)
    c.drawString(mid + 35 * mm, H - 87 * mm, "01 Mar 2025")

    hline(c, 20 * mm, W - 20 * mm, H - 92 * mm)

    # Line items
    c.setFont("Helvetica-Bold", 8)
    row_y = H - 99 * mm
    col_x = [25 * mm, 85 * mm, 120 * mm, 147 * mm, 170 * mm, W - 25 * mm]
    hdrs = ["Description", "SAC", "Qty", "Rate (₹)", "Tax", "Amount (₹)"]
    for i, h_txt in enumerate(hdrs):
        c.drawString(col_x[i], row_y, h_txt)
    hline(c, 20 * mm, W - 20 * mm, row_y - 3 * mm)

    items = [
        ("Payment Gateway Usage Fee", "997159", "1", "5,000.00", "IGST 18%", "5,000.00"),
        ("API Integration Charges", "998313", "3", "2,000.00", "IGST 18%", "6,000.00"),
        ("Support & Maintenance", "998519", "1", "3,500.00", "IGST 18%", "3,500.00"),
    ]
    c.setFont("Helvetica", 8)
    row_y -= 9 * mm
    for item in items:
        for i, val in enumerate(item):
            c.drawString(col_x[i], row_y, val)
        row_y -= 7 * mm

    hline(c, 20 * mm, W - 20 * mm, row_y - 1 * mm)

    # Totals
    ty = row_y - 9 * mm
    totals = [
        ("Subtotal", "14,500.00"),
        ("IGST @ 18%", "2,610.00"),
        ("Total", "17,110.00"),
    ]
    for label, val in totals:
        c.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 9)
        c.drawRightString(W - 50 * mm, ty, label + ":")
        c.drawRightString(W - 25 * mm, ty, val)
        ty -= 7 * mm

    hline(c, 20 * mm, W - 20 * mm, ty + 2 * mm)
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, ty - 8 * mm, "Place of Supply: Karnataka (29)")
    c.drawString(25 * mm, ty - 15 * mm, "Amount in words: Seventeen Thousand One Hundred Ten Rupees Only")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "KONNECT FINTECH SERVICES LLP",
        "vendor_gstin": "06AABCK8823B1ZQ",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "KFS-2025-0312",
        "invoice_date": "01 Mar 2025",
        "total_amount": 17110.00,
        "gst_type": "IGST"
    }
    print(f"  [B] {fname} — ₹17,110.00")


# ---------------------------------------------------------------------------
# Invoice C — Standard header, "Customer:" label, CGST+SGST (TN→TN)
# ---------------------------------------------------------------------------
def gen_invoice_c():
    fname = "invoice_C1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)

    styles = getSampleStyleSheet()
    bold = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontName="Helvetica", fontSize=9)
    title_style = ParagraphStyle("title", parent=styles["Normal"], fontName="Helvetica-Bold",
                                  fontSize=16, alignment=TA_CENTER)

    doc = SimpleDocTemplate(fpath, pagesize=A4,
                            leftMargin=25 * mm, rightMargin=25 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    story = []

    story.append(Paragraph("BHARATH CLOUD TECHNOLOGIES PVT. LTD.", title_style))
    story.append(Paragraph(
        "<font size='9'>Plot 22, TIDEL Park, Taramani, Chennai - 600 113, Tamil Nadu<br/>"
        "GSTIN: 33AABFB3312C1Z4 | CIN: U72200TN2018PTC123456</font>",
        ParagraphStyle("sub", parent=styles["Normal"], fontName="Helvetica", fontSize=9, alignment=TA_CENTER)
    ))
    story.append(HRFlowable(width="100%", thickness=1))
    story.append(Spacer(1, 4 * mm))

    meta = [
        ["Tax Invoice No.", "BCT/2025/0089", "Date", "2025-01-20"],
    ]
    meta_tbl = Table(meta, colWidths=[40 * mm, 60 * mm, 25 * mm, 40 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Customer:", bold))
    story.append(Paragraph(BUYER_NAME, bold))
    story.append(Paragraph(BUYER_ADDR, normal))
    story.append(Paragraph(f"GSTIN: {BUYER_GSTIN}", normal))
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5))
    story.append(Spacer(1, 3 * mm))

    items_header = ["#", "Description", "HSN", "Qty", "Unit Rate (₹)", "CGST 9%", "SGST 9%", "Amount (₹)"]
    items_data = [
        ["1", "Cloud Hosting (Basic)", "998315", "1", "4,000.00", "360.00", "360.00", "4,720.00"],
        ["2", "SSL Certificate", "998315", "2", "800.00", "144.00", "144.00", "1,888.00"],
        ["3", "Domain Registration", "998316", "1", "1,200.00", "108.00", "108.00", "1,416.00"],
    ]
    col_w = [8 * mm, 52 * mm, 18 * mm, 12 * mm, 26 * mm, 18 * mm, 18 * mm, 23 * mm]
    tbl = Table([items_header] + items_data, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 4 * mm))

    totals = [
        ["", "", "", "", "Subtotal:", "", "", "8,024.00"],
        ["", "", "", "", "CGST (9%):", "", "", "612.00"],
        ["", "", "", "", "SGST (9%):", "", "", "612.00"],
        ["", "", "", "", "Grand Total:", "", "", "8,024.00"],
    ]
    # recalculate: 4000+800*2+1200 = 7200 subtotal; cgst= 648; sgst=648; total=8496
    totals = [
        ["", "", "", "", "Subtotal:", "", "", "7,200.00"],
        ["", "", "", "", "CGST (9%):", "", "", "648.00"],
        ["", "", "", "", "SGST (9%):", "", "", "648.00"],
        ["", "", "", "", "Grand Total:", "", "", "8,496.00"],
    ]
    tot_tbl = Table(totals, colWidths=col_w)
    tot_tbl.setStyle(TableStyle([
        ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
        ("FONTNAME", (7, -1), (7, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
    ]))
    story.append(tot_tbl)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Amount in words: Eight Thousand Four Hundred Ninety Six Rupees Only",
        ParagraphStyle("words", parent=styles["Normal"], fontName="Helvetica-Oblique", fontSize=8)
    ))

    doc.build(story)

    ground_truth[fname] = {
        "vendor_name": "BHARATH CLOUD TECHNOLOGIES PVT. LTD.",
        "vendor_gstin": "33AABFB3312C1Z4",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "BCT/2025/0089",
        "invoice_date": "2025-01-20",
        "total_amount": 8496.00,
        "gst_type": "CGST+SGST"
    }
    print(f"  [C] {fname} — ₹8,496.00")


# ---------------------------------------------------------------------------
# Invoice D — Multi-page, professional services, TDS, partial payment
# ---------------------------------------------------------------------------
def gen_invoice_d():
    fname = "invoice_D1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    def page1():
        c.setFont("Helvetica-Bold", 13)
        c.drawString(25 * mm, H - 22 * mm, "APEX LEGAL & MANAGEMENT CONSULTANTS LLP")
        c.setFont("Helvetica", 8)
        c.drawString(25 * mm, H - 28 * mm,
                     "B-204, Maker Chambers IV, Nariman Point, Mumbai - 400 021, Maharashtra")
        c.drawString(25 * mm, H - 33 * mm,
                     "GSTIN: 27AABCA7781K1ZJ  |  PAN: AABCA7781K  |  SAC: 998311")
        hline(c, 20 * mm, W - 20 * mm, H - 37 * mm, 1)

        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(W / 2, H - 44 * mm, "TAX INVOICE")
        hline(c, 20 * mm, W - 20 * mm, H - 47 * mm)

        meta = [
            ("Invoice No.", "CA/24-25/118"),
            ("Invoice Date", "28 Feb 2025"),
            ("Due Date", "14 Mar 2025"),
            ("PAN of Recipient", "AAHCE1996R"),
        ]
        y = H - 55 * mm
        for k, v in meta:
            c.setFont("Helvetica-Bold", 8)
            c.drawString(25 * mm, y, k + ":")
            c.setFont("Helvetica", 8)
            c.drawString(70 * mm, y, v)
            y -= 6 * mm

        c.setFont("Helvetica-Bold", 9)
        c.drawString(25 * mm, y - 4 * mm, "Billed To:")
        c.setFont("Helvetica-Bold", 9)
        c.drawString(25 * mm, y - 10 * mm, BUYER_NAME)
        c.setFont("Helvetica", 8)
        c.drawString(25 * mm, y - 16 * mm, BUYER_ADDR)
        c.drawString(25 * mm, y - 22 * mm, f"GSTIN: {BUYER_GSTIN}")
        hline(c, 20 * mm, W - 20 * mm, y - 27 * mm)

        col_x = [25 * mm, 80 * mm, 120 * mm, 147 * mm, W - 25 * mm]
        hdrs = ["Service Description", "SAC", "Hours", "Rate/Hr (₹)", "Amount (₹)"]
        row_y = y - 35 * mm
        c.setFont("Helvetica-Bold", 8)
        for i, h_txt in enumerate(hdrs):
            c.drawString(col_x[i], row_y, h_txt)
        hline(c, 20 * mm, W - 20 * mm, row_y - 3 * mm)

        items = [
            ("Statutory Audit — Q3 FY 2024-25", "998311", "40", "3,000.00", "1,20,000.00"),
            ("Tax Advisory & Compliance", "998312", "15", "3,500.00", "52,500.00"),
            ("MCA Filing Support", "998313", "8", "2,000.00", "16,000.00"),
        ]
        c.setFont("Helvetica", 8)
        row_y -= 9 * mm
        for item in items:
            for i, val in enumerate(item):
                c.drawString(col_x[i], row_y, val)
            row_y -= 7 * mm

        hline(c, 20 * mm, W - 20 * mm, row_y - 2 * mm)

        ty = row_y - 10 * mm
        totals = [
            ("Subtotal", "1,88,500.00"),
            ("IGST @ 18%", "33,930.00"),
            ("Gross Total", "2,22,430.00"),
            ("Less: TDS @ 10% (Sec 194J)", "18,850.00"),
            ("Less: Advance Paid", "50,000.00"),
            ("Balance Due", "1,53,580.00"),
        ]
        for label, val in totals:
            bold_labels = ("Gross Total", "Balance Due")
            c.setFont("Helvetica-Bold" if label in bold_labels else "Helvetica", 8)
            c.drawRightString(W - 55 * mm, ty, label + ":")
            c.drawRightString(W - 25 * mm, ty, val)
            ty -= 6 * mm

        hline(c, 20 * mm, W - 20 * mm, ty + 2 * mm)

        c.setFont("Helvetica", 7)
        c.drawString(25 * mm, ty - 8 * mm,
                     "Note: TDS deductible u/s 194J of the Income Tax Act, 1961. Please deduct TDS before payment.")
        c.drawString(25 * mm, ty - 14 * mm,
                     "Bank: ICICI Bank  |  A/C: 012345678901  |  IFSC: ICIC0000123  |  Branch: Nariman Point")
        c.setFont("Helvetica-BoldOblique", 8)
        c.drawRightString(W - 25 * mm, ty - 20 * mm, "Partner, APEX LMC LLP")

        c.drawString(W / 2 - 10, 12 * mm, "Page 1 of 1")

    page1()
    c.save()

    ground_truth[fname] = {
        "vendor_name": "APEX LEGAL & MANAGEMENT CONSULTANTS LLP",
        "vendor_gstin": "27AABCA7781K1ZJ",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "CA/24-25/118",
        "invoice_date": "28 Feb 2025",
        "total_amount": 222430.00,
        "gst_type": "IGST"
    }
    print(f"  [D] {fname} — ₹2,22,430.00 (gross); balance ₹1,53,580")


# ---------------------------------------------------------------------------
# Invoice E — Minimal, Karnataka vendor, IGST
# ---------------------------------------------------------------------------
def gen_invoice_e():
    fname = "invoice_E1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40 * mm, H - 30 * mm, "PRAKASH PRINTING WORKS")
    c.setFont("Helvetica", 9)
    c.drawString(40 * mm, H - 37 * mm, "No. 8, Gandhi Bazaar, Bengaluru - 560 004")
    c.drawString(40 * mm, H - 43 * mm, "GSTIN: 29AABPP5577G1Z3")

    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(W - 30 * mm, H - 30 * mm, "Invoice")

    c.setFont("Helvetica", 9)
    c.drawRightString(W - 30 * mm, H - 37 * mm, "No: PPW-1092")
    c.drawRightString(W - 30 * mm, H - 43 * mm, "Date: 05-02-2025")

    hline(c, 30 * mm, W - 30 * mm, H - 48 * mm)

    c.setFont("Helvetica", 9)
    c.drawString(40 * mm, H - 55 * mm, "To:")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(50 * mm, H - 55 * mm, BUYER_NAME)
    c.setFont("Helvetica", 9)
    c.drawString(50 * mm, H - 61 * mm, "Bengaluru, Karnataka")
    c.drawString(50 * mm, H - 67 * mm, f"GSTIN: {BUYER_GSTIN}")

    hline(c, 30 * mm, W - 30 * mm, H - 72 * mm)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(40 * mm, H - 80 * mm, "Particulars")
    c.drawRightString(W - 30 * mm, H - 80 * mm, "Amount (₹)")
    hline(c, 30 * mm, W - 30 * mm, H - 83 * mm)

    c.setFont("Helvetica", 9)
    c.drawString(40 * mm, H - 91 * mm, "Business Card Printing (500 pcs)")
    c.drawRightString(W - 30 * mm, H - 91 * mm, "500.00")

    hline(c, 30 * mm, W - 30 * mm, H - 96 * mm)

    ty = H - 104 * mm
    c.drawRightString(W - 60 * mm, ty, "IGST @ 18%:")
    c.drawRightString(W - 30 * mm, ty, "90.00")
    ty -= 7 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(W - 60 * mm, ty, "Total:")
    c.drawRightString(W - 30 * mm, ty, "590.00")

    c.setFont("Helvetica", 8)
    c.drawString(40 * mm, ty - 12 * mm, "Payment: Cash / UPI - 9876543210")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "PRAKASH PRINTING WORKS",
        "vendor_gstin": "29AABPP5577G1Z3",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "PPW-1092",
        "invoice_date": "05-02-2025",
        "total_amount": 590.00,
        "gst_type": "IGST"
    }
    print(f"  [E] {fname} — ₹590.00")


# ---------------------------------------------------------------------------
# Invoice F — E-commerce/SaaS format, two-column
# ---------------------------------------------------------------------------
def gen_invoice_f():
    fname = "invoice_F1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    # Header bar
    c.setFillColor(colors.HexColor("#1a1a2e"))
    c.rect(0, H - 40 * mm, W, 40 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(25 * mm, H - 20 * mm, "STACKPAY TECHNOLOGIES PVT. LTD.")
    c.setFont("Helvetica", 9)
    c.drawString(25 * mm, H - 28 * mm, "15th Floor, Raheja Towers, MG Road, Bengaluru - 560 001")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(W - 25 * mm, H - 22 * mm, "INVOICE")
    c.setFillColor(colors.black)

    # FROM / TO
    mid = W / 2
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.grey)
    c.drawString(25 * mm, H - 50 * mm, "BILLED FROM")
    c.drawString(mid + 5 * mm, H - 50 * mm, "BILLED TO")
    c.setFillColor(colors.black)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(25 * mm, H - 57 * mm, "STACKPAY TECHNOLOGIES PVT. LTD.")
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, H - 63 * mm, "GSTIN: 29AABCS9922M1ZK")
    c.drawString(25 * mm, H - 69 * mm, "PAN: AABCS9922M")

    c.setFont("Helvetica-Bold", 9)
    c.drawString(mid + 5 * mm, H - 57 * mm, BUYER_NAME)
    c.setFont("Helvetica", 8)
    c.drawString(mid + 5 * mm, H - 63 * mm, f"GSTIN: {BUYER_GSTIN}")
    c.drawString(mid + 5 * mm, H - 69 * mm, "Bengaluru, Karnataka")

    hline(c, 20 * mm, W - 20 * mm, H - 74 * mm)

    # Invoice ref
    c.setFont("Helvetica-Bold", 8)
    c.drawString(25 * mm, H - 81 * mm, "Invoice Number:")
    c.setFont("Helvetica", 8)
    c.drawString(70 * mm, H - 81 * mm, "SPT/MAR25/00891")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(mid + 5 * mm, H - 81 * mm, "Invoice Date:")
    c.setFont("Helvetica", 8)
    c.drawString(mid + 35 * mm, H - 81 * mm, "31/03/2025")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(25 * mm, H - 88 * mm, "Place of Supply:")
    c.setFont("Helvetica", 8)
    c.drawString(70 * mm, H - 88 * mm, "Karnataka (29)")

    hline(c, 20 * mm, W - 20 * mm, H - 93 * mm)

    # Items
    col_x = [25 * mm, 100 * mm, 140 * mm, 168 * mm, W - 25 * mm]
    hdrs = ["Description", "SAC", "Rate (₹)", "IGST 18%", "Total (₹)"]
    row_y = H - 101 * mm
    c.setFont("Helvetica-Bold", 8)
    for i, h in enumerate(hdrs):
        c.drawString(col_x[i], row_y, h)
    hline(c, 20 * mm, W - 20 * mm, row_y - 3 * mm)

    items = [
        ("Platform Transaction Fee — Feb 2025", "997159", "8,200.00", "1,476.00", "9,676.00"),
        ("Chargeback Handling Fee", "997159", "1,500.00", "270.00", "1,770.00"),
    ]
    c.setFont("Helvetica", 8)
    row_y -= 9 * mm
    for item in items:
        for i, val in enumerate(item):
            c.drawString(col_x[i], row_y, val)
        row_y -= 8 * mm

    hline(c, 20 * mm, W - 20 * mm, row_y - 2 * mm)

    ty = row_y - 10 * mm
    for label, val in [("Subtotal", "9,700.00"), ("IGST (18%)", "1,746.00"), ("Total", "11,446.00")]:
        c.setFont("Helvetica-Bold" if label == "Total" else "Helvetica", 9)
        c.drawRightString(W - 50 * mm, ty, label + ":")
        c.drawRightString(W - 25 * mm, ty, val)
        ty -= 7 * mm

    hline(c, 20 * mm, W - 20 * mm, ty + 2 * mm)
    c.setFont("Helvetica", 7)
    c.drawString(25 * mm, ty - 8 * mm,
                 "This is a computer generated invoice. No signature required.")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "STACKPAY TECHNOLOGIES PVT. LTD.",
        "vendor_gstin": "29AABCS9922M1ZK",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "SPT/MAR25/00891",
        "invoice_date": "31/03/2025",
        "total_amount": 11446.00,
        "gst_type": "IGST"
    }
    print(f"  [F] {fname} — ₹11,446.00")


# ---------------------------------------------------------------------------
# Invoice G — Government/PSU dense format
# ---------------------------------------------------------------------------
def gen_invoice_g():
    fname = "invoice_G1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    # Outer border
    c.setLineWidth(1.5)
    c.rect(15 * mm, 15 * mm, W - 30 * mm, H - 30 * mm)

    # Letterhead
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, H - 28 * mm, "BHARAT HEAVY ELECTRICALS LIMITED (BHEL)")
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2, H - 34 * mm,
                        "Power Sector - Eastern Region, Salt Lake City, Kolkata - 700 091, West Bengal")
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, H - 39 * mm, "GSTIN: 19AAACB0472F1ZC   |   CIN: L40100DL1964GOI004281")
    hline(c, 15 * mm, W - 15 * mm, H - 43 * mm, 1)

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, H - 50 * mm, "TAX INVOICE")
    hline(c, 15 * mm, W - 15 * mm, H - 53 * mm)

    # Two-column meta
    left_meta = [
        ("Invoice No.", "BHEL/PSE/2025/0341"),
        ("Invoice Date", "10/02/2025"),
        ("Contract Ref.", "BHEL/MUM/ENT/2024-25/011"),
        ("Order Date", "01/04/2024"),
    ]
    right_meta = [
        ("Place of Supply", "West Bengal (19)"),
        ("State of Supplier", "West Bengal (19)"),
        ("Reverse Charge", "No"),
        ("Currency", "INR"),
    ]
    y = H - 62 * mm
    for (lk, lv), (rk, rv) in zip(left_meta, right_meta):
        c.setFont("Helvetica-Bold", 8)
        c.drawString(18 * mm, y, lk + ":")
        c.setFont("Helvetica", 8)
        c.drawString(55 * mm, y, lv)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(W / 2 + 3 * mm, y, rk + ":")
        c.setFont("Helvetica", 8)
        c.drawString(W / 2 + 40 * mm, y, rv)
        y -= 6 * mm

    hline(c, 15 * mm, W - 15 * mm, y - 1 * mm)

    # Buyer
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(18 * mm, y, "Consignee / Bill To:")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(18 * mm, y, BUYER_NAME)
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    c.drawString(18 * mm, y, BUYER_ADDR)
    y -= 5 * mm
    c.drawString(18 * mm, y, f"GSTIN: {BUYER_GSTIN}   |   State: Karnataka (29)")
    hline(c, 15 * mm, W - 15 * mm, y - 3 * mm)

    # Items
    col_x = [18 * mm, 25 * mm, 85 * mm, 115 * mm, 140 * mm, 162 * mm, W - 15 * mm]
    hdrs = ["Sl.", "Item Description", "HSN", "Qty", "Unit Price", "IGST 12%", "Total (₹)"]
    row_y = y - 11 * mm
    c.setFont("Helvetica-Bold", 7)
    for i, h in enumerate(hdrs):
        c.drawString(col_x[i], row_y, h)
    hline(c, 15 * mm, W - 15 * mm, row_y - 3 * mm)

    items = [
        ("1", "Electrical Control Panel", "8537", "2", "35,000.00", "8,400.00", "78,400.00"),
        ("2", "Copper Bus Bar (per metre)", "7407", "50", "850.00", "5,100.00", "47,600.00"),
    ]
    c.setFont("Helvetica", 7)
    row_y -= 8 * mm
    for item in items:
        for i, val in enumerate(item):
            c.drawString(col_x[i], row_y, val)
        row_y -= 7 * mm

    hline(c, 15 * mm, W - 15 * mm, row_y - 1 * mm)

    ty = row_y - 9 * mm
    for label, val in [
        ("Subtotal", "1,18,000.00"),
        ("IGST @ 12%", "14,160.00"),
        ("Freight & Insurance", "2,500.00"),
        ("Grand Total", "1,34,660.00"),
    ]:
        c.setFont("Helvetica-Bold" if "Total" in label or "Grand" in label else "Helvetica", 8)
        c.drawRightString(W - 35 * mm, ty, label + ":")
        c.drawRightString(W - 17 * mm, ty, val)
        ty -= 6 * mm

    hline(c, 15 * mm, W - 15 * mm, ty + 2 * mm)
    c.setFont("Helvetica", 7)
    c.drawString(18 * mm, ty - 7 * mm,
                 "E & OE. Subject to Kolkata jurisdiction. Goods once sold will not be taken back.")
    c.drawString(18 * mm, ty - 13 * mm,
                 "Bank: State Bank of India  |  A/C: 39870123456  |  IFSC: SBIN0000123  |  Kolkata Main Branch")
    c.setFont("Helvetica-BoldOblique", 8)
    c.drawRightString(W - 17 * mm, ty - 20 * mm, "General Manager (Finance)")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "BHARAT HEAVY ELECTRICALS LIMITED (BHEL)",
        "vendor_gstin": "19AAACB0472F1ZC",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "BHEL/PSE/2025/0341",
        "invoice_date": "10/02/2025",
        "total_amount": 134660.00,
        "gst_type": "IGST"
    }
    print(f"  [G] {fname} — ₹1,34,660.00")


# ---------------------------------------------------------------------------
# Invoice H — Handwritten-style noise, Courier font, abbreviations
# ---------------------------------------------------------------------------
def gen_invoice_h():
    fname = "invoice_H1.pdf"
    fpath = os.path.join(OUTPUT_DIR, fname)
    c = canvas.Canvas(fpath, pagesize=A4)

    # Use Courier to simulate typewriter/OCR noise
    c.setFont("Courier-Bold", 12)
    c.drawString(25 * mm, H - 25 * mm, "METRO OFFICE SUPPLIES Pvt. Ltd.")
    c.setFont("Courier", 8)
    c.drawString(25 * mm, H - 32 * mm, "Shop No. 14, Ratan Lal Mkt., Chandni Chowk, Delhi - 110 006")
    c.drawString(25 * mm, H - 38 * mm, "GSTIN : 07AABCM5512H1Z8    Ph : 011-23456780")

    c.setFont("Courier-Bold", 11)
    c.drawRightString(W - 25 * mm, H - 25 * mm, "TAX INVOICE")
    c.setFont("Courier", 9)
    c.drawRightString(W - 25 * mm, H - 32 * mm, "Inv. No. : MOS/25/0087")
    c.drawRightString(W - 25 * mm, H - 38 * mm, "Dt.      : 12-Jan-2025")

    hline(c, 20 * mm, W - 20 * mm, H - 43 * mm)

    c.setFont("Courier-Bold", 9)
    c.drawString(25 * mm, H - 50 * mm, "Buyer :")
    c.setFont("Courier", 9)
    c.drawString(45 * mm, H - 50 * mm, "Entvin Labs Pvt. Ltd.")
    c.drawString(45 * mm, H - 56 * mm, "Koramangala, Bengaluru - 560 095")
    c.drawString(45 * mm, H - 62 * mm, f"GSTIN : {BUYER_GSTIN}")

    hline(c, 20 * mm, W - 20 * mm, H - 67 * mm)

    # Items — Courier, slightly off spacing
    col_x = [25 * mm, 85 * mm, 120 * mm, 148 * mm, W - 25 * mm]
    row_y = H - 75 * mm
    c.setFont("Courier-Bold", 8)
    for i, h in enumerate(["Particulars", "HSN", "Qty.", "Rate Rs.", "Amt. Rs."]):
        c.drawString(col_x[i], row_y, h)
    hline(c, 20 * mm, W - 20 * mm, row_y - 3 * mm)

    items = [
        ("A4 Paper Ream (500 Sheets)", "4802", "10", "350.00", "3,500.00"),
        ("Ball Pen Box (20 Pcs)", "9608", "5", "120.00", "600.00"),
        ("Stapler & Pins Set", "8305", "3", "180.00", "540.00"),
        ("File Folders (Pack of 10)", "4820", "4", "250.00", "1,000.00"),
    ]
    c.setFont("Courier", 8)
    row_y -= 9 * mm
    for item in items:
        for i, val in enumerate(item):
            c.drawString(col_x[i], row_y, val)
        row_y -= 7 * mm

    hline(c, 20 * mm, W - 20 * mm, row_y - 2 * mm)

    ty = row_y - 9 * mm
    for label, val in [
        ("Sub-Total", "5,640.00"),
        ("IGST @ 12%", "676.80"),
        ("Rounding Off", "+0.20"),
        ("Net Payable", "6,317.00"),
    ]:
        c.setFont("Courier-Bold" if "Net" in label else "Courier", 8)
        c.drawRightString(W - 50 * mm, ty, label + " :")
        c.drawRightString(W - 25 * mm, ty, val)
        ty -= 6 * mm

    hline(c, 20 * mm, W - 20 * mm, ty + 2 * mm)
    c.setFont("Courier", 7)
    c.drawString(25 * mm, ty - 8 * mm, "Recd. goods in good cond.  Stamp & Sign : ____________")
    c.drawString(25 * mm, ty - 15 * mm, "Subject to Delhi Jurisdiction. E. & O.E.")

    c.save()

    ground_truth[fname] = {
        "vendor_name": "METRO OFFICE SUPPLIES Pvt. Ltd.",
        "vendor_gstin": "07AABCM5512H1Z8",
        "buyer_gstin": BUYER_GSTIN,
        "invoice_number": "MOS/25/0087",
        "invoice_date": "12-Jan-2025",
        "total_amount": 6317.00,
        "gst_type": "IGST"
    }
    print(f"  [H] {fname} — ₹6,317.00")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Generating test invoices...")
    gen_invoice_a()
    gen_invoice_b()
    gen_invoice_c()
    gen_invoice_d()
    gen_invoice_e()
    gen_invoice_f()
    gen_invoice_g()
    gen_invoice_h()

    gt_path = os.path.join(OUTPUT_DIR, "ground_truth.json")
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Ground truth saved to {gt_path}")
    print("\nFiles generated:")
    for fn in sorted(os.listdir(OUTPUT_DIR)):
        fp = os.path.join(OUTPUT_DIR, fn)
        size_kb = os.path.getsize(fp) / 1024
        print(f"  {fn:30s}  {size_kb:6.1f} KB")
