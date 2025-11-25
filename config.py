import os
from datetime import datetime

# Bot Configuration (Pulled from Render Environment Variables)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Admins: convert comma-separated ENV string into a list of integers
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().isdigit()]

# Payment
BTC_WALLET_ADDRESS = os.getenv("BTC_WALLET", "")

# Google Sheets
SHEET_CREDENTIALS_FILE = "credentials.json"  # Render will read this file
SHEET_URL = os.getenv("SHEET_URL", "")

# Database
DB_PATH = "shop_bot.db"

# Bot States
class States:
    CATEGORY = 1
    PRODUCTS = 2
    CART = 3
    CHECKOUT_NAME = 4
    CHECKOUT_PHONE = 5
    CHECKOUT_ADDRESS = 6
    ADMIN_MENU = 10
    ADMIN_ADD_PRODUCT_NAME = 11
    ADMIN_ADD_PRODUCT_DESC = 12
    ADMIN_ADD_PRODUCT_PRICE = 13
    ADMIN_ADD_PRODUCT_CATEGORY = 14
    ADMIN_ADD_PRODUCT_BRAND = 15
    ADMIN_ADD_PRODUCT_IMAGE = 16
    ADMIN_BROADCAST = 17
    ADMIN_EDIT_PRODUCT_SELECT = 18
    ADMIN_EDIT_PRODUCT_FIELD = 19
    ADMIN_EDIT_PRODUCT_VALUE = 20
    ADMIN_DELETE_PRODUCT_CONFIRM = 21
    ADMIN_BROADCAST_MESSAGE = 22

# Categories and Brands (Admin can add more via interface)
CATEGORIES = ["Electronics", "Clothing", "Books", "Home"]
BRANDS = ["Brand A", "Brand B", "Brand C", "Brand D"]
