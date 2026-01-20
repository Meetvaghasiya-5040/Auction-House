from reportlab.platypus import Image, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.pdfgen import canvas
from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.contrib.admin.views.decorators import staff_member_required
from .models import Auction, Item,Lot

import os

class NumberedCanvas(canvas.Canvas):
    """Custom canvas for adding headers and footers"""
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.grey)
        # Footer
        self.drawRightString(
            A4[0] - 30, 20,
            f"Page {self._pageNumber} of {page_count}"
        )
        self.drawString(
            30, 20,
            f"Generated on {timezone.now().strftime('%d-%m-%Y at %H:%M')}"
        )
        # Header line
        self.setStrokeColor(colors.HexColor('#2c3e50'))
        self.setLineWidth(2)
        self.line(30, A4[1] - 30, A4[0] - 30, A4[1] - 30)


@login_required
def create_auction(request):
    """Create new auction"""
    if request.method == 'POST':
        try:
            # Get form data
            title = request.POST.get('title')
            description = request.POST.get('description')
            auction_type = request.POST.get('auction_type', 'live')
            location = request.POST.get('location', '')
            buyer_premium = request.POST.get('buyer_premium_percentage', 0)
            min_bid_increment = request.POST.get('min_bid_increment', 100)
            allow_proxy = request.POST.get('allow_proxy_bidding') == 'on'
            terms = request.POST.get('terms_and_conditions', '')
            action = request.POST.get('action', 'submit')
            
            # Create auction
            auction = Auction.objects.create(
                title=title,
                description=description,
                auction_type=auction_type,
                location=location,
                created_by=request.user,
                buyer_premium_percentage=buyer_premium,
                min_bid_increment=min_bid_increment,
                allow_proxy_bidding=allow_proxy,
                terms_and_conditions=terms,
                status='draft'
            )
            
            # Handle scheduled auction dates
            if auction_type == 'scheduled':
                start_date_str = request.POST.get('start_date')
                end_date_str = request.POST.get('end_date')
                
                if start_date_str and end_date_str:
                    # Parse the datetime strings
                    start_dt = parse_datetime(start_date_str)
                    end_dt = parse_datetime(end_date_str)
                    
                    # Make them timezone-aware if they aren't already
                    if start_dt and timezone.is_naive(start_dt):
                        start_dt = timezone.make_aware(start_dt)
                    if end_dt and timezone.is_naive(end_dt):
                        end_dt = timezone.make_aware(end_dt)
                    
                    auction.start_date = start_dt
                    auction.end_date = end_dt
                    auction.save()
            
            # Handle action
            if action == 'submit':
                if request.user.is_staff:
                    # Staff can directly approve
                    auction.approve(request.user)
                    messages.success(request, 'Auction created and approved!')
                else:
                    # Regular users submit for approval
                    auction.submit_for_approval()
                    messages.success(request, 'Auction submitted for approval!')
            else:
                messages.success(request, 'Auction saved as draft!')
            
            return redirect('all_auction')
            
        except Exception as e:
            messages.error(request, f'Error creating auction: {str(e)}')
    
    return render(request, 'auctions/create_auction.html')



def format_inr(amount):
    if not amount:
        return "Rs. 0"
    return f"Rs. {amount:,.2f}"


