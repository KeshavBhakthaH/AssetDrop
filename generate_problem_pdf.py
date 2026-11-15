import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#71717a"))
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 755, "AssetDrop Architecture Brief — Seamless Cross-Device Security Dilemma")
            self.setStrokeColor(colors.HexColor("#27272a"))
            self.setLineWidth(0.5)
            self.line(54, 747, 558, 747)
            
        # Footer
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, page_str)
        self.drawString(54, 36, "CONFIDENTIAL // ENGINEERING ARCHITECTURE BRIEF")
        self.setStrokeColor(colors.HexColor("#27272a"))
        self.setLineWidth(0.5)
        self.line(54, 48, 558, 48)
        self.restoreState()

def build_pdf(filename):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#09090b")
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#10b981"),
        spaceAfter=15
    )

    meta_style = ParagraphStyle(
        'MetaText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#52525b")
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#09090b"),
        spaceBefore=14,
        spaceAfter=6
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#18181b"),
        spaceBefore=8,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13.5,
        textColor=colors.HexColor("#27272a"),
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'BulletText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=13,
        textColor=colors.HexColor("#27272a"),
        leftIndent=12,
        spaceAfter=3
    )

    callout_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13.5,
        textColor=colors.HexColor("#065f46")
    )

    code_style = ParagraphStyle(
        'CodeText',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#09090b")
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("TECHNICAL ARCHITECTURE & PRODUCT DILEMMA BRIEF", subtitle_style))
    story.append(Paragraph("Zero-Friction Ingestion vs. Public Network Security", title_style))
    story.append(Spacer(1, 4))
    
    meta_table_data = [
        [
            Paragraph("<b>Project:</b> AssetDrop Cross-Device Media Engine", meta_style),
            Paragraph("<b>Target Audience:</b> Systems & Full-Stack Developers", meta_style)
        ],
        [
            Paragraph("<b>Focus:</b> The Public Wi-Fi Security vs. UX Dilemma", meta_style),
            Paragraph("<b>Date:</b> November 2026 // Version 1.0", meta_style)
        ]
    ]
    t_meta = Table(meta_table_data, colWidths=[250, 254])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f4f4f5")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#e4e4e7")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 12))

    # Executive Summary Callout
    summary_text = (
        "<b>Core Dilemma:</b> AssetDrop was conceived as an invisible, zero-friction tool: "
        "a video editor browses Reels/TikToks/YouTube on mobile, taps <i>Paste</i>, and sends the media directly to their PC "
        "in under 50ms. However, adding mandatory passwords, device UIDs, and login screens destroyed this seamless experience. "
        "Yet, removing security entirely creates critical attack surfaces on public networks (coffee shops, studios, shared Wi-Fi). "
        "This brief details the exact problem and provides production-ready architectural solutions."
    )
    t_summary = Table([[Paragraph(summary_text, callout_style)]], colWidths=[504])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#ecfdf5")),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor("#a7f3d0")),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 10))

    # Section 1: The Core Value Proposition vs. The UX Failure
    story.append(Paragraph("1. The UX Breakdown: How Security Broke the Product", h1_style))
    story.append(Paragraph(
        "The core reason users want AssetDrop is speed. Traditional workflows (WhatsApp self-messages, cloud drives, browser downloaders) "
        "are clunky, compress files, waste phone data, and require 5+ manual steps. AssetDrop solves this with instant LAN RPC.",
        body_style
    ))

    flow_comparison_data = [
        [
            Paragraph("<b>Original Intended UX (Zero-Friction)</b>", h2_style),
            Paragraph("<b>Current Broken UX (Manual Friction)</b>", h2_style)
        ],
        [
            Paragraph(
                "1. User discovers video on Instagram/TikTok/YouTube.<br/>"
                "2. Copies link.<br/>"
                "3. Opens AssetDrop on phone.<br/>"
                "4. Taps <b>[ Paste ]</b> &rarr; Taps <b>[ Send ]</b>.<br/>"
                "5. <b>Total Time: 2 seconds.</b> Zero auth friction.",
                body_style
            ),
            Paragraph(
                "1. User discovers video on phone.<br/>"
                "2. Opens AssetDrop.<br/>"
                "3. <b>Blocked:</b> 'Workstation Connection Required'.<br/>"
                "4. Must enter Device UID & Workstation Password.<br/>"
                "5. Token storage errors, expired sessions, typing on mobile.<br/>"
                "6. <b>Result:</b> Slower than WhatsApp. Users abandon it.",
                body_style
            )
        ]
    ]
    t_flow = Table(flow_comparison_data, colWidths=[248, 256])
    t_flow.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#f0fdf4")),
        ('BACKGROUND', (1,0), (1,-1), colors.HexColor("#fef2f2")),
        ('BOX', (0,0), (0,-1), 0.5, colors.HexColor("#bbf7d0")),
        ('BOX', (1,0), (1,-1), 0.5, colors.HexColor("#fecaca")),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_flow)
    story.append(Spacer(1, 10))

    # Section 2: The Security Threat Model on Public Wi-Fi
    story.append(Paragraph("2. The Security Threat Model: What Happens on Public Wi-Fi?", h1_style))
    story.append(Paragraph(
        "If we solve the UX problem by simply removing all authentication (running wide open on <code>0.0.0.0:8000</code>), "
        "it works beautifully at home. But the moment a video editor works on a laptop at Starbucks, an airport, a coworking space, "
        "or a shared university network, severe security vulnerabilities emerge:",
        body_style
    ))

    threat_data = [
        [Paragraph("<b>Threat Vector</b>", h2_style), Paragraph("<b>Mechanism</b>", h2_style), Paragraph("<b>Severity / Impact</b>", h2_style)],
        [
            Paragraph("<b>1. Arbitrary Disk Filling (DoS)</b>", body_style),
            Paragraph("Anyone on the same subnet (e.g. <code>10.0.x.x</code>) can scan port 8000 and blast <code>POST /download</code> with massive 4K/8K stream URLs.", body_style),
            Paragraph("<font color='#dc2626'><b>HIGH:</b> Exhausts PC SSD storage, chokes CPU with FFmpeg muxing, crashes NLE.</font>", body_style)
        ],
        [
            Paragraph("<b>2. Filesystem Reconnaissance</b>", body_style),
            Paragraph("An attacker queries <code>/api/browse?path=C:\\</code> or <code>/api/drives</code> to map the victim's folder structure, project names, and client identities.", body_style),
            Paragraph("<font color='#ea580c'><b>MEDIUM-HIGH:</b> Privacy breach, client confidentiality leak for commercial editors.</font>", body_style)
        ],
        [
            Paragraph("<b>3. Malicious Source Ingestion</b>", body_style),
            Paragraph("Attacker triggers downloads of malicious archives, phishing media, or illegal material directly into the victim's project folders.", body_style),
            Paragraph("<font color='#dc2626'><b>CRITICAL:</b> Compromises workstation integrity and legal compliance.</font>", body_style)
        ],
        [
            Paragraph("<b>4. Plaintext LAN Sniffing</b>", body_style),
            Paragraph("Standard HTTP traffic on unencrypted Wi-Fi allows other clients to inspect URLs and filenames via ARP spoofing/packet capture.", body_style),
            Paragraph("<font color='#d97706'><b>MEDIUM:</b> Leaks editorial links, unreleased footage, and private tokens.</font>", body_style)
        ]
    ]
    t_threat = Table(threat_data, colWidths=[120, 234, 150])
    t_threat.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f4f4f5")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e4e4e7")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_threat)
    story.append(Spacer(1, 10))

    # Section 3: Recommended Architecture Solutions
    story.append(Paragraph("3. Recommended Engineering Solutions (How to Solve Both)", h1_style))
    story.append(Paragraph(
        "To achieve <b>Apple AirDrop-like zero-friction UX</b> while maintaining <b>enterprise-grade public Wi-Fi security</b>, "
        "the engineering team should evaluate the following three design patterns:",
        body_style
    ))

    # Solution A
    story.append(Paragraph("<b>Approach A: The WhatsApp Web Model (Ephemeral QR Handshake — Recommended for LAN)</b>", h2_style))
    story.append(Paragraph(
        "<b>Concept:</b> The user NEVER types a password or UID. When the PC desktop app opens, it displays an encrypted ephemeral QR code on screen. "
        "The phone camera scans it once. The QR code contains: <code>http://[LAN_IP]:8000?auth=[CRYPTOGRAPHIC_HMAC_SECRET]</code>.<br/>"
        "&bull; <b>Why it's seamless:</b> Zero typing. 1-second camera glance. Phone saves token permanently in <code>localStorage</code>.<br/>"
        "&bull; <b>Why it's secure on Public Wi-Fi:</b> Strangers on the coffee shop Wi-Fi cannot see the PC screen, so they cannot scan the code. Unauthenticated requests receive <code>401 Unauthorized</code>.",
        bullet_style
    ))
    story.append(Spacer(1, 4))

    # Solution B
    story.append(Paragraph("<b>Approach B: The WireGuard Mesh Model (Tailscale — Zero Passwords Everywhere)</b>", h2_style))
    story.append(Paragraph(
        "<b>Concept:</b> Instead of binding to open LAN Wi-Fi (<code>0.0.0.0</code>), the PC daemon binds strictly to a private Tailscale interface (<code>100.x.y.z</code> or <code>127.0.0.1</code>).<br/>"
        "&bull; <b>Why it's seamless:</b> Completely eliminates passwords, logins, and pairing screens. The phone app has 1 screen only.<br/>"
        "&bull; <b>Why it's secure on Public Wi-Fi:</b> Device-to-device traffic is end-to-end encrypted with WireGuard keys. Port 8000 is completely invisible to anyone on the public Wi-Fi or internet. Works identically whether on coffee shop Wi-Fi or 4G/5G cellular.",
        bullet_style
    ))
    story.append(Spacer(1, 4))

    # Solution C
    story.append(Paragraph("<b>Approach C: Network-Aware Dual-Mode (Home Mode vs. Studio/Public Mode)</b>", h2_style))
    story.append(Paragraph(
        "<b>Concept:</b> The desktop app provides a simple toggle: <i>'Home Mode (Open Access)'</i> vs. <i>'Public Mode (QR Bond Required)'</i>.<br/>"
        "&bull; At home on private trusted Wi-Fi, the editor enables Open Mode: zero authentication, pure instant ingestion.<br/>"
        "&bull; In public spaces or multi-tenant studio networks, one click activates Public Mode, locking down endpoints to pre-paired device tokens.",
        bullet_style
    ))
    story.append(Spacer(1, 10))

    # Section 4: Implementation Specification for the Developer
    story.append(Paragraph("4. Actionable Deliverables & Refactoring Scope for the Dev", h1_style))
    story.append(Paragraph("Here is the exact architectural contract the developer needs to implement:", body_style))

    dev_scope_data = [
        [Paragraph("<b>Component</b>", h2_style), Paragraph("<b>Target Behavior / Engineering Contract</b>", h2_style)],
        [
            Paragraph("<b>Mobile Client UI</b>", body_style),
            Paragraph("<b>Strip all clutter.</b> Exactly 1 functional screen: Paste input (auto-detects clipboard), MP4/MP3 format toggle, target folder dropdown, and <code>[ Download to PC ]</code>. If unpaired in public mode, present a camera QR scanner, <i>never a manual password form</i>.", body_style)
        ],
        [
            Paragraph("<b>PC Workstation App</b>", body_style),
            Paragraph("Remove link paste box entirely. Display active shared folder targets (with '+ Add Folder' and 'Open in Explorer'), real-time download feed table (title, size, status), and a prominent connection QR code card.", body_style)
        ],
        [
            Paragraph("<b>Auth Middleware</b>", body_style),
            Paragraph("Replace manual username/password modals with token-in-URL QR pairing (<code>/pair?token=...</code>) or Tailscale IP whitelisting. Use constant-time HMAC validation.", body_style)
        ]
    ]
    t_scope = Table(dev_scope_data, colWidths=[130, 374])
    t_scope.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f4f4f5")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e4e4e7")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_scope)

    doc.build(story, canvasmaker=NumberedCanvas)
    print("PDF generated successfully:", filename)

if __name__ == "__main__":
    out_pdf = "d:/AssetDrop/AssetDrop_Security_vs_Friction_Brief.pdf"
    build_pdf(out_pdf)
