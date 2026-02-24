from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from bids.models import Bid

def calculate_shipping_fee(weight, item_value, source_city, source_state, dest_city=None, dest_state=None):
    """
    Calculate shipping fee based on weight, value, and distance.
    Formula:
    - BaseFee = ₹80
    - RatePerKg = ₹40 * Weight
    - DistanceFee: 
      - Same city = ₹50
      - Same state = ₹100
      - Different state = ₹180
    - FuelSurcharge = ₹30
    - InsuranceFee = 1% of ItemValue
    """
    if dest_city is None:
        dest_city = getattr(settings, 'WAREHOUSE_CITY', 'Ahmedabad')
    if dest_state is None:
        dest_state = getattr(settings, 'WAREHOUSE_STATE', 'Gujarat')
        
    # Ensure inputs are Decimals/Floats
    weight = Decimal(str(weight or 0))
    item_value = Decimal(str(item_value or 0))
    
    # 1. Base Fee
    base_fee = Decimal('80.00')
    
    # 2. Weight Fee
    weight_fee = Decimal('40.00') * weight
    
    # 3. Distance Fee
    distance_fee = Decimal('180.00') # Default: Different State
    
    if source_city and dest_city and source_city.lower() == dest_city.lower():
        distance_fee = Decimal('50.00')
    elif source_state and dest_state and source_state.lower() == dest_state.lower():
        distance_fee = Decimal('100.00')
        
    # 4. Fuel Surcharge
    fuel_surcharge = Decimal('30.00')
    
    # 5. Insurance Fee (1% of Item Value)
    insurance_fee = item_value * Decimal('0.01')
    
    total_fee = base_fee + weight_fee + distance_fee + fuel_surcharge + insurance_fee
    
    return total_fee.quantize(Decimal('0.01'))


def update_hot_status(auction):
    """
    Update hot status for an auction based on bid activity in last 10 minutes.
    An auction is marked as hot if it has received 10+ bids in the last 10 minutes.
    
    Args:
        auction: Auction instance
    
    Returns:
        bool: True if auction is hot, False otherwise
    """
    
    # Calculate time threshold (10 minutes ago)
    time_threshold = timezone.now() - timedelta(minutes=10)
    
    # Count bids across all lots in this auction in the last 10 minutes
    recent_bid_count = Bid.objects.filter(
        lot__auction=auction,
        timestamp__gte=time_threshold
    ).count()
    
    # Update hot status
    is_hot = recent_bid_count >= 10
    if auction.is_hot != is_hot:
        auction.is_hot = is_hot
        auction.save(update_fields=['is_hot'])
    
    return is_hot


def update_lot_hot_status(lot):
    """
    Update hot status for a lot based on bid activity in last 10 minutes.
    A lot is marked as hot if it has received 10+ bids in the last 10 minutes.
    
    Args:
        lot: Lot instance
    
    Returns:
        bool: True if lot is hot, False otherwise
    """
    from bids.models import Bid
    
    # Calculate time threshold (10 minutes ago)
    time_threshold = timezone.now() - timedelta(minutes=10)
    
    # Count bids on this lot in the last 10 minutes
    recent_bid_count = Bid.objects.filter(
        lot=lot,
        timestamp__gte=time_threshold
    ).count()
    
    # Update hot status
    is_hot = recent_bid_count >= 10
    if lot.is_hot != is_hot:
        lot.is_hot = is_hot
        lot.save(update_fields=['is_hot'])
    
    return is_hot


def get_hot_bid_count(lot):
    """
    Get the number of bids in the last 10 minutes for a lot.
    
    Args:
        lot: Lot instance
    
    Returns:
        int: Number of bids in last 10 minutes
    """
   
    
    time_threshold = timezone.now() - timedelta(minutes=10)
    return Bid.objects.filter(
        lot=lot,
        timestamp__gte=time_threshold
    ).count()
