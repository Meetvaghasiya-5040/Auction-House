"""
Email utility for sending delivery and pickup status notifications
"""
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
import threading

def send_email_async(subject, html_content, recipient_list):
    def send():
        try:
            email = EmailMessage(
                subject=subject,
                body=html_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipient_list,
            )
            email.content_subtype = 'html'
            email.send(fail_silently=False)
            print(f"✅ Async email sent to: {recipient_list}")
        except Exception as e:
            print(f"❌ Error sending async email: {e}")
            
    import threading
    # Use daemon=False so the Python interpreter gives it a moment to finish before terminating
    threading.Thread(target=send, daemon=False).start()


def send_pickup_confirmed_email(item):
    try:
        seller = item.owner
        subject = f'✅ Item Picked Up - {item.title}'
        
        context = {
            'seller_name': seller.get_full_name() or seller.username,
            'item': item,
        }
        
        html_message = render_to_string('auction_list/emails/pickup_confirmed.html', context)
        plain_message = f"""
            Dear {context['seller_name']},

            Your item has been successfully picked up by our courier!

            Item: {item.title}
            Pickup OTP: {item.pickup_otp}
            Status: Picked Up

            Your item is now on its way to our warehouse. We'll notify you once it arrives.

            Best regards,
            Auction House Team
        """
        
        html_message = render_to_string('auction_list/emails/pickup_confirmed.html', context)
        
        send_email_async(subject, html_message, [seller.email])
        print(f"✅ Pickup confirmation email queued for seller: {seller.email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending pickup confirmed email: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_item_at_warehouse_email(item):
    try:
        print(f"📧 Attempting to send warehouse email for item: {item.id} - {item.title}")
        seller = item.owner
        print(f"   Seller: {seller.email}")
        # Get buyer from lot - find any lot containing this item
        lot = item.lots.first()
        print(f"   Found lot: {lot.id if lot else 'None'} (status: {lot.status if lot else 'N/A'})")
        
        # If no lot found, we can still notify the seller, but we can't notify the buyer
        if not lot:
            print(f"⚠️ No lot found for item {item.id}. Sending email to seller only.")
            buyer = None
        elif not lot.winning_bidder:
            print(f"⚠️ Lot {lot.id} has no winning bidder. Sending email to seller only.")
            buyer = None
        else:
            buyer = lot.winning_bidder
            print(f"   Buyer: {buyer.email}")
            
        # Email to seller
        subject_seller = f'📦 Item Arrived at Warehouse - {item.title}'
        context_seller = {
            'user_name': seller.get_full_name() or seller.username,
            'item': item,
            'lot': lot, # May be None
            'is_seller': True,
        }
        
        html_message_seller = render_to_string('auction_list/emails/item_at_warehouse.html', context_seller)
        
        html_message_seller = render_to_string('auction_list/emails/item_at_warehouse.html', context_seller)
        
        send_email_async(subject_seller, html_message_seller, [seller.email])
        print(f"✅ Warehouse email queued for seller: {seller.email}")
        
        # Email to buyer (only if buyer exists)
        if buyer:
            subject_buyer = f'📦 Your Item is at Warehouse - Lot #{lot.lot_number}'
            context_buyer = {
                'user_name': buyer.get_full_name() or buyer.username,
                'item': item,
                'lot': lot,
                'is_seller': False,
            }
            
            html_message_buyer = render_to_string('auction_list/emails/item_at_warehouse.html', context_buyer)
            
            html_message_buyer = render_to_string('auction_list/emails/item_at_warehouse.html', context_buyer)
            
            send_email_async(subject_buyer, html_message_buyer, [buyer.email])
            print(f"✅ Warehouse email queued for buyer: {buyer.email}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error sending item at warehouse email: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_lot_ready_for_delivery_email(lot):
    try:
        buyer = lot.winning_bidder
        subject = f'🚀 Your Lot is Ready for Delivery - Lot #{lot.lot_number}'
        
        context = {
            'buyer_name': buyer.get_full_name() or buyer.username,
            'lot': lot,
            'items': lot.items.all(),
        }
        
        html_message = render_to_string('auction_list/emails/lot_ready_for_delivery.html', context)
        plain_message = f"""
                Dear {context['buyer_name']},

                Great news! All items in your lot are now at our warehouse and ready for delivery.

                Lot #{lot.lot_number}: {lot.title}
                Items: {lot.items.count()} item(s)

                Your lot will be shipped to you soon. We'll send you tracking information once it's dispatched.

                Best regards,
                Auction House Team
        """
        
        html_message = render_to_string('auction_list/emails/lot_ready_for_delivery.html', context)
        
        send_email_async(subject, html_message, [buyer.email])
        print(f"✅ Lot ready email queued for buyer: {buyer.email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending lot ready for delivery email: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_lot_shipped_email(lot, delivery):
    """
    Send email to buyer when lot is shipped
    
    Args:
        lot: Lot object that was shipped
        delivery: Delivery object with OTP
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        buyer = lot.winning_bidder
        subject = f'🚚 Your Lot is Out for Delivery - Lot #{lot.lot_number}'
        
        context = {
            'buyer_name': buyer.get_full_name() or buyer.username,
            'lot': lot,
            'delivery': delivery,
            'items': lot.items.all(),
        }
        
        html_message = render_to_string('auction_list/emails/lot_shipped.html', context)
        plain_message = f"""
Dear {context['buyer_name']},

Your lot is now out for delivery!

Lot #{lot.lot_number}: {lot.title}
Delivery OTP: {delivery.verification_code}

Please keep this OTP ready. You'll need to share it with the courier upon delivery.

Estimated delivery: 3-5 business days

Best regards,
Auction House Team
        """
        
        html_message = render_to_string('auction_list/emails/lot_shipped.html', context)
        
        send_email_async(subject, html_message, [buyer.email])
        print(f"✅ Lot shipped email queued for buyer: {buyer.email}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending lot shipped email: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_lot_delivered_email(lot):
    """
    Send email to buyer and seller when lot is delivered
    
    Args:
        lot: Lot object that was delivered
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        buyer = lot.winning_bidder
        seller = lot.items.first().owner if lot.items.exists() else None
        
        # Email to buyer
        subject_buyer = f'✅ Delivery Complete - Lot #{lot.lot_number}'
        context_buyer = {
            'user_name': buyer.get_full_name() or buyer.username,
            'lot': lot,
            'items': lot.items.all(),
            'is_buyer': True,
        }
        
        html_message_buyer = render_to_string('auction_list/emails/lot_delivered.html', context_buyer)
        
        html_message_buyer = render_to_string('auction_list/emails/lot_delivered.html', context_buyer)
        
        send_email_sync(subject_buyer, html_message_buyer, [buyer.email])
        print(f"✅ Delivery complete email queued for buyer: {buyer.email}")
        
        # Email to seller
        if seller:
            subject_seller = f'✅ Item Delivered - {lot.title}'
            context_seller = {
                'user_name': seller.get_full_name() or seller.username,
                'lot': lot,
                'items': lot.items.all(),
                'is_buyer': False,
            }
            
            html_message_seller = render_to_string('auction_list/emails/lot_delivered.html', context_seller)
            
            html_message_seller = render_to_string('auction_list/emails/lot_delivered.html', context_seller)
            
            send_email_async(subject_seller, html_message_seller, [seller.email])
            print(f"✅ Delivery complete email queued for seller: {seller.email}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error sending lot delivered email: {e}")
        import traceback
        traceback.print_exc()
        return False
