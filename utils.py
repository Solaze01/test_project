import gspread
import sqlite3
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
from config import SHEET_CREDENTIALS_FILE, SHEET_URL, DB_PATH

class GoogleSheets:
    def __init__(self):
        self.client = None
        self.sheet = None
        self.init_sheets()
    
    def init_sheets(self):
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(SHEET_CREDENTIALS_FILE, scopes=scopes)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_url(SHEET_URL).sheet1
            
            # Set headers if sheet is empty
            if not self.sheet.get_all_records():
                headers = ["Order ID", "User ID", "Name", "Phone", "Address", "Items JSON", "Total", "Status", "Payment Method", "Date"]
                self.sheet.append_row(headers)
            print("✅ Google Sheets initialized successfully")
        except Exception as e:
            print(f"❌ Google Sheets init error: {e}")
    
    def add_order(self, order_data):
        if not self.sheet:
            print("Google Sheets not initialized")
            return False
        
        try:
            row = [
                order_data['order_id'],
                order_data['user_id'],
                order_data['name'],
                order_data['phone'],
                order_data['address'],
                order_data['items_json'],
                order_data['total'],
                order_data['status'],
                order_data.get('payment_method', 'Unknown'),
                order_data['date']
            ]
            self.sheet.append_row(row)
            print(f"✅ Order {order_data['order_id']} added to Google Sheets")
            return True
        except Exception as e:
            print(f"❌ Google Sheets add error: {e}")
            return False

    def update_order_status(self, order_id, new_status):
        """Update order status in Google Sheets - Working version"""
        if not self.sheet:
            print("Google Sheets not initialized")
            return False
        
        try:
            # Get all records to find the exact row
            records = self.sheet.get_all_records()
            row_number = None
            
            # Find the row number for this order_id
            for i, record in enumerate(records):
                if record.get('Order ID') == order_id:
                    row_number = i + 2  # +2 because header is row 1 and enumerate starts at 0
                    break
            
            if not row_number:
                print(f"❌ Order {order_id} not found in Google Sheets")
                return False
            
            # Update the status cell (column H = column 8)
            # Use the exact range format that gspread expects
            range_name = f"H{row_number}"
            
            # This is the correct way to update a single cell
            self.sheet.update(range_name, [[new_status]])
            
            print(f"✅ Order {order_id} status updated to {new_status} in row {row_number}")
            return True
            
        except Exception as e:
            print(f"❌ Google Sheets update error for {order_id}: {e}")
            return False

    def check_connection(self):
        """Check if Google Sheets connection is working"""
        try:
            if not self.sheet:
                return False, "Sheets not initialized"
            
            records = self.sheet.get_all_records()
            return True, f"Connected successfully - {len(records)} orders found"
        except Exception as e:
            return False, f"Connection failed: {e}"

def generate_order_id():
    """Generate custom order ID like ORD-001, ORD-002"""
    from database import db
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM orders')
    count = cursor.fetchone()[0] + 1
    conn.close()
    return f"ORD-{count:03d}"

def format_cart_items(cart_items):
    """Format cart items for display"""
    if not cart_items:
        return "🛒 *Your Cart is Empty*\n\nAdd some products to get started!", 0
    
    text = "🛒 *Your Cart:*\n\n"
    total = 0
    
    for item in cart_items:
        product_id, name, price, quantity, _ = item
        item_total = price * quantity
        total += item_total
        text += f"📦 *{name}*\n"
        text += f"   💰 Price: ${price:.2f}\n"
        text += f"   📦 Quantity: {quantity}\n"
        text += f"   💵 Subtotal: ${item_total:.2f}\n\n"
    
    text += f"💳 *Cart Total: ${total:.2f}*"
    return text, total

# Global sheets instance
sheets = GoogleSheets()