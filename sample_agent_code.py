"""Sample code 'written by agent' for review purposes."""

def calculate_discount(price, user_type):
    """Calculate discount based on user type."""
    if user_type == "premium":
        discount = 0.2
    elif user_type == "vip":
        discount = 0.5
    elif user_type == "regular":
        discount = 0.05
    else:
        discount = 0
    
    final_price = price * (1 - discount)
    return final_price


def process_order(items, user):
    """Process a list of order items."""
    total = 0
    for item in items:
        total += item["price"] * item["quantity"]
    
    discounted = calculate_discount(total, user.get("type", "regular"))
    tax = discounted * 0.08
    
    return {
        "subtotal": total,
        "discount_applied": total - discounted,
        "tax": tax,
        "grand_total": discounted + tax,
    }


def validate_user(user):
    """Validate user data."""
    required = ["id", "email", "type"]
    for field in required:
        if field not in user:
            return False, f"Missing field: {field}"
    
    valid_types = ["regular", "premium", "vip"]
    if user["type"] not in valid_types:
        return False, f"Invalid type: {user['type']}"
    
    return True, None
