from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from datetime import datetime
import os
from django.conf import settings
from io import BytesIO
from django.utils import timezone
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from .models import Bid, Wallet,Transaction 
from reportlab.platypus import PageBreak    
from auction_list.models import Lot


def download_bid_history_pdf(request):
    """
    Generate and download a PDF of user's complete bid history
    """
    user = request.user
    
    # Create a BytesIO buffer to receive PDF data
    buffer = BytesIO()
    
    # Create the PDF object using ReportLab
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.75*inch,
        bottomMargin=0.5*inch,
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#666666'),
        spaceAfter=20,
        alignment=TA_CENTER,
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold'
    )
    
    # Optional: Add company logo at the top
    # Uncomment and modify the path to your logo image
    # try:
    #     logo = Image('path/to/your/logo.png', width=1.5*inch, height=0.5*inch)
    #     logo.hAlign = 'CENTER'
    #     elements.append(logo)
    #     elements.append(Spacer(1, 0.2*inch))
    # except:
    #     pass
    
    # Header Section
    elements.append(Paragraph("Bid History Report", title_style))
    elements.append(Paragraph(
        f"Generated for: {user.get_full_name() or user.username}", 
        subtitle_style
    ))
    elements.append(Paragraph(
        f"Report Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
        subtitle_style
    ))
    elements.append(Spacer(1, 0.3*inch))
    
    # Wallet Summary Section
    try:
        wallet = user.wallet
        elements.append(Paragraph("Wallet Summary", heading_style))
        
        wallet_data = [
            ['Current Balance:', f'Rs. {wallet.balance:,.2f}'],
            ['Wallet Created:', wallet.created_at.strftime('%B %d, %Y')],
            ['Last Updated:', wallet.updated_at.strftime('%B %d, %Y at %I:%M %p')],
        ]
        
        wallet_table = Table(wallet_data, colWidths=[2.5*inch, 4*inch])
        wallet_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        
        elements.append(wallet_table)
        elements.append(Spacer(1, 0.3*inch))
        
    except Wallet.DoesNotExist:
        elements.append(Paragraph("No wallet found for this user.", styles['Normal']))
        elements.append(Spacer(1, 0.3*inch))
    
    # Bid History Section
    bids = Bid.objects.filter(user=user).select_related(
        'lot', 'lot__auction'
    ).order_by('-timestamp')
    
    elements.append(Paragraph(f"Bid History ({bids.count()} Total Bids)", heading_style))
    
    if bids.exists():
        # Statistics
        winning_bids = bids.filter(is_winning=True)
        won_lots = bids.filter(lot__status='sold', lot__winning_bidder=user)
        
        stats_data = [
            ['Current Winning Bids:', str(winning_bids.count())],
            ['Total Bids Placed:', str(bids.count())],
        ]
        
        stats_table = Table(stats_data, colWidths=[2.5*inch, 4*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f4f8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        
        elements.append(stats_table)
        elements.append(Spacer(1, 0.25*inch))
        
        # Detailed Bid Table
        elements.append(Paragraph("Detailed Bid History", heading_style))
        
        # Table headers
        bid_table_data = [
            ['Date & Time', 'Lot', 'Auction', 'Amount', 'Status']
        ]
        
        # Add bid data
        for bid in bids:
            # Status determination
            if bid.lot.status == 'sold':
                if bid.lot.winning_bidder == user:
                    status = 'WON'
                else:
                    status = 'Lost'
            elif bid.is_winning:
                status = 'Winning'
            else:
                status = 'Outbid'
            
            # Use Paragraph to allow text wrapping instead of truncating with dots
            lot_title = Paragraph(bid.lot.title, styles['Normal'])
            auction_title = Paragraph(bid.lot.auction.title, styles['Normal'])
            
            bid_table_data.append([
                bid.timestamp.strftime('%m/%d/%y %I:%M %p'),
                lot_title,
                auction_title,
                f'Rs. {bid.amount:,.2f}',
                status
            ])
        
        # Create table with column widths
        bid_table = Table(
            bid_table_data,
            colWidths=[1.3*inch, 2*inch, 1.8*inch, 1*inch, 0.9*inch]
        )
        
        # Style the table
        table_style = [
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            
            # Data rows
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Date column
            ('ALIGN', (1, 1), (2, -1), 'LEFT'),     # Lot and Auction columns
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'),    # Amount column
            ('ALIGN', (4, 1), (4, -1), 'CENTER'),   # Status column
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),  # Vertical alignment for wrapped text
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]
        
        # Highlight won bids
        for i, bid in enumerate(bids, start=1):
            if bid.lot.status == 'sold' and bid.lot.winning_bidder == user:
                table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#d4edda')))
                table_style.append(('TEXTCOLOR', (4, i), (4, i), colors.HexColor('#155724')))
                table_style.append(('FONTNAME', (4, i), (4, i), 'Helvetica-Bold'))
        
        bid_table.setStyle(TableStyle(table_style))
        elements.append(bid_table)
        
    else:
        elements.append(Paragraph("No bids placed yet.", styles['Normal']))
    
    elements.append(Spacer(1, 0.3*inch))
    
    # Footer
    elements.append(Spacer(1, 0.4*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    elements.append(Paragraph(
        "This is an automated report. For any discrepancies, please contact support.",
        footer_style
    ))
    elements.append(Paragraph(
        f"Report generated on {timezone.now().strftime('%B %d, %Y at %I:%M %p')}",
        footer_style
    ))
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    
    # Create the HTTP response with PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bid_history_{user.username}_{timezone.now().strftime("%Y%m%d")}.pdf"'
    response.write(pdf)
    
    return response


def transaction_invoice(request):
    user = request.user
    
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.75*inch,
        bottomMargin=0.5*inch,
    )
    
    elements = []
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#666666'),
        spaceAfter=20,
        alignment=TA_CENTER,
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold'
    )
    
    # Optional: Add company logo at the top
    # Uncomment and modify the path to your logo image
    # try:
    #     logo = Image('path/to/your/logo.png', width=1.5*inch, height=0.5*inch)
    #     logo.hAlign = 'CENTER'
    #     elements.append(logo)
    #     elements.append(Spacer(1, 0.2*inch))
    # except:
    #     pass
    
    # Header Section
    elements.append(Paragraph("Transaction History Report", title_style))
    elements.append(Paragraph(
        f"Generated for: {user.get_full_name() or user.username}", 
        subtitle_style
    ))
    elements.append(Paragraph(
        f"Report Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
        subtitle_style
    ))
    elements.append(Spacer(1, 0.3*inch))

    # Wallet Summary Section
    try:
        wallet = user.wallet
        elements.append(Paragraph("Wallet Summary", heading_style))
        
        wallet_data = [
            ['Current Balance:', f'Rs. {wallet.balance:,.2f}'],
            ['Wallet Created:', wallet.created_at.strftime('%B %d, %Y')],
            ['Last Updated:', wallet.updated_at.strftime('%B %d, %Y at %I:%M %p')],
        ]
        
        wallet_table = Table(wallet_data, colWidths=[2.5*inch, 4*inch])
        wallet_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        
        elements.append(wallet_table)
        elements.append(Spacer(1, 0.3*inch))
        
    except Wallet.DoesNotExist:
        elements.append(Paragraph("No wallet found for this user.", styles['Normal']))
        elements.append(Spacer(1, 0.3*inch))

    if hasattr(user, 'wallet'):
        transactions = Transaction.objects.filter(
            wallet=user.wallet
        ).order_by('-timestamp')[:50]  # Last 50 transactions
        
        if transactions.exists():
            elements.append(PageBreak())  # New page for transactions
            elements.append(Paragraph("Recent Transaction History", heading_style))
            elements.append(Spacer(1, 0.15*inch))
            
            # Transaction table
            trans_table_data = [
                ['Date & Time', 'Type', 'Description', 'Amount', 'Balance']
            ]
            
            for trans in transactions:
                # Add prefix for positive/negative
                if trans.amount > 0:
                    amount_color = colors.green
                    amount_prefix = '+'
                else:
                    amount_color = colors.red
                    amount_prefix = '-'
                
                # Use Paragraph for description to allow wrapping
                description = Paragraph(trans.description, styles['Normal'])
                
                trans_table_data.append([
                    trans.timestamp.strftime('%m/%d/%y %I:%M %p'),
                    trans.get_transaction_type_display(),
                    description,
                    Paragraph(
                        f'{amount_prefix} Rs. {abs(trans.amount):,.2f}',
                        ParagraphStyle('amount', textColor=amount_color, parent=styles['Normal'], fontName='Helvetica-Bold')
                    ),
                    f'Rs. {user.wallet.balance:,.2f}'  # Current balance (simplified)
                ])
            
            trans_table = Table(
                trans_table_data,
                colWidths=[1.2*inch, 1.3*inch, 2.3*inch, 1*inch, 1*inch]
            )
            
            trans_table.setStyle(TableStyle([
                # Header
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                
                # Data
                ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                ('ALIGN', (1, 1), (2, -1), 'LEFT'),
                ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),  # Vertical alignment for wrapped text
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ]))
            
            elements.append(trans_table)
    
    # Footer
    elements.append(Spacer(1, 0.4*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=TA_CENTER,
    )
    elements.append(Paragraph(
        "This is an automated report. For any discrepancies, please contact support.",
        footer_style
    ))
    elements.append(Paragraph(
        f"Report generated on {timezone.now().strftime('%B %d, %Y at %I:%M %p')}",
        footer_style
    ))
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    
    # Create the HTTP response with PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Transaction_history_{user.username}_{timezone.now().strftime("%Y%m%d")}.pdf"'
    response.write(pdf)
    
    return response

    

def generate_invoice(lot, winner):


    """
    Generate a beautiful PDF invoice for a won lot using ReportLab
    
    Args:
        lot: Lot object that was won
        winner: User object who won
    
    Returns:
        str: Path to the generated PDF file
    """
    try:
        # Calculate invoice details
        winning_bid = float(lot.current_bid)
        admin_commission = winning_bid * 0.10
        total_amount = winning_bid
        
        # Get all items in the lot
        items = lot.items.all()
        
        # Create invoices directory if it doesn't exist
        invoice_dir = os.path.join(settings.MEDIA_ROOT, 'invoices')
        os.makedirs(invoice_dir, exist_ok=True)
        
        # Generate PDF filename
        pdf_filename = f'invoice_lot_{lot.id}_{winner.id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        pdf_path = os.path.join(invoice_dir, pdf_filename)
        
        # Create PDF document
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Get styles
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#34495e'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#2c3e50')
        )
        
        right_align_style = ParagraphStyle(
            'RightAlign',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#2c3e50')
        )
        
        # Add logo if available (optional)
        # Uncomment and modify if you have a logo
        # logo_path = os.path.join(settings.STATIC_ROOT, 'images', 'logo.png')
        # if os.path.exists(logo_path):
        #     logo = Image(logo_path, width=2*inch, height=1*inch)
        #     elements.append(logo)
        #     elements.append(Spacer(1, 0.3*inch))
        
        # Title
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Invoice details header
        invoice_number = f'INV-{lot.id}-{datetime.now().strftime("%Y%m%d")}'
        invoice_date = datetime.now().strftime('%B %d, %Y')
        
        header_data = [
            [Paragraph(f"<b>Invoice Number:</b> {invoice_number}", normal_style),
             Paragraph(f"<b>Invoice Date:</b> {invoice_date}", right_align_style)],
        ]
        
        header_table = Table(header_data, colWidths=[3.5*inch, 3.5*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Buyer and Auction information
        info_data = [
            [Paragraph("<b>Bill To:</b>", heading_style), 
             Paragraph("<b>Auction Details:</b>", heading_style)],
            [Paragraph(f"{winner.get_full_name() or winner.username}<br/>"
                      f"{getattr(winner, 'email', 'N/A')}<br/>"
                      f"{getattr(winner, 'phone', 'N/A')}", normal_style),
             Paragraph(f"<b>Auction:</b> {lot.auction.title}<br/>"
                      f"<b>Lot Number:</b> {lot.id}<br/>"
                      f"<b>Lot Title:</b> {lot.title}", normal_style)],
        ]
        
        info_table = Table(info_data, colWidths=[3.5*inch, 3.5*inch])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 5),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Items table
        elements.append(Paragraph("Items in Lot", heading_style))
        
        # Table header
        items_data = [
            [Paragraph("<b>Item</b>", normal_style),
             Paragraph("<b>Description</b>", normal_style),
             Paragraph("<b>Quantity</b>", normal_style)]
        ]
        
        # Add items
        for item in items:
            items_data.append([
                Paragraph(str(item.name), normal_style),
                Paragraph(str(getattr(item, 'description', 'N/A'))[:100], normal_style),
                Paragraph(str(getattr(item, 'quantity', 1)), normal_style)
            ])
        
        items_table = Table(items_data, colWidths=[2*inch, 3.5*inch, 1.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')])
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Financial summary
        elements.append(Paragraph("Payment Summary", heading_style))
        
        summary_data = [
            [Paragraph("<b>Winning Bid:</b>", normal_style),
             Paragraph(f"${winning_bid:,.2f}", right_align_style)],
            [Paragraph("<b>Admin Commission (10%):</b>", normal_style),
             Paragraph(f"${admin_commission:,.2f}", right_align_style)],
            [Paragraph("", normal_style), Paragraph("", normal_style)],  # Spacer row
            [Paragraph("<b>Total Amount Due:</b>", heading_style),
             Paragraph(f"<b>${total_amount:,.2f}</b>", 
                      ParagraphStyle('TotalStyle', parent=heading_style, alignment=TA_RIGHT, 
                                   textColor=colors.HexColor('#27ae60'), fontSize=16))]
        ]
        
        summary_table = Table(summary_data, colWidths=[5*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('LINEABOVE', (0, 3), (-1, 3), 2, colors.HexColor('#34495e')),
            ('TOPPADDING', (0, 3), (-1, 3), 10),
            ('BOTTOMPADDING', (0, 2), (-1, 2), 5),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.4*inch))
        
        # Payment terms
        elements.append(Paragraph("Payment Terms & Conditions", heading_style))
        terms_text = """
        Payment is due within 7 days of invoice date. Please make payment via bank transfer 
        or approved payment methods. For any questions regarding this invoice, please contact 
        our billing department. Thank you for your participation in our auction.
        """
        elements.append(Paragraph(terms_text, normal_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        elements.append(Spacer(1, 0.5*inch))
        elements.append(Paragraph(
            f"Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
            footer_style
        ))
        
        # Build PDF
        doc.build(elements)
        
        return pdf_path
        
    except Exception as e:
        print(f"Error generating invoice: {e}")
        return None