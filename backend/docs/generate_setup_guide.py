"""
Generate Vithana Integration Setup Guide PDF using reportlab.
Run: python3 docs/generate_setup_guide.py
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, ListFlowable, ListItem,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus.flowables import KeepTogether

OUTPUT = "docs/Vithana_Integration_Setup_Guide.pdf"

# ── Palette ──────────────────────────────────────────────────────────────────
BRAND       = colors.HexColor("#1A56DB")   # Vithana blue
BRAND_LIGHT = colors.HexColor("#EBF5FF")
ACCENT      = colors.HexColor("#0E9F6E")   # green (success)
WARN        = colors.HexColor("#E3A008")   # amber
DANGER      = colors.HexColor("#E02424")   # red
GRAY        = colors.HexColor("#6B7280")
LIGHT_GRAY  = colors.HexColor("#F9FAFB")
BORDER      = colors.HexColor("#D1D5DB")
DARK        = colors.HexColor("#111827")
CODE_BG     = colors.HexColor("#F3F4F6")
CODE_FG     = colors.HexColor("#1F2937")

W, H = A4

def styles():
    base = getSampleStyleSheet()
    s = {}

    s["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"],
        fontSize=28, textColor=colors.white, leading=36,
        spaceAfter=6, alignment=TA_CENTER,
    )
    s["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=base["Normal"],
        fontSize=13, textColor=colors.HexColor("#BFD7FF"), leading=18,
        spaceAfter=4, alignment=TA_CENTER,
    )
    s["cover_meta"] = ParagraphStyle(
        "cover_meta", parent=base["Normal"],
        fontSize=10, textColor=colors.HexColor("#93C5FD"), leading=14,
        alignment=TA_CENTER,
    )
    s["h1"] = ParagraphStyle(
        "h1", parent=base["Heading1"],
        fontSize=18, textColor=BRAND, leading=24,
        spaceBefore=14, spaceAfter=6, borderPad=0,
    )
    s["h2"] = ParagraphStyle(
        "h2", parent=base["Heading2"],
        fontSize=13, textColor=DARK, leading=18,
        spaceBefore=10, spaceAfter=4,
    )
    s["h3"] = ParagraphStyle(
        "h3", parent=base["Heading3"],
        fontSize=11, textColor=BRAND, leading=16,
        spaceBefore=8, spaceAfter=3,
    )
    s["body"] = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=10, textColor=DARK, leading=15,
        spaceAfter=5, alignment=TA_JUSTIFY,
    )
    s["note"] = ParagraphStyle(
        "note", parent=base["Normal"],
        fontSize=9.5, textColor=colors.HexColor("#374151"), leading=14,
        leftIndent=12, spaceAfter=4,
    )
    s["code"] = ParagraphStyle(
        "code", parent=base["Code"],
        fontSize=8.5, textColor=CODE_FG, leading=13,
        fontName="Courier", backColor=CODE_BG,
        leftIndent=10, rightIndent=10,
        spaceBefore=4, spaceAfter=4,
        borderPad=6,
    )
    s["step"] = ParagraphStyle(
        "step", parent=base["Normal"],
        fontSize=10, textColor=DARK, leading=15,
        leftIndent=18, spaceAfter=4,
    )
    s["toc_item"] = ParagraphStyle(
        "toc_item", parent=base["Normal"],
        fontSize=11, textColor=BRAND, leading=18,
        leftIndent=12,
    )
    s["label"] = ParagraphStyle(
        "label", parent=base["Normal"],
        fontSize=9, textColor=GRAY, leading=13, spaceAfter=2,
    )
    s["table_h"] = ParagraphStyle(
        "table_h", parent=base["Normal"],
        fontSize=9.5, textColor=colors.white, leading=13,
        fontName="Helvetica-Bold",
    )
    s["table_c"] = ParagraphStyle(
        "table_c", parent=base["Normal"],
        fontSize=9, textColor=DARK, leading=13,
    )
    return s


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6, spaceBefore=4)


def badge(text, bg=BRAND_LIGHT, fg=BRAND):
    return Paragraph(
        f'<font color="#{fg.hexval()[1:]}"><b>{text}</b></font>',
        ParagraphStyle("badge", fontSize=8.5, textColor=fg, backColor=bg, leading=12,
                       borderPad=3, leftIndent=4, rightIndent=4),
    )


def info_box(s, title, body_text, color=BRAND_LIGHT, border=BRAND):
    data = [[
        Paragraph(f"<b>{title}</b>", ParagraphStyle(
            "ib_t", fontSize=9.5, textColor=border, leading=13, fontName="Helvetica-Bold")),
        Paragraph(body_text, ParagraphStyle(
            "ib_b", fontSize=9.5, textColor=DARK, leading=13)),
    ]]
    t = Table(data, colWidths=[3.5*cm, 13*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("BOX", (0,0), (-1,-1), 0.8, border),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    return t


def config_table(s, rows):
    """rows = [("Key", "Description", "Example"), ...]"""
    header = [
        Paragraph("Config Key", s["table_h"]),
        Paragraph("Description", s["table_h"]),
        Paragraph("Example / Notes", s["table_h"]),
    ]
    data = [header]
    for key, desc, example in rows:
        data.append([
            Paragraph(f'<font name="Courier" size="8.5">{key}</font>', s["table_c"]),
            Paragraph(desc, s["table_c"]),
            Paragraph(f'<font color="#6B7280">{example}</font>', s["table_c"]),
        ])
    t = Table(data, colWidths=[4.5*cm, 7*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND),
        ("BACKGROUND", (0,1), (-1,-1), colors.white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 7),
        ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    return t


def step_list(s, items):
    """Numbered steps."""
    elems = []
    for i, item in enumerate(items, 1):
        elems.append(Paragraph(f"<b>{i}.</b>  {item}", s["step"]))
    return elems


def bullet_list(s, items):
    elems = []
    for item in items:
        elems.append(Paragraph(f"• &nbsp; {item}", s["step"]))
    return elems


# ── Cover page ────────────────────────────────────────────────────────────────
def cover_page(s):
    # Solid blue block simulated via table
    cover_data = [[
        Paragraph("Vithana Accounting Automation", s["cover_title"]),
    ]]
    cover_data += [[Paragraph("Integration Setup Guide", s["cover_sub"])]]
    cover_data += [[Spacer(1, 0.3*cm)]]
    cover_data += [[Paragraph(
        "Gmail OAuth &amp; Mail Ingestion · Zoho Books · QuickBooks Online",
        s["cover_sub"])]]
    cover_data += [[Spacer(1, 1*cm)]]
    cover_data += [[Paragraph("Version 1.0 · April 2026 · Internal Use Only", s["cover_meta"])]]

    t = Table([[row[0]] for row in cover_data], colWidths=[16.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), BRAND),
        ("LEFTPADDING", (0,0), (-1,-1), 24),
        ("RIGHTPADDING", (0,0), (-1,-1), 24),
        ("TOPPADDING", (0,0), (0,0), 60),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 60),
        ("TOPPADDING", (0,1), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-2), 6),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    return [t, PageBreak()]


# ── TOC ───────────────────────────────────────────────────────────────────────
def toc_page(s):
    elems = [
        Paragraph("Table of Contents", s["h1"]),
        hr(),
        Spacer(1, 0.4*cm),
    ]
    sections = [
        ("1", "Gmail OAuth Setup", "Google Cloud Console, OAuth consent, credentials"),
        ("2", "Gmail Mail Ingestion (Pull)", "Authorise mailbox, configure ingest settings"),
        ("3", "Zoho Books Integration", "OAuth app, refresh token, platform config"),
        ("4", "QuickBooks Online Integration", "Intuit developer app, OAuth 2.0, realm ID"),
        ("A", "Appendix: Troubleshooting", "Common errors and fixes"),
    ]
    rows = []
    for num, title, desc in sections:
        rows.append([
            Paragraph(f"<b>{num}</b>", ParagraphStyle("tn", fontSize=13, textColor=BRAND,
                                                        fontName="Helvetica-Bold", leading=18)),
            Paragraph(f"<b>{title}</b><br/><font size='9' color='#6B7280'>{desc}</font>",
                      ParagraphStyle("tt", fontSize=11, textColor=DARK, leading=18)),
        ])
    t = Table(rows, colWidths=[1.5*cm, 14.5*cm])
    t.setStyle(TableStyle([
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LINEBELOW", (0,0), (-1,-1), 0.4, BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    elems.append(t)
    elems.append(PageBreak())
    return elems


# ── Section 1: Gmail OAuth Setup ─────────────────────────────────────────────
def section_gmail_oauth(s):
    elems = [
        Paragraph("1. Gmail OAuth Setup", s["h1"]),
        hr(),
        Paragraph(
            "Vithana uses Google OAuth 2.0 to securely authorise access to Gmail inboxes. "
            "Each company tenant has its own OAuth client credentials stored in the database — "
            "no shared credentials are used.",
            s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("1.1  Create a Google Cloud Project", s["h2"]),
        *step_list(s, [
            'Go to <b>console.cloud.google.com</b> and sign in with a Google account that owns or manages the organisation.',
            'Click the project selector at the top → <b>New Project</b>.',
            'Name it (e.g., <i>vithana-prod</i>) and click <b>Create</b>.',
            'Ensure the new project is selected in the top bar before continuing.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("1.2  Enable the Gmail API", s["h2"]),
        *step_list(s, [
            'In the left menu navigate to <b>APIs &amp; Services → Library</b>.',
            'Search for <b>Gmail API</b> and click it.',
            'Click <b>Enable</b>. Wait for the API to activate.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("1.3  Configure the OAuth Consent Screen", s["h2"]),
        *step_list(s, [
            'Navigate to <b>APIs &amp; Services → OAuth consent screen</b>.',
            'Select <b>Internal</b> if users are within your Google Workspace org, or <b>External</b> for personal Gmail accounts.',
            'Fill in <b>App name</b> (e.g., <i>Vithana Accounting</i>), <b>User support email</b>, and <b>Developer contact email</b>.',
            'Under <b>Scopes</b> add: <font name="Courier" size="9">https://www.googleapis.com/auth/gmail.readonly</font>',
            'If <b>External</b>: under <b>Test users</b> add every Gmail address that will authorise during testing.',
            'Save and continue until the consent screen is published.',
        ]),
        info_box(s, "⚠ Important",
                 "Until your app passes Google verification, only addresses listed as <b>Test users</b> "
                 "can authorise. Add all developer and tester emails now.",
                 color=colors.HexColor("#FFFBEB"), border=WARN),
        Spacer(1, 0.3*cm),

        Paragraph("1.4  Create OAuth 2.0 Credentials", s["h2"]),
        *step_list(s, [
            'Navigate to <b>APIs &amp; Services → Credentials</b>.',
            'Click <b>+ Create Credentials → OAuth client ID</b>.',
            'Application type: <b>Web application</b>.',
            'Add the authorised redirect URI: <font name="Courier" size="9">http://&lt;your-backend-host&gt;/api/auth/google/callback</font>',
            'Click <b>Create</b>. Download the JSON — it contains <b>client_id</b> and <b>client_secret</b>.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("1.5  Register Credentials in Vithana Admin", s["h2"]),
        *step_list(s, [
            'Log in to the Vithana Admin Dashboard.',
            'Navigate to <b>Companies → &lt;Company Name&gt; → OAuth Settings</b>.',
            'Enter the <b>Client ID</b>, <b>Client Secret</b>, and <b>Redirect URI</b>.',
            'Click <b>Save OAuth Config</b>.',
            'The redirect URI must exactly match what you registered in Google Cloud.',
        ]),
        config_table(s, [
            ("client_id",     "OAuth 2.0 Client ID from Google Cloud",   "1234567890-abc.apps.googleusercontent.com"),
            ("client_secret", "OAuth 2.0 Client Secret",                 "GOCSPX-xxxxxxxxxxxx"),
            ("redirect_uri",  "Must match Google Cloud exactly",         "https://api.vithana.com/api/auth/google/callback"),
        ]),
        Spacer(1, 0.3*cm),
        PageBreak(),
    ]
    return elems


# ── Section 2: Gmail Ingest ───────────────────────────────────────────────────
def section_gmail_ingest(s):
    elems = [
        Paragraph("2. Gmail Mail Ingestion (Pull)", s["h1"]),
        hr(),
        Paragraph(
            "Once OAuth credentials are configured, each user can authorise their Gmail mailbox. "
            "Vithana then pulls emails matching configured rules and extracts invoice attachments.",
            s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("2.1  User Authorises Gmail Access", s["h2"]),
        *step_list(s, [
            'User logs in to the Vithana web app.',
            'Navigate to <b>Settings → Email Sources → Connect Gmail</b>.',
            'Click <b>Authorise Gmail</b>. A Google consent screen opens.',
            'Grant <b>Read mail</b> permission.',
            'On success the status shows <b>Connected</b> with the authorised email address.',
        ]),
        info_box(s, "ℹ Note",
                 "Vithana requests <b>read-only</b> Gmail access. It never sends, deletes, or modifies emails.",
                 color=BRAND_LIGHT, border=BRAND),
        Spacer(1, 0.3*cm),

        Paragraph("2.2  Configure Ingest Rules", s["h2"]),
        Paragraph(
            "Rules control which emails are picked up. Navigate to <b>Settings → Rules</b> and create rules:",
            s["body"]),
        *bullet_list(s, [
            "<b>Sender filter</b> — e.g., <font name='Courier' size='9'>invoices@vendor.com</font>",
            "<b>Subject keyword</b> — e.g., <font name='Courier' size='9'>invoice</font>, <font name='Courier' size='9'>bill</font>",
            "<b>Attachment type</b> — PDF (default), PNG, JPEG",
            "<b>Label/folder</b> — restrict to a specific Gmail label",
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("2.3  Trigger a Manual Sync", s["h2"]),
        *step_list(s, [
            'Navigate to <b>Dashboard → Email Sources</b>.',
            'Click <b>Sync Now</b> on the Gmail source.',
            'Vithana fetches matching emails since the last sync timestamp.',
            'Extracted attachments appear in <b>Invoices → Pending</b>.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("2.4  Automated Polling", s["h2"]),
        Paragraph(
            "The backend scheduler polls Gmail automatically at the interval set in <b>Settings → "
            "System Config → GMAIL_POLL_INTERVAL_MINUTES</b> (default: 30 minutes). "
            "No manual sync is needed in production.",
            s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("2.5  Environment Variables", s["h2"]),
        config_table(s, [
            ("GOOGLE_REDIRECT_URI",           "Callback URL for OAuth flow",           "https://api.vithana.com/api/auth/google/callback"),
            ("GMAIL_POLL_INTERVAL_MINUTES",   "Auto-sync frequency (minutes)",         "30"),
            ("ATTACHMENT_DIR",                "Local path to store downloaded files",  "/app/attachments"),
        ]),
        Spacer(1, 0.3*cm),
        PageBreak(),
    ]
    return elems


# ── Section 3: Zoho Books ─────────────────────────────────────────────────────
def section_zoho(s):
    elems = [
        Paragraph("3. Zoho Books Integration", s["h1"]),
        hr(),
        Paragraph(
            "Vithana pushes approved invoice drafts to Zoho Books as Bills. "
            "Authentication uses Zoho OAuth 2.0 with a long-lived <b>refresh token</b>.",
            s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("3.1  Create a Zoho OAuth App", s["h2"]),
        *step_list(s, [
            'Go to <b>api-console.zoho.in</b> (India region) or <b>api-console.zoho.com</b> (Global).',
            'Click <b>Add Client → Server-based Applications</b>.',
            'Set <b>Redirect URI</b> to any valid HTTPS URL (e.g., <font name="Courier" size="9">https://api.vithana.com/oauth/zoho/callback</font>). '
            'This URI is only used once during the grant-token exchange.',
            'Note the <b>Client ID</b> and <b>Client Secret</b>.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("3.2  Generate a Grant Token (One-Time)", s["h2"]),
        Paragraph("Open this URL in your browser while logged into Zoho Books:", s["body"]),
        Paragraph(
            "https://accounts.zoho.in/oauth/v2/auth?scope=ZohoBooks.fullaccess.all"
            "&amp;client_id=YOUR_CLIENT_ID&amp;response_type=code"
            "&amp;redirect_uri=YOUR_REDIRECT_URI&amp;access_type=offline",
            s["code"]),
        *step_list(s, [
            'Approve the consent screen.',
            'You are redirected to your redirect URI with <font name="Courier" size="9">?code=1000.xxxxx</font> in the URL.',
            'Copy that <b>code</b> value — it expires in 60 seconds.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("3.3  Exchange Grant Token for Refresh Token", s["h2"]),
        Paragraph("Run the following curl command immediately after copying the grant code:", s["body"]),
        Paragraph(
            "curl -X POST https://accounts.zoho.in/oauth/v2/token \\\n"
            "  -d \"code=1000.YOUR_GRANT_CODE\" \\\n"
            "  -d \"client_id=YOUR_CLIENT_ID\" \\\n"
            "  -d \"client_secret=YOUR_CLIENT_SECRET\" \\\n"
            "  -d \"redirect_uri=YOUR_REDIRECT_URI\" \\\n"
            "  -d \"grant_type=authorization_code\"",
            s["code"]),
        Paragraph("The response contains <b>refresh_token</b> — save it permanently. It does not expire unless revoked.", s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("3.4  Get Your Organization ID", s["h2"]),
        *step_list(s, [
            'Log in to Zoho Books.',
            'Navigate to <b>Settings → Organisation Profile</b>.',
            'Copy the <b>Organisation ID</b> shown at the top.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("3.5  Configure in Vithana", s["h2"]),
        *step_list(s, [
            'In the Vithana web app, navigate to <b>Settings → Integrations → Zoho Books → Configure</b>.',
            'Fill in all required fields (see table below).',
            'Click <b>Test Connection</b> to verify.',
            'Click <b>Save</b>.',
        ]),
        config_table(s, [
            ("client_id",         "Zoho OAuth Client ID",                            "1000.ABCDEF..."),
            ("client_secret",     "Zoho OAuth Client Secret",                        "2842196c..."),
            ("refresh_token",     "Long-lived refresh token from Step 3.3",          "1000.fd29a3..."),
            ("organization_id",   "Zoho Books Organisation ID",                      "12345678"),
            ("base_url",          "API base (India: zohoapis.in, Global: .com)",     "https://www.zohoapis.in/books/v3"),
            ("auth_url",          "Token endpoint",                                   "https://accounts.zoho.in/oauth/v2/token"),
            ("default_account_id","Fallback Chart of Accounts ID (optional)",        "460000000000388"),
            ("tax_id",            "Zoho tax rate ID for GST auto-split (optional)",  "460000000053001"),
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("3.6  GST Tax Handling", s["h2"]),
        Paragraph(
            "Vithana uses <b>Option A</b>: the <font name='Courier' size='9'>tax_id</font> is set on each "
            "bill line item and Zoho automatically computes CGST / SGST / IGST based on its configured "
            "tax rates. To find your tax_id:",
            s["body"]),
        *bullet_list(s, [
            "In Zoho Books go to <b>Settings → Taxes → Tax Rates</b>.",
            "Click the desired GST rate (e.g., GST 18%).",
            "The URL contains the tax ID: <font name='Courier' size='9'>.../taxrates/<b>460000000053001</b></font>",
        ]),
        info_box(s, "ℹ Note",
                 "If <b>tax_id</b> is left blank, bills are pushed without GST. "
                 "Zoho will use its own default tax rules if configured.",
                 color=BRAND_LIGHT, border=BRAND),
        Spacer(1, 0.3*cm),
        PageBreak(),
    ]
    return elems


# ── Section 4: QuickBooks ─────────────────────────────────────────────────────
def section_quickbooks(s):
    elems = [
        Paragraph("4. QuickBooks Online Integration", s["h1"]),
        hr(),
        Paragraph(
            "Vithana can push approved bills to QuickBooks Online (QBO) using the Intuit OAuth 2.0 flow. "
            "This section covers app creation, credential exchange, and Vithana configuration.",
            s["body"]),
        Spacer(1, 0.3*cm),

        Paragraph("4.1  Create an Intuit Developer App", s["h2"]),
        *step_list(s, [
            'Go to <b>developer.intuit.com</b> and sign in with your Intuit account.',
            'Click <b>Dashboard → Create an app</b>.',
            'Select <b>QuickBooks Online and Payments</b>.',
            'Choose a name (e.g., <i>Vithana Accounting</i>) and select the <b>com.intuit.quickbooks.accounting</b> scope.',
            'Click <b>Create app</b>.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("4.2  Configure Redirect URIs", s["h2"]),
        *step_list(s, [
            'In the app dashboard go to <b>Development → Keys &amp; credentials</b> (or <b>Production</b> tab for live).',
            'Under <b>Redirect URIs</b> add: <font name="Courier" size="9">https://api.vithana.com/api/auth/quickbooks/callback</font>',
            'Save changes.',
            'Note the <b>Client ID</b> and <b>Client Secret</b> from this page.',
        ]),
        info_box(s, "ℹ Sandbox vs Production",
                 "Intuit provides a <b>Sandbox</b> environment with test companies. Use sandbox credentials "
                 "during development. Switch to <b>Production</b> credentials before go-live.",
                 color=BRAND_LIGHT, border=BRAND),
        Spacer(1, 0.3*cm),

        Paragraph("4.3  Authorise and Obtain Tokens", s["h2"]),
        *step_list(s, [
            'In the Vithana Admin Dashboard navigate to <b>Settings → Integrations → QuickBooks → Connect</b>.',
            'Click <b>Authorise QuickBooks</b>. You are redirected to Intuit\'s consent screen.',
            'Select the QuickBooks company to connect and click <b>Connect</b>.',
            'Vithana exchanges the authorisation code for <b>access_token</b> and <b>refresh_token</b> automatically and stores them.',
            'The <b>Realm ID</b> (company ID) is captured from the callback and saved.',
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("4.4  Manual Token Exchange (CLI)", s["h2"]),
        Paragraph("If you need to exchange tokens manually outside the UI:", s["body"]),
        Paragraph(
            "# Step 1 – Build the authorisation URL\n"
            "https://appcenter.intuit.com/connect/oauth2\n"
            "  ?client_id=YOUR_CLIENT_ID\n"
            "  &redirect_uri=YOUR_REDIRECT_URI\n"
            "  &response_type=code\n"
            "  &scope=com.intuit.quickbooks.accounting\n"
            "  &state=random_state_string\n\n"
            "# Step 2 – Exchange the code\n"
            "curl -X POST https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer \\\n"
            "  -H \"Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)\" \\\n"
            "  -H \"Content-Type: application/x-www-form-urlencoded\" \\\n"
            "  -d \"grant_type=authorization_code&code=YOUR_CODE&redirect_uri=YOUR_REDIRECT_URI\"",
            s["code"]),
        Spacer(1, 0.3*cm),

        Paragraph("4.5  Configuration Fields", s["h2"]),
        config_table(s, [
            ("client_id",      "Intuit app Client ID",                          "ABcd1234EFgh..."),
            ("client_secret",  "Intuit app Client Secret",                      "XYZ9876..."),
            ("refresh_token",  "Long-lived refresh token (180-day expiry)",     "AB11..."),
            ("realm_id",       "QuickBooks company ID (Realm ID)",              "1234567890"),
            ("base_url",       "QBO API base URL",                              "https://quickbooks.api.intuit.com"),
            ("auth_url",       "Intuit token endpoint",                         "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"),
            ("environment",    "sandbox or production",                         "production"),
        ]),
        Spacer(1, 0.3*cm),

        Paragraph("4.6  Token Refresh", s["h2"]),
        Paragraph(
            "QBO access tokens expire after <b>1 hour</b>. Refresh tokens expire after <b>180 days</b> "
            "(or 100 days of inactivity). Vithana automatically refreshes the access token before each API call. "
            "Re-authorisation is required only if the refresh token expires.",
            s["body"]),
        info_box(s, "⚠ Important",
                 "Set a calendar reminder to re-authorise QuickBooks every <b>150 days</b> to avoid "
                 "refresh token expiry in production.",
                 color=colors.HexColor("#FFFBEB"), border=WARN),
        Spacer(1, 0.3*cm),
        PageBreak(),
    ]
    return elems


# ── Appendix: Troubleshooting ─────────────────────────────────────────────────
def section_appendix(s):
    elems = [
        Paragraph("Appendix A: Troubleshooting", s["h1"]),
        hr(),
        Spacer(1, 0.2*cm),
    ]

    issues = [
        (
            "Gmail",
            "Access blocked: App has not completed Google verification",
            "Your Google account is not listed as a Test User. Go to Google Auth Platform → Audience → "
            "Test Users and add the email address. Only needed during development; production requires app verification.",
        ),
        (
            "Gmail",
            "Connection failed: HttpError / stale token",
            "The stored OAuth token is invalid or expired. In Vithana go to Settings → Email Sources, "
            "disconnect the Gmail source, and re-authorise by clicking Connect Gmail again.",
        ),
        (
            "Gmail",
            "Wrong redirect URI port",
            "The redirect URI in Google Cloud Console must exactly match what Vithana sends. "
            "Check GOOGLE_REDIRECT_URI in .env and update the Google Cloud Console entry to match.",
        ),
        (
            "Zoho",
            "Invalid grant / refresh token revoked",
            "The refresh token has been revoked (e.g., password change, session purge). "
            "Repeat Section 3.2–3.3 to generate a new grant token and exchange it for a fresh refresh token.",
        ),
        (
            "Zoho",
            "Vendor not found on Zoho",
            "Vithana could not find the vendor in Zoho Books. Create a Vendor Mapping in "
            "Settings → Vendor Mappings, mapping the alias to an existing Zoho contact, or create the vendor in Zoho first.",
        ),
        (
            "Zoho",
            "Bill created but no GST applied",
            "The tax_id field is not set in the Zoho integration config. Find the tax rate ID in "
            "Zoho Books → Settings → Taxes → Tax Rates and add it to the integration settings.",
        ),
        (
            "QuickBooks",
            "AuthenticationFailed / Invalid token",
            "The access token has expired (1-hour TTL). Vithana auto-refreshes — if this persists, "
            "the refresh token may have expired (180 days). Re-authorise via Settings → Integrations → QuickBooks.",
        ),
        (
            "QuickBooks",
            "Company not found / Invalid Realm ID",
            "The realm_id does not match the connected QBO company. Check the Realm ID in your QBO "
            "URL (https://app.qbo.intuit.com/app/homepage?token=<realm_id>) and update the integration config.",
        ),
    ]

    header = [
        Paragraph("Platform", s["table_h"]),
        Paragraph("Error / Symptom", s["table_h"]),
        Paragraph("Resolution", s["table_h"]),
    ]
    rows = [header]
    for platform, error, resolution in issues:
        platform_color = {
            "Gmail": colors.HexColor("#FEF3C7"),
            "Zoho":  colors.HexColor("#ECFDF5"),
            "QuickBooks": colors.HexColor("#EFF6FF"),
        }.get(platform, colors.white)
        rows.append([
            Paragraph(f"<b>{platform}</b>", ParagraphStyle(
                "tp", fontSize=9, textColor=DARK, leading=13, fontName="Helvetica-Bold")),
            Paragraph(error, s["table_c"]),
            Paragraph(resolution, s["table_c"]),
        ])

    t = Table(rows, colWidths=[2.5*cm, 5.5*cm, 8.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ("BOX", (0,0), (-1,-1), 0.5, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("LEFTPADDING", (0,0), (-1,-1), 7),
        ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    elems.append(t)
    elems.append(Spacer(1, 0.5*cm))

    elems += [
        Paragraph("Support", s["h2"]),
        Paragraph(
            "For platform-specific issues consult the official documentation:",
            s["body"]),
        *bullet_list(s, [
            "<b>Google OAuth</b>: developers.google.com/identity/protocols/oauth2",
            "<b>Gmail API</b>: developers.google.com/gmail/api",
            "<b>Zoho Books API</b>: www.zoho.com/books/api/v3",
            "<b>QuickBooks API</b>: developer.intuit.com/app/developer/qbo/docs",
        ]),
    ]
    return elems


# ── Header / Footer ───────────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    # Header line
    canvas.setStrokeColor(BRAND)
    canvas.setLineWidth(1.5)
    canvas.line(2*cm, h - 1.5*cm, w - 2*cm, h - 1.5*cm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(BRAND)
    canvas.drawString(2*cm, h - 1.2*cm, "Vithana Accounting Automation")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(w - 2*cm, h - 1.2*cm, "Integration Setup Guide v1.0")
    # Footer line
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, 1.5*cm, w - 2*cm, 1.5*cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(2*cm, 1.1*cm, "Internal Use Only · Vithana Consulting")
    canvas.drawRightString(w - 2*cm, 1.1*cm, f"Page {doc.page}")
    canvas.restoreState()


def on_cover(canvas, doc):
    # No header/footer on cover
    pass


# ── Main ──────────────────────────────────────────────────────────────────────
def build():
    import os
    os.makedirs("docs", exist_ok=True)

    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title="Vithana Integration Setup Guide",
        author="Vithana Consulting",
        subject="Gmail OAuth, Gmail Ingest, Zoho Books, QuickBooks Online",
    )

    s = styles()
    story = []

    # Cover (no header/footer)
    story += cover_page(s)
    # TOC
    story += toc_page(s)
    # Sections
    story += section_gmail_oauth(s)
    story += section_gmail_ingest(s)
    story += section_zoho(s)
    story += section_quickbooks(s)
    story += section_appendix(s)

    # Build with page callbacks — cover gets blank, rest get header/footer
    doc.build(
        story,
        onFirstPage=on_cover,
        onLaterPages=on_page,
    )
    print(f"PDF written to: {OUTPUT}")


if __name__ == "__main__":
    build()