def auction_report_pdf(request):
    """Generate comprehensive professional auction house report PDF"""

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Auction_House_Comprehensive_Report.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=60,
        bottomMargin=60
    )

    styles = getSampleStyleSheet()
    elements = []

    # Custom Styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=20,
        fontName='Helvetica-Bold',
        leading=28
    )

    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#7f8c8d'),
        alignment=TA_CENTER,
        spaceAfter=30
    )

    heading2_style = ParagraphStyle(
        "CustomHeading2",
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=20,
        fontName='Helvetica-Bold',
        backColor=colors.HexColor('#ecf0f1'),
        leftIndent=10,
        rightIndent=10
    )

    heading3_style = ParagraphStyle(
        "CustomHeading3",
        parent=styles['Heading3'],
        fontSize=13,
        textColor=colors.HexColor('#34495e'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold'
    )

    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_JUSTIFY,
        spaceAfter=10,
        leading=14
    )

    # ============ COVER PAGE ============
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("AUCTION HOUSE", title_style))
    elements.append(Paragraph("COMPREHENSIVE BUSINESS REPORT", title_style))
    elements.append(Paragraph("Detailed Analysis & Performance Overview", subtitle_style))
    elements.append(Spacer(1, 30))

    report_info = [
        ["Report Generated:", timezone.now().strftime('%d %B %Y at %H:%M')],
        ["Report Period:", "All Time"],
        ["Generated By:", request.user.get_full_name() or request.user.username if hasattr(request, 'user') else "System"],
        ["Report Type:", "Full Auction House Analysis"],
        ["Classification:", "Confidential - Internal Use Only"]
    ]

    info_table = Table(report_info, colWidths=[2.5*inch, 3.5*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#3498db')),
        ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#ecf0f1')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))

    elements.append(info_table)
    elements.append(PageBreak())

    # ============ TABLE OF CONTENTS ============
    elements.append(Paragraph("TABLE OF CONTENTS", heading2_style))
    elements.append(Spacer(1, 20))
    
    toc_data = [
        ["Section", "Page"],
        ["1. Executive Summary", "3"],
        ["2. Auction Overview Statistics", "4"],
        ["3. Financial Summary", "5"],
        ["4. Auction Status Breakdown", "6"],
        ["5. Detailed Auction Listings", "7"],
        ["6. Top Performing Auctions", "8"],
        ["7. Lot Analysis", "9"],
        ["8. Auction Type Performance", "10"],
        ["9. Timeline Analysis", "11"],
        ["10. Recommendations & Insights", "12"],
    ]
    
    toc_table = Table(toc_data, colWidths=[4.5*inch, 1.5*inch])
    toc_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(toc_table)
    elements.append(PageBreak())

    # ============ DATA COLLECTION ============
    auctions = Auction.objects.all().select_related('created_by', 'approved_by').prefetch_related('lots')
    total_auctions = auctions.count()
    
    # Calculate comprehensive statistics
    total_value = sum(a.total_value or 0 for a in auctions)
    total_lots = sum(a.total_lots or 0 for a in auctions)
    
    active_auctions = auctions.filter(status='live').count()
    completed_auctions = auctions.filter(status='completed').count()
    pending_auctions = auctions.filter(status='pending').count()
    draft_auctions = auctions.filter(status='draft').count()
    scheduled_auctions = auctions.filter(status='scheduled').count()
    cancelled_auctions = auctions.filter(status='cancelled').count()
    approved_auctions = auctions.filter(status='approved').count()
    
    # Auction types
    live_type = auctions.filter(auction_type='live').count()
    scheduled_type = auctions.filter(auction_type='scheduled').count()
    timed_type = auctions.filter(auction_type='timed').count()

    # ============ EXECUTIVE SUMMARY ============
    elements.append(Paragraph("1. EXECUTIVE SUMMARY", heading2_style))
    elements.append(Spacer(1, 12))
    
    summary_text = f"""
    This comprehensive report provides a detailed overview of all auction house activities and performance metrics.
    The analysis encompasses {total_auctions} total auctions with a combined estimated value of {format_inr(total_value)}
    across {total_lots} individual lots. The current operational status indicates {active_auctions} active auctions,
    {completed_auctions} successfully completed auctions, and {pending_auctions} awaiting approval.
    <br/><br/>
    The auction house demonstrates diverse operational capabilities with {live_type} live auctions, 
    {scheduled_type} scheduled auctions, and {timed_type} timed auctions. This diversified approach 
    ensures optimal market coverage and client satisfaction. The pipeline includes {draft_auctions} auctions 
    in draft status and {scheduled_auctions} scheduled for future dates, indicating healthy future business flow.
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 15))

    # Key Highlights Box
    highlights_data = [
        ["KEY PERFORMANCE HIGHLIGHTS"],
        [f"Total Auction Value: {format_inr(total_value)}"],
        [f"Average Value per Auction: {format_inr(total_value/total_auctions if total_auctions > 0 else 0)}"],
        [f"Average Lots per Auction: {total_lots/total_auctions if total_auctions > 0 else 0:.1f}"],
        [f"Completion Rate: {(completed_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
    ]
    
    highlights_table = Table(highlights_data, colWidths=[6*inch])
    highlights_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#27ae60')),
        ('TEXTCOLOR', (0, 0), (0, 0), colors.white),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#e8f8f5')),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#27ae60')),
        ('FONTSIZE', (0, 1), (0, -1), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(highlights_table)
    elements.append(PageBreak())

    # ============ AUCTION OVERVIEW STATISTICS ============
    elements.append(Paragraph("2. AUCTION OVERVIEW STATISTICS", heading2_style))
    elements.append(Spacer(1, 12))

    stats_data = [
        ["Metric", "Value", "Metric", "Value"],
        ["Total Auctions", str(total_auctions), "Total Lots", str(total_lots)],
        ["Active (Live)", str(active_auctions), "Completed", str(completed_auctions)],
        ["Pending Approval", str(pending_auctions), "Draft", str(draft_auctions)],
        ["Scheduled", str(scheduled_auctions), "Approved", str(approved_auctions)],
        ["Cancelled", str(cancelled_auctions), "Total Value", format_inr(total_value)],
    ]

    stats_table = Table(stats_data, colWidths=[1.8*inch, 1.2*inch, 1.8*inch, 1.2*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#ecf0f1')),
        ('BACKGROUND', (2, 1), (2, -1), colors.HexColor('#ecf0f1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(stats_table)
    elements.append(Spacer(1, 20))

    # Auction Type Distribution
    elements.append(Paragraph("Auction Type Distribution", heading3_style))
    type_data = [
        ["Auction Type", "Count", "Percentage"],
        ["Live Auction", str(live_type), f"{(live_type/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
        ["Scheduled Auction", str(scheduled_type), f"{(scheduled_type/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
        ["Timed Auction", str(timed_type), f"{(timed_type/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
    ]
    
    type_table = Table(type_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
    type_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(type_table)
    elements.append(PageBreak())

    # ============ FINANCIAL SUMMARY ============
    elements.append(Paragraph("3. FINANCIAL SUMMARY", heading2_style))
    elements.append(Spacer(1, 12))

    # Calculate financial metrics by status
    completed_value = sum(a.total_value or 0 for a in auctions.filter(status='completed'))
    live_value = sum(a.total_value or 0 for a in auctions.filter(status='live'))
    scheduled_value = sum(a.total_value or 0 for a in auctions.filter(status='scheduled'))
    pending_value = sum(a.total_value or 0 for a in auctions.filter(status='pending'))

    # Calculate potential commission (assuming average 15% buyer premium)
    avg_premium = Decimal('0.15')  # Convert to Decimal
    potential_commission = total_value * avg_premium
    realized_commission = completed_value * avg_premium

    financial_data = [
        ["Financial Metric", "Amount (INR)"],
        ["Total Catalog Value", format_inr(total_value)],
        ["Completed Auction Value", format_inr(completed_value)],
        ["Live Auction Value", format_inr(live_value)],
        ["Scheduled Auction Value", format_inr(scheduled_value)],
        ["Pipeline Value (Pending)", format_inr(pending_value)],
        ["", ""],
        ["Estimated Total Commission (15%)", format_inr(potential_commission)],
        ["Realized Commission (Completed)", format_inr(realized_commission)],
        ["Pending Commission (Active)", format_inr((live_value + scheduled_value) * avg_premium)],
    ]

    financial_table = Table(financial_data, colWidths=[3.5*inch, 2.5*inch])
    financial_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('BACKGROUND', (0, 6), (-1, 6), colors.HexColor('#ecf0f1')),
        ('BACKGROUND', (0, 7), (-1, -1), colors.HexColor('#d5f4e6')),
        ('FONTNAME', (0, 7), (0, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(financial_table)
    elements.append(Spacer(1, 15))

    financial_note = """
    <b>Note:</b> Commission calculations are based on an average 15% buyer's premium. 
    Actual commissions may vary based on individual auction terms and seller agreements.
    Pipeline value represents potential future revenue from pending and scheduled auctions.
    """
    elements.append(Paragraph(financial_note, ParagraphStyle(
        'FinNote', parent=body_style, fontSize=9, textColor=colors.HexColor('#7f8c8d')
    )))
    elements.append(PageBreak())

    # ============ AUCTION STATUS BREAKDOWN ============
    elements.append(Paragraph("4. AUCTION STATUS BREAKDOWN", heading2_style))
    elements.append(Spacer(1, 12))

    status_data = [
        ["Status", "Count", "Percentage", "Total Value"],
        ["Live", str(active_auctions), f"{(active_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(live_value)],
        ["Completed", str(completed_auctions), f"{(completed_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(completed_value)],
        ["Scheduled", str(scheduled_auctions), f"{(scheduled_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(scheduled_value)],
        ["Pending Approval", str(pending_auctions), f"{(pending_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(pending_value)],
        ["Approved", str(approved_auctions), f"{(approved_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(sum(a.total_value or 0 for a in auctions.filter(status='approved')))],
        ["Draft", str(draft_auctions), f"{(draft_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(sum(a.total_value or 0 for a in auctions.filter(status='draft')))],
        ["Cancelled", str(cancelled_auctions), f"{(cancelled_auctions/total_auctions*100 if total_auctions > 0 else 0):.1f}%", format_inr(sum(a.total_value or 0 for a in auctions.filter(status='cancelled')))],
    ]

    status_table = Table(status_data, colWidths=[2*inch, 1*inch, 1.5*inch, 1.5*inch])
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(status_table)
    elements.append(PageBreak())

    # ============ DETAILED AUCTION LISTINGS ============
    elements.append(Paragraph("5. DETAILED AUCTION LISTINGS", heading2_style))
    elements.append(Spacer(1, 12))

    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER)
    cell_style_left = ParagraphStyle('CellStyleLeft', parent=styles['Normal'], fontSize=7, alignment=TA_LEFT)

    data = [[
        Paragraph("<b>ID</b>", cell_style),
        Paragraph("<b>Title</b>", cell_style),
        Paragraph("<b>Type</b>", cell_style),
        Paragraph("<b>Status</b>", cell_style),
        Paragraph("<b>Creator</b>", cell_style),
        Paragraph("<b>Start Date</b>", cell_style),
        Paragraph("<b>End Date</b>", cell_style),
        Paragraph("<b>Lots</b>", cell_style),
        Paragraph("<b>Value</b>", cell_style),
    ]]

    for a in auctions:
        data.append([
            Paragraph(str(a.id), cell_style),
            Paragraph(a.title[:30] + "..." if len(a.title) > 30 else a.title, cell_style_left),
            Paragraph(a.get_auction_type_display()[:10], cell_style),
            Paragraph(a.get_status_display(), cell_style),
            Paragraph(a.created_by.username if a.created_by else "-", cell_style),
            Paragraph(a.start_date.strftime("%d/%m/%y") if a.start_date else "-", cell_style),
            Paragraph(a.end_date.strftime("%d/%m/%y") if a.end_date else "-", cell_style),
            Paragraph(str(a.total_lots or 0), cell_style),
            Paragraph(format_inr(a.total_value), cell_style),
        ])

    table = Table(data, repeatRows=1, colWidths=[0.4*inch, 1.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.7*inch, 0.7*inch, 0.5*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)
    elements.append(PageBreak())

    # ============ TOP PERFORMING AUCTIONS ============
    elements.append(Paragraph("6. TOP PERFORMING AUCTIONS", heading2_style))
    elements.append(Spacer(1, 12))

    # Get top 10 by value
    top_auctions = sorted(auctions, key=lambda x: x.total_value or 0, reverse=True)[:10]

    top_data = [[
        Paragraph("<b>Rank</b>", cell_style),
        Paragraph("<b>Auction Title</b>", cell_style),
        Paragraph("<b>Type</b>", cell_style),
        Paragraph("<b>Status</b>", cell_style),
        Paragraph("<b>Lots</b>", cell_style),
        Paragraph("<b>Total Value</b>", cell_style),
    ]]

    for idx, a in enumerate(top_auctions, 1):
        top_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(a.title[:40] + "..." if len(a.title) > 40 else a.title, cell_style_left),
            Paragraph(a.get_auction_type_display(), cell_style),
            Paragraph(a.get_status_display(), cell_style),
            Paragraph(str(a.total_lots or 0), cell_style),
            Paragraph(format_inr(a.total_value), cell_style),
        ])

    top_table = Table(top_data, repeatRows=1, colWidths=[0.5*inch, 2.2*inch, 1*inch, 1*inch, 0.6*inch, 1.2*inch])
    top_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e74c3c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 1), (0, 3), colors.HexColor('#f9e79f')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(top_table)
    elements.append(PageBreak())

    # ============ LOT ANALYSIS ============
    elements.append(Paragraph("7. LOT ANALYSIS", heading2_style))
    elements.append(Spacer(1, 12))

    lot_analysis_text = f"""
    The auction house currently manages a total of {total_lots} lots across all auctions. 
    This represents a diverse inventory spanning various categories and value ranges. The average 
    number of lots per auction is {total_lots/total_auctions if total_auctions > 0 else 0:.1f}, 
    indicating a balanced catalog size that optimizes buyer engagement while maintaining quality standards.
    """
    elements.append(Paragraph(lot_analysis_text, body_style))
    elements.append(Spacer(1, 15))

    # Lot distribution by auction
    lot_dist_data = [["Auction", "Number of Lots", "Avg Value per Lot"]]
    
    for a in auctions[:15]:  # Top 15
        avg_lot_value = (a.total_value / a.total_lots) if a.total_lots and a.total_lots > 0 else 0
        lot_dist_data.append([
            a.title[:35] + "..." if len(a.title) > 35 else a.title,
            str(a.total_lots or 0),
            format_inr(avg_lot_value)
        ])

    lot_dist_table = Table(lot_dist_data, repeatRows=1, colWidths=[3*inch, 1.5*inch, 1.5*inch])
    lot_dist_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2980b9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    elements.append(lot_dist_table)
    elements.append(PageBreak())

    # ============ AUCTION TYPE PERFORMANCE ============
    elements.append(Paragraph("8. AUCTION TYPE PERFORMANCE ANALYSIS", heading2_style))
    elements.append(Spacer(1, 12))

    type_perf_data = [
        ["Auction Type", "Total Count", "Completed", "Active", "Avg Value", "Total Value"],
    ]

    for auc_type, display_name in [('live', 'Live Auction'), ('scheduled', 'Scheduled'), ('timed', 'Timed')]:
        type_auctions = auctions.filter(auction_type=auc_type)
        type_count = type_auctions.count()
        type_completed = type_auctions.filter(status='completed').count()
        type_active = type_auctions.filter(status='live').count()
        type_value = sum(a.total_value or 0 for a in type_auctions)
        type_avg = type_value / type_count if type_count > 0 else 0

        type_perf_data.append([
            display_name,
            str(type_count),
            str(type_completed),
            str(type_active),
            format_inr(type_avg),
            format_inr(type_value)
        ])

    type_perf_table = Table(type_perf_data, colWidths=[1.5*inch, 1*inch, 1*inch, 0.8*inch, 1.2*inch, 1*inch])
    type_perf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d35400')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(type_perf_table)
    elements.append(PageBreak())

    # ============ TIMELINE ANALYSIS ============
    elements.append(Paragraph("9. TIMELINE ANALYSIS", heading2_style))
    elements.append(Spacer(1, 12))

    # Monthly activity analysis
    from datetime import datetime, timedelta
    from collections import defaultdict
    
    monthly_data = defaultdict(lambda: {'count': 0, 'value': 0})
    
    for a in auctions:
        if a.created_at:
            month_key = a.created_at.strftime('%Y-%m')
            monthly_data[month_key]['count'] += 1
            monthly_data[month_key]['value'] += a.total_value or 0
    
    # Get last 12 months
    sorted_months = sorted(monthly_data.keys(), reverse=True)[:12]
    
    if sorted_months:
        timeline_data = [["Month", "Auctions Created", "Total Value"]]
        
        for month in reversed(sorted_months):
            month_display = datetime.strptime(month, '%Y-%m').strftime('%B %Y')
            timeline_data.append([
                month_display,
                str(monthly_data[month]['count']),
                format_inr(monthly_data[month]['value'])
            ])
        
        timeline_table = Table(timeline_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
        timeline_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(timeline_table)
    
    elements.append(Spacer(1, 20))
    
    # Upcoming auctions
    elements.append(Paragraph("Upcoming Scheduled Auctions", heading3_style))
    upcoming = auctions.filter(status='scheduled', start_date__gte=timezone.now()).order_by('start_date')[:10]
    
    if upcoming.exists():
        upcoming_data = [["Title", "Start Date", "End Date", "Lots", "Value"]]
        
        for a in upcoming:
            upcoming_data.append([
                a.title[:30] + "..." if len(a.title) > 30 else a.title,
                a.start_date.strftime("%d %b %Y") if a.start_date else "-",
                a.end_date.strftime("%d %b %Y") if a.end_date else "-",
                str(a.total_lots or 0),
                format_inr(a.total_value)
            ])
        
        upcoming_table = Table(upcoming_data, colWidths=[2*inch, 1.2*inch, 1.2*inch, 0.8*inch, 1.3*inch])
        upcoming_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))
        elements.append(upcoming_table)
    else:
        elements.append(Paragraph("No upcoming scheduled auctions at this time.", body_style))
    
    elements.append(PageBreak())

    # ============ RECOMMENDATIONS & INSIGHTS ============
    elements.append(Paragraph("10. RECOMMENDATIONS & INSIGHTS", heading2_style))
    elements.append(Spacer(1, 12))

    # Generate insights based on data
    insights = []
    
    if completed_auctions > 0:
        completion_rate = (completed_auctions / total_auctions * 100)
        insights.append(f"Auction completion rate stands at {completion_rate:.1f}%, indicating {'strong' if completion_rate > 70 else 'moderate'} operational efficiency.")
    
    if draft_auctions > total_auctions * 0.3:
        insights.append(f"High number of draft auctions ({draft_auctions}) suggests potential for increased catalog activation.")
    
    if pending_auctions > 0:
        insights.append(f"{pending_auctions} auctions pending approval require attention to maintain pipeline flow.")
    
    avg_lots = total_lots / total_auctions if total_auctions > 0 else 0
    if avg_lots < 10:
        insights.append(f"Average lot count per auction ({avg_lots:.1f}) is relatively low. Consider consolidating smaller auctions.")
    elif avg_lots > 50:
        insights.append(f"High average lot count ({avg_lots:.1f}) per auction. Excellent catalog depth.")
    
    # Most successful type
    type_values = {
        'live': sum(a.total_value or 0 for a in auctions.filter(auction_type='live')),
        'scheduled': sum(a.total_value or 0 for a in auctions.filter(auction_type='scheduled')),
        'timed': sum(a.total_value or 0 for a in auctions.filter(auction_type='timed'))
    }
    best_type = max(type_values, key=type_values.get)
    insights.append(f"{best_type.title()} auctions generate the highest total value at {format_inr(type_values[best_type])}.")

    elements.append(Paragraph("Key Insights:", heading3_style))
    
    for idx, insight in enumerate(insights, 1):
        insight_para = Paragraph(f"{idx}. {insight}", body_style)
        elements.append(insight_para)
        elements.append(Spacer(1, 8))
    
    elements.append(Spacer(1, 15))
    elements.append(Paragraph("Strategic Recommendations:", heading3_style))
    
    recommendations = [
        "Continue to diversify auction types to maximize market reach and accommodate different buyer preferences.",
        "Maintain focus on high-value auctions while ensuring adequate lot quantity to attract broader participation.",
        "Implement systematic approval workflows to reduce pending auction backlog and improve time-to-market.",
        "Monitor completion rates and identify factors contributing to auction cancellations for process improvement.",
        "Leverage seasonal trends identified in timeline analysis for optimal auction scheduling.",
        "Consider implementing buyer premium optimization strategies based on auction type performance data.",
    ]
    
    for idx, rec in enumerate(recommendations, 1):
        rec_para = Paragraph(f"{idx}. {rec}", body_style)
        elements.append(rec_para)
        elements.append(Spacer(1, 8))
    
    elements.append(PageBreak())

    # ============ OPERATIONAL METRICS ============
    elements.append(Paragraph("11. OPERATIONAL METRICS", heading2_style))
    elements.append(Spacer(1, 12))

    # Creator performance
    from collections import Counter
    creator_counts = Counter(a.created_by.username for a in auctions if a.created_by)
    top_creators = creator_counts.most_common(10)
    
    elements.append(Paragraph("Top Auction Creators", heading3_style))
    
    creator_data = [["Creator", "Auctions Created", "Percentage"]]
    for creator, count in top_creators:
        creator_data.append([
            creator,
            str(count),
            f"{(count/total_auctions*100):.1f}%"
        ])
    
    creator_table = Table(creator_data, colWidths=[2.5*inch, 1.5*inch, 2*inch])
    creator_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(creator_table)
    elements.append(Spacer(1, 20))

    # Approval metrics
    approved_with_approver = auctions.filter(approved_by__isnull=False)
    if approved_with_approver.exists():
        elements.append(Paragraph("Approval Activity", heading3_style))
        
        approver_counts = Counter(a.approved_by.username for a in approved_with_approver)
        top_approvers = approver_counts.most_common(5)
        
        approver_data = [["Approver", "Approvals"]]
        for approver, count in top_approvers:
            approver_data.append([approver, str(count)])
        
        approver_table = Table(approver_data, colWidths=[3*inch, 2*inch])
        approver_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0392b')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(approver_table)
    
    elements.append(PageBreak())

    # ============ AUCTION SETTINGS ANALYSIS ============
    elements.append(Paragraph("12. AUCTION SETTINGS & CONFIGURATION", heading2_style))
    elements.append(Spacer(1, 12))

    # Proxy bidding stats
    proxy_enabled = auctions.filter(allow_proxy_bidding=True).count()
    proxy_disabled = total_auctions - proxy_enabled

    settings_data = [
        ["Configuration", "Count", "Percentage"],
        ["Proxy Bidding Enabled", str(proxy_enabled), f"{(proxy_enabled/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
        ["Proxy Bidding Disabled", str(proxy_disabled), f"{(proxy_disabled/total_auctions*100 if total_auctions > 0 else 0):.1f}%"],
    ]

    settings_table = Table(settings_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
    settings_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2980b9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(settings_table)
    elements.append(Spacer(1, 20))

    # Buyer premium analysis
    elements.append(Paragraph("Buyer Premium Configuration", heading3_style))
    
    premium_ranges = {
        '0%': auctions.filter(buyer_premium_percentage=0).count(),
        '1-10%': auctions.filter(buyer_premium_percentage__gt=0, buyer_premium_percentage__lte=10).count(),
        '11-20%': auctions.filter(buyer_premium_percentage__gt=10, buyer_premium_percentage__lte=20).count(),
        '20%+': auctions.filter(buyer_premium_percentage__gt=20).count(),
    }
    
    premium_data = [["Premium Range", "Count"]]
    for range_name, count in premium_ranges.items():
        premium_data.append([range_name, str(count)])
    
    premium_table = Table(premium_data, colWidths=[3*inch, 2*inch])
    premium_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16a085')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(premium_table)

    # ============ FOOTER & DISCLAIMERS ============
    elements.append(PageBreak())
    elements.append(Spacer(1, 100))
    
    elements.append(Paragraph("REPORT DISCLAIMERS & NOTES", heading2_style))
    elements.append(Spacer(1, 20))
    
    disclaimer_text = """
    <b>Confidentiality Notice:</b><br/>
    This report contains confidential and proprietary information of the auction house. 
    It is intended solely for internal use and authorized personnel. Unauthorized distribution, 
    copying, or disclosure of this report is strictly prohibited.
    <br/><br/>
    <b>Data Accuracy:</b><br/>
    All data presented in this report is current as of the generation timestamp indicated on the cover page. 
    The information is compiled from the auction management system and represents the most accurate available data 
    at the time of generation. Values and statistics are subject to change as auctions progress and new data is recorded.
    <br/><br/>
    <b>Financial Calculations:</b><br/>
    Commission estimates are based on standard buyer's premium percentages and may not reflect actual realized commissions. 
    Consult detailed financial records for precise revenue figures. All currency values are presented in Indian Rupees (INR).
    <br/><br/>
    <b>Recommendations:</b><br/>
    Strategic recommendations provided in this report are based on historical data analysis and industry best practices. 
    Implementation should consider current market conditions, regulatory requirements, and specific business objectives.
    <br/><br/>
    <b>Report Generation:</b><br/>
    This report was automatically generated by the Auction Management System. For questions or clarifications 
    regarding the data presented, please contact the system administrator or auction house management.
    <br/><br/>
    <b>Version Information:</b><br/>
    Report Version: 2.0<br/>
    System: Auction Management Platform<br/>
    Generated: {generation_time}<br/>
    Generated By: {generated_by}
    """.format(
        generation_time=timezone.now().strftime('%d %B %Y at %H:%M:%S'),
        generated_by=request.user.get_full_name() or request.user.username if hasattr(request, 'user') else "System"
    )
    
    elements.append(Paragraph(disclaimer_text, ParagraphStyle(
        'Disclaimer',
        parent=body_style,
        fontSize=9,
        textColor=colors.HexColor('#555555'),
        alignment=TA_JUSTIFY,
        leading=12
    )))
    
    elements.append(Spacer(1, 30))
    
    # Footer signature
    signature_text = """
    <br/><br/>
    _____________________________________________<br/>
    <b>Authorized Signature</b><br/>
    Auction House Management
    """
    
    elements.append(Paragraph(signature_text, ParagraphStyle(
        'Signature',
        parent=body_style,
        fontSize=10,
        alignment=TA_CENTER
    )))

    # Build PDF
    doc.build(elements, canvasmaker=NumberedCanvas)
    return response




@login_required
def auctions_list(request):
    """List all auctions with filtering"""
    # Get all auctions
    auctions = Auction.objects.all().select_related('created_by', 'approved_by')
    
    # Filter based on user permissions
    if not request.user.is_staff:
        # Non-staff users only see approved/live/scheduled/completed auctions
        # and their own auctions
        auctions = auctions.filter(
            Q(status__in=['approved', 'live', 'scheduled', 'completed']) |
            Q(created_by=request.user)
        )
    
    # Update auction statuses (in case they've changed)
    for auction in auctions:
        if auction.status in ['approved', 'scheduled', 'live']:
            auction.update_auction_status()
            auction.save()
    
    # Calculate counts for filters
    live_count = auctions.filter(status='live').count()
    scheduled_count = auctions.filter(status='scheduled').count()
    approved_count = auctions.filter(status='approved').count()
    pending_count = auctions.filter(status='pending').count()
    completed_count = auctions.filter(status='completed').count()
    
    context = {
        'auctions': auctions,
        'live_count': live_count,
        'scheduled_count': scheduled_count,
        'approved_count': approved_count,
        'pending_count': pending_count,
        'completed_count': completed_count,
    }
    
    return render(request, 'auctions/auctions_list.html', context)


@staff_member_required
def get_items_by_category(request):
    category_id = request.GET.get("category_id")
    items = Item.objects.filter(category_id=category_id)

    data = [
        {"id": i.id, "text": f"{i.title} - ₹{i.price} ({i.status})"}
        for i in items
    ]
    return JsonResponse(data, safe=False)


def view_lots(request):
    lots = Lot.objects.all()
    return render(request, 'lots/view_lots.html', {'lots': lots,'counts':Lot.all_status_count()})

def lot_detail(request,lot_id):
    lot = Lot.objects.filter(id = lot_id)
    return render(request,'lots/lot_detail.html',{'lot':lot})