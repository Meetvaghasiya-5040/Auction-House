"""
Email utility for sending winner notifications with invoices
"""
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
import os


def send_winner_email(lot, winner, invoice_path=None):
    """
    Send winner notification email with invoice attachment
    
    Args:
        lot: Lot object that was won
        winner: User object who won
        invoice_path: Path to the generated invoice PDF (optional)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = f'🎉 Congratulations! You Won Lot #{lot.lot_number}'
        
        # Email context
        context = {
            'winner_name': winner.get_full_name() or winner.username,
            'lot': lot,
            'auction': lot.auction,
            'winning_bid': lot.current_bid,
        }
        
        # Render email body
        html_message = render_to_string('bids/emails/winner_notification.html', context)
        plain_message = f"""
Congratulations {context['winner_name']}!

You have won the auction for:
Lot #{lot.lot_number}: {lot.title}

Winning Bid: ₹{lot.current_bid}
Auction: {lot.auction.title}

Please find your invoice attached.

Thank you for participating in our auction!

Best regards,
Auction House Team
        """
        
        # Create email
        email = EmailMessage(
            subject=subject,
            body=plain_message,
            from_email=settings.EMAIL_HOST_USER,
            to=[winner.email],
        )
        
        # Attach invoice if provided
        if invoice_path and os.path.exists(invoice_path):
            email.attach_file(invoice_path)
        
        # Send email
        email.send(fail_silently=False)
        return True
        
    except Exception as e:
        print(f"Error sending winner email: {e}")
        return False
