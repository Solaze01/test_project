import logging
import sqlite3
from telegram.error import BadRequest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from config import BOT_TOKEN, ADMIN_IDS, States, BTC_WALLET_ADDRESS, DB_PATH
from database import db
from utils import sheets, generate_order_id, format_cart_items
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== NOTIFICATION FUNCTIONS ==========
async def notify_admins_new_order(context: ContextTypes.DEFAULT_TYPE, order_data, username=None):
    """Notify all admins about new order with customer contact info and order details"""
    text = f"🆕 *NEW ORDER RECEIVED!*\n\n"
    text += f"📦 *Order ID:* {order_data['order_id']}\n"
    text += f"👤 *Customer:* {order_data['name']}\n"
    text += f"📞 *Phone:* {order_data['phone']}\n"
    
    # Add username if available
    if username:
        text += f"👥 *Telegram:* @{username}\n"
    
    text += f"💰 *Total:* ${order_data['total']:.2f}\n"
    text += f"💳 *Payment Method:* {order_data.get('payment_method', 'Unknown')}\n"
    text += f"📊 *Status:* {order_data['status'].upper()}\n\n"
    text += f"📍 *Address:* {order_data['address']}\n\n"
    
    # Add ordered items with names and quantities
    text += "🛍️ *ORDER ITEMS:*\n"
    try:
        items = json.loads(order_data['items_json'])
        for item in items:
            product_name = item.get('name', 'Unknown Product')
            quantity = item.get('quantity', 1)
            price = item.get('price', 0)
            item_total = price * quantity
            text += f"• {product_name} x{quantity} - ${item_total:.2f}\n"
    except Exception as e:
        logger.error(f"Error parsing order items: {e}")
        text += "• Error loading order items\n"
    
    # Add special instructions for custom payment
    if order_data.get('payment_method') == 'custom':
        text += f"\n⚠️ *CUSTOM PAYMENT REQUIRES MANUAL FOLLOW-UP*\n"
        if username:
            text += f"💬 Contact customer directly: @{username}\n"
        else:
            text += f"💬 Contact customer via phone: {order_data['phone']}\n"
        text += f"📞 Reach out to arrange payment details"
    
    keyboard = [
        [InlineKeyboardButton("📊 View Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")]
    ]
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

async def notify_user_order_update(context: ContextTypes.DEFAULT_TYPE, user_id, order_id, new_status):
    """Notify user about order status update with better formatting"""
    status_messages = {
        'paid': "✅ *Payment Confirmed!*\n\nYour order is now being processed and prepared for shipping.",
        'shipped': "🚚 *Order Shipped!*\n\nYour order is on the way! You'll receive it soon.",
        'completed': "🎉 *Order Delivered!*\n\nThank you for your purchase! We hope you enjoy your products.",
        'cancelled': "❌ *Order Cancelled*\n\nPlease contact support if you have any questions."
    }
    
    message = status_messages.get(new_status, f"Order status updated to: {new_status.upper()}")
    
    text = f"📦 *Order Update*\n\n"
    text += f"🆔 *Order ID:* {order_id}\n"
    text += f"📊 *New Status:* {new_status.upper()}\n\n"
    text += message
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")


# ========== USER FLOW ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Categories", callback_data="browse_categories")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name} to our Shop Bot!\n\n"
        "Browse categories, add items to cart, and checkout securely.",
        reply_markup=reply_markup
    )

async def browse_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    categories = db.get_categories()
    keyboard = []
    
    for category in categories:
        keyboard.append([InlineKeyboardButton(category, callback_data=f"category_{category}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📂 *Select a Category:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("category_", "")
    products = db.get_products_by_category(category)
    
    if not products:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="browse_categories")]]
        # Use safe_edit_message instead of edit_message_text
        await safe_edit_message(
            query,
            f"❌ No products found in {category} category.",
            InlineKeyboardMarkup(keyboard)
        )
        return
    
    keyboard = []
    for product in products:
        product_id, name, description, price, brand, image_file_id = product
        keyboard.append([InlineKeyboardButton(
            f"{name} - ${price:.2f}", 
            callback_data=f"product_{product_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="browse_categories")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Use safe_edit_message instead of edit_message_text
    await safe_edit_message(
        query,
        f"📦 *Products in {category}:*\nSelect a product to view details:",
        reply_markup,
        parse_mode='Markdown'
    )

async def show_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("product_", ""))
    product = db.get_product(product_id)
    
    if not product:
        await query.edit_message_text("❌ Product not found.")
        return
    
    id, name, description, price, category, brand, image_file_id, created_at, is_active = product
    
    text = f"*{name}*\n\n"
    text += f"📝 *Description:* {description}\n"
    text += f"💰 *Price:* ${price:.2f}\n"
    text += f"🏷️ *Brand:* {brand}\n"
    text += f"📂 *Category:* {category}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart_{product_id}")],
        [InlineKeyboardButton("📂 Back to Category", callback_data=f"category_{category}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if image_file_id:
        # If we're coming from a text message, delete it first
        try:
            await query.message.delete()
        except BadRequest:
            pass  # If we can't delete, just continue
        
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=image_file_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # Use safe_edit_message for text-only products
        await safe_edit_message(
            query,
            text,
            reply_markup,
            parse_mode='Markdown'
        )

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("add_to_cart_", ""))
    user_id = query.from_user.id
    
    db.add_to_cart(user_id, product_id)
    
    # Show quick confirmation and then cart
    await query.message.reply_text("✅ Item added to cart!")
    
    # Then show the cart
    await view_cart(update, context)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
        message = query.message
    else:
        # Handle case when called from add_to_cart directly
        user_id = update.effective_user.id
        message = None
    
    cart_items = db.get_cart(user_id)
    cart_text, total = format_cart_items(cart_items)
    
    keyboard = []
    
    if cart_items:
        # Add +/- buttons for each item
        for item in cart_items:
            product_id, name, price, quantity, _ = item
            keyboard.append([
                InlineKeyboardButton(f"➖", callback_data=f"decrease_{product_id}"),
                InlineKeyboardButton(f"➕", callback_data=f"increase_{product_id}")
            ])
            keyboard.append([
                InlineKeyboardButton(f"❌ Remove {name}", callback_data=f"remove_{product_id}")
            ])
        
        keyboard.append([InlineKeyboardButton("💰 Checkout", callback_data="checkout_start")])
        keyboard.append([InlineKeyboardButton("🛒 Continue Shopping", callback_data="browse_categories")])
    else:
        keyboard.append([InlineKeyboardButton("🛒 Start Shopping", callback_data="browse_categories")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query and message and message.text:
        # Only edit if the message has text (not a photo with caption)
        try:
            await query.edit_message_text(
                cart_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except BadRequest:
            # If we can't edit (e.g., photo message), send a new one
            await query.message.reply_text(
                cart_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        # Send new message in all other cases
        if query:
            await query.message.reply_text(
                cart_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=cart_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

async def increase_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("increase_", ""))
    user_id = query.from_user.id
    
    # Add one more of the same product
    db.add_to_cart(user_id, product_id)
    
    # Refresh cart view
    await view_cart(update, context)

async def decrease_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("decrease_", ""))
    user_id = query.from_user.id
    
    # Get current quantity
    cart_items = db.get_cart(user_id)
    current_quantity = 0
    for item in cart_items:
        if item[0] == product_id:
            current_quantity = item[3]
            break
    
    if current_quantity > 1:
        # If more than 1, decrease quantity by removing one
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE cart SET quantity = quantity - 1 
            WHERE user_id = ? AND product_id = ?
        ''', (user_id, product_id))
        conn.commit()
        conn.close()
    else:
        # If only 1, remove the item completely
        db.remove_from_cart(user_id, product_id)
    
    # Refresh cart view
    await view_cart(update, context)

async def remove_from_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("remove_", ""))
    user_id = query.from_user.id
    
    db.remove_from_cart(user_id, product_id)
    
    # Refresh cart view
    await view_cart(update, context)

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🛒 *Checkout Process*\n\n"
        "Please enter your *full name*:",
        parse_mode='Markdown'
    )
    return States.CHECKOUT_NAME

async def checkout_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checkout_name'] = update.message.text
    
    await update.message.reply_text(
        "📞 Now please enter your *phone number*:",
        parse_mode='Markdown'
    )
    return States.CHECKOUT_PHONE

async def checkout_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checkout_phone'] = update.message.text
    
    await update.message.reply_text(
        "🏠 Please enter your *shipping address*:",
        parse_mode='Markdown'
    )
    return States.CHECKOUT_ADDRESS

async def checkout_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checkout_address'] = update.message.text
    
    # Show payment options
    keyboard = [
        [InlineKeyboardButton("₿ Bitcoin (BTC)", callback_data="payment_btc")],
        [InlineKeyboardButton("💳 Custom Payment", callback_data="payment_custom")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="view_cart")]
    ]
    
    await update.message.reply_text(
        "💳 *Select Payment Method:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def process_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    payment_method = query.data.replace("payment_", "")
    user_id = query.from_user.id
    username = query.from_user.username  # Get the customer's username
    
    # Get cart items and total
    cart_items = db.get_cart(user_id)
    cart_text, total = format_cart_items(cart_items)
    
    # Generate order
    order_id = generate_order_id()
    items_json = json.dumps([{
        'product_id': item[0],
        'name': item[1],
        'price': item[2],
        'quantity': item[3]
    } for item in cart_items])
    
    # Create order in database
    db.create_order(
        order_id=order_id,
        user_id=user_id,
        customer_name=context.user_data['checkout_name'],
        customer_phone=context.user_data['checkout_phone'],
        customer_address=context.user_data['checkout_address'],
        items_json=items_json,
        total_amount=total,
        payment_method=payment_method
    )
    
    # Prepare order data for sheets and notifications
    from datetime import datetime
    order_data = {
        'order_id': order_id,
        'user_id': user_id,
        'name': context.user_data['checkout_name'],
        'phone': context.user_data['checkout_phone'],
        'address': context.user_data['checkout_address'],
        'items_json': items_json,
        'total': total,
        'status': 'pending',
        'payment_method': payment_method,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Sync to Google Sheets with error handling
    try:
        sheets.add_order(order_data)
        sheets_success = True
    except Exception as e:
        logger.error(f"Google Sheets error: {e}")
        sheets_success = False
    
    # Clear cart
    db.clear_cart(user_id)
    
    # Send order confirmation to user with proper formatting
    if payment_method == 'btc':
        text = f"✅ *Order Confirmed!*\n\n"
        text += f"📦 *Order ID:* `{order_id}`\n"
        text += f"💰 *Total Amount:* `${total:.2f}`\n"
        text += f"₿ *Payment Method:* Bitcoin\n\n"
        text += f"*Please send exactly `${total:.2f}` worth of BTC to:*\n"
        text += f"`{BTC_WALLET_ADDRESS}`\n\n"
        text += "📍 *After Payment:*\n"
        text += "• Your order status will update to 'PAID'\n"
        text += "• We'll process and ship your order\n"
        text += "• You'll receive notifications at each stage"
        
    else:  # custom payment
        text = f"✅ *Order Confirmed!*\n\n"
        text += f"📦 *Order ID:* `{order_id}`\n"
        text += f"💰 *Total Amount:* `${total:.2f}`\n"
        text += f"💳 *Payment Method:* Custom Payment\n\n"
        text += "📍 *Next Steps:*\n"
        text += "• We will contact you shortly for payment details\n"
        text += "• Your order status is currently 'PENDING'\n"
        text += "• You'll receive updates as we process your order"
        
        # Add username hint if user doesn't have one
        if not username:
            text += f"\n\n💡 *Tip:* Add a username to your Telegram account for faster communication"
    
    if not sheets_success:
        text += "\n\n⚠️ *Note:* Order tracking is temporarily delayed. Admin has been notified."
    
    keyboard = [[InlineKeyboardButton("🏠 Back to Main Menu", callback_data="back_to_main")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    # Notify admins about new order - PASS THE USERNAME
    await notify_admins_new_order(context, order_data, username)

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    orders = db.get_user_orders(user_id)
    
    if not orders:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
        await query.edit_message_text(
            "📦 You have no orders yet.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📦 *Your Orders:*\n\n"
    
    for order in orders:
        # order contains: order_id, items_json, total_amount, status, created_at
        order_id = order[0]
        items_json = order[1]
        total = order[2]
        status = order[3]
        created_at = order[4]
        
        text += f"🆔 *Order ID:* {order_id}\n"
        text += f"💰 *Total:* ${total:.2f}\n"
        text += f"📊 *Status:* {status.upper()}\n"
        text += f"📅 *Date:* {created_at}\n"
        text += "─" * 20 + "\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ========== ADMIN FLOW ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access denied.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Manage Products", callback_data="admin_manage_products")],  # NEW
        [InlineKeyboardButton("📊 View Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(
        "👑 *Admin Panel*\n\n"
        "Manage products, orders, and send broadcasts.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ========== ADMIN PRODUCT MANAGEMENT ==========

async def admin_manage_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin product management main menu"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access denied.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📦 Add New Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("✏️ Edit Products", callback_data="admin_edit_products")],
        [InlineKeyboardButton("👁️ View All Products", callback_data="admin_view_products")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        "🛍️ *Product Management*\n\n"
        "Manage your product catalog: add new products, edit existing ones, or view all products.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_view_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all products with management options"""
    query = update.callback_query
    await query.answer()
    
    products = db.get_all_products()
    
    if not products:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_manage_products")]]
        await query.edit_message_text(
            "📦 No products found.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📦 *All Products*\n\n"
    
    for product in products[:10]:  # Show first 10 products
        product_id, name, description, price, category, brand, image_file_id, is_active = product
        status = "✅ Active" if is_active else "❌ Inactive"
        
        text += f"🆔 *{product_id}* - {status}\n"
        text += f"📦 *{name}*\n"
        text += f"💰 ${price:.2f} | 🏷️ {brand} | 📂 {category}\n"
        text += f"📝 {description[:50]}{'...' if len(description) > 50 else ''}\n"
        
        # Action buttons for each product
        text += f"   ✏️ Edit | {'❌ Deactivate' if is_active else '✅ Activate'} | 🗑️ Delete\n"
        text += "─" * 30 + "\n\n"
    
    if len(products) > 10:
        text += f"📋 ... and {len(products) - 10} more products\n\n"
    
    # Create action buttons for products
    keyboard = []
    for product in products[:5]:  # Show buttons for first 5 products
        product_id, name, _, _, _, _, _, is_active = product
        keyboard.append([
            InlineKeyboardButton(f"✏️ {name[:15]}", callback_data=f"admin_edit_select_{product_id}"),
            InlineKeyboardButton(f"{'❌' if is_active else '✅'} Status", callback_data=f"admin_toggle_{product_id}"),
            InlineKeyboardButton(f"🗑️ Delete", callback_data=f"admin_delete_{product_id}")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton("📦 Load More Products", callback_data="admin_load_more_products")],
        [InlineKeyboardButton("🔙 Back to Management", callback_data="admin_manage_products")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_edit_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select product to edit"""
    query = update.callback_query
    await query.answer()
    
    products = db.get_all_products()
    
    if not products:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_manage_products")]]
        await safe_edit_message(
            query,
            "📦 No products found to edit.",
            InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "✏️ *Select Product to Edit*\n\n"
    
    # Show products in a compact list
    for product in products[:15]:
        product_id, name, _, price, category, brand, _, is_active = product
        status = "✅" if is_active else "❌"
        text += f"{status} {product_id}. {name} - ${price:.2f} ({category})\n"
    
    # Create product selection buttons
    keyboard = []
    row = []
    for product in products[:12]:  # Show buttons for first 12 products
        product_id, name, _, _, _, _, _, _ = product
        row.append(InlineKeyboardButton(f"{product_id}", callback_data=f"admin_edit_select_{product_id}"))
        if len(row) == 3:  # 3 buttons per row
            keyboard.append(row)
            row = []
    if row:  # Add remaining buttons
        keyboard.append(row)
    
    keyboard.extend([
        [InlineKeyboardButton("🔍 Search Product", callback_data="admin_search_product")],
        [InlineKeyboardButton("🔙 Back to Management", callback_data="admin_manage_products")]
    ])
    
    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_view_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all products with management options"""
    query = update.callback_query
    await query.answer()
    
    products = db.get_all_products()
    
    if not products:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_manage_products")]]
        await safe_edit_message(
            query,
            "📦 No products found.",
            InlineKeyboardMarkup(keyboard)
        )
        return
    
    text = "📦 *All Products*\n\n"
    
    for product in products[:10]:  # Show first 10 products
        product_id, name, description, price, category, brand, image_file_id, is_active = product
        status = "✅ Active" if is_active else "❌ Inactive"
        
        text += f"🆔 *{product_id}* - {status}\n"
        text += f"📦 *{name}*\n"
        text += f"💰 ${price:.2f} | 🏷️ {brand} | 📂 {category}\n"
        text += f"📝 {description[:50]}{'...' if len(description) > 50 else ''}\n"
        
        # Action buttons for each product
        text += f"   ✏️ Edit | {'❌ Deactivate' if is_active else '✅ Activate'} | 🗑️ Delete\n"
        text += "─" * 30 + "\n\n"
    
    if len(products) > 10:
        text += f"📋 ... and {len(products) - 10} more products\n\n"
    
    # Create action buttons for products
    keyboard = []
    for product in products[:5]:  # Show buttons for first 5 products
        product_id, name, _, _, _, _, _, is_active = product
        keyboard.append([
            InlineKeyboardButton(f"✏️ {name[:15]}", callback_data=f"admin_edit_select_{product_id}"),
            InlineKeyboardButton(f"{'❌' if is_active else '✅'} Status", callback_data=f"admin_toggle_{product_id}"),
            InlineKeyboardButton(f"🗑️ Delete", callback_data=f"admin_delete_{product_id}")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton("📦 Load More Products", callback_data="admin_load_more_products")],
        [InlineKeyboardButton("🔙 Back to Management", callback_data="admin_manage_products")]
    ])
    
    await safe_edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_edit_select_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select which field to edit for a product"""
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("admin_edit_select_", ""))
    product = db.get_product(product_id)
    
    if not product:
        # Use reply_text instead of edit_message_text to avoid the error
        await query.message.reply_text("❌ Product not found.")
        return
    
    id, name, description, price, category, brand, image_file_id, created_at, is_active = product
    
    context.user_data['editing_product_id'] = product_id
    
    text = f"✏️ *Editing Product #{product_id}*\n\n"
    text += f"📦 *Name:* {name}\n"
    text += f"📝 *Description:* {description}\n"
    text += f"💰 *Price:* ${price:.2f}\n"
    text += f"📂 *Category:* {category}\n"
    text += f"🏷️ *Brand:* {brand}\n"
    text += f"📊 *Status:* {'✅ Active' if is_active else '❌ Inactive'}\n"
    text += f"🖼️ *Image:* {'✅ Set' if image_file_id else '❌ Not set'}\n\n"
    text += "Select what you want to edit:"
    
    keyboard = [
        [InlineKeyboardButton("📦 Name", callback_data="admin_edit_field_name")],
        [InlineKeyboardButton("📝 Description", callback_data="admin_edit_field_description")],
        [InlineKeyboardButton("💰 Price", callback_data="admin_edit_field_price")],
        [InlineKeyboardButton("📂 Category", callback_data="admin_edit_field_category")],
        [InlineKeyboardButton("🏷️ Brand", callback_data="admin_edit_field_brand")],
        [InlineKeyboardButton("🖼️ Image", callback_data="admin_edit_field_image")],
        [InlineKeyboardButton("🔙 Back to Products", callback_data="admin_edit_products")]
    ]
    
    # Try to edit the message, if it fails, send a new one
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except BadRequest:
        # If we can't edit (e.g., the message is a photo), send a new message
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def safe_edit_message(query, text, reply_markup=None, parse_mode=None):
    """Safely edit a message, handling cases where editing isn't possible"""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        if "no text in the message" in str(e) or "message can't be edited" in str(e):
            # Send a new message instead
            await query.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            # Re-raise other BadRequest errors
            raise e
        
async def admin_edit_field_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle field selection and ask for new value"""
    query = update.callback_query
    await query.answer()
    
    field = query.data.replace("admin_edit_field_", "")
    field_names = {
        'name': 'Product Name',
        'description': 'Description', 
        'price': 'Price',
        'category': 'Category',
        'brand': 'Brand',
        'image': 'Image'
    }
    
    # Map 'image' to 'image_file_id' for database
    db_field = 'image_file_id' if field == 'image' else field
    context.user_data['editing_field'] = db_field
    
    if field == 'image':
        await query.edit_message_text(
            f"🖼️ *Update Product Image*\n\n"
            f"Please send the new product image:",
            parse_mode='Markdown'
        )
        return States.ADMIN_EDIT_PRODUCT_VALUE
    
    await query.edit_message_text(
        f"✏️ *Update {field_names[field]}*\n\n"
        f"Please enter the new {field_names[field].lower()}:",
        parse_mode='Markdown'
    )
    return States.ADMIN_EDIT_PRODUCT_VALUE

async def admin_edit_product_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the new value for product field"""
    field = context.user_data.get('editing_field')
    product_id = context.user_data.get('editing_product_id')
    
    if not field or not product_id:
        await update.message.reply_text("❌ Editing session expired. Please start over.")
        return ConversationHandler.END
    
    if field == 'image_file_id':
        if update.message.photo:
            # Get the highest quality photo (last in the array)
            new_value = update.message.photo[-1].file_id
            logger.info(f"Updating product {product_id} image with file_id: {new_value[:20]}...")
        else:
            await update.message.reply_text("❌ Please send a valid image (as a photo, not a file).")
            return States.ADMIN_EDIT_PRODUCT_VALUE
    else:
        new_value = update.message.text
        
        # Validate price
        if field == 'price':
            try:
                new_value = float(new_value)
                logger.info(f"Updating product {product_id} price to: {new_value}")
            except ValueError:
                await update.message.reply_text("❌ Invalid price. Please enter a valid number (e.g., 29.99):")
                return States.ADMIN_EDIT_PRODUCT_VALUE
        else:
            logger.info(f"Updating product {product_id} {field} to: {new_value}")
    
    # Update the product
    success = db.update_product(product_id, field, new_value)
    
    if success:
        logger.info(f"✅ Successfully updated product {product_id} {field}")
        await update.message.reply_text(f"✅ Product updated successfully!")
        
        # Show the updated product
        product = db.get_product(product_id)
        if product:
            id, name, description, price, category, brand, image_file_id, created_at, is_active = product
            
            text = f"✅ *Product Updated*\n\n"
            text += f"📦 *Name:* {name}\n"
            text += f"📝 *Description:* {description}\n"
            text += f"💰 *Price:* ${price:.2f}\n"
            text += f"📂 *Category:* {category}\n"
            text += f"🏷️ *Brand:* {brand}\n"
            text += f"📊 *Status:* {'✅ Active' if is_active else '❌ Inactive'}\n"
            text += f"🖼️ *Image:* {'✅ Set' if image_file_id else '❌ Not set'}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("✏️ Edit Again", callback_data=f"admin_edit_select_{product_id}")],
                [InlineKeyboardButton("📦 Back to Products", callback_data="admin_manage_products")]
            ]
            
            if image_file_id and field == 'image_file_id':  # Only send image if we just updated it
                try:
                    await context.bot.send_photo(
                        chat_id=update.message.chat_id,
                        photo=image_file_id,
                        caption=text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send product image: {e}")
                    await update.message.reply_text(
                        text + "\n\n⚠️ *Note:* Image updated but couldn't display preview.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
    else:
        logger.error(f"❌ Failed to update product {product_id} field {field}")
        await update.message.reply_text(
            "❌ Failed to update product. Please try again.\n\n"
            "💡 *Tip:* Make sure the product still exists and you have proper permissions."
        )
    
    # Clear the editing context
    if 'editing_product_id' in context.user_data:
        del context.user_data['editing_product_id']
    if 'editing_field' in context.user_data:
        del context.user_data['editing_field']
    
    return ConversationHandler.END

async def admin_toggle_product_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle product active/inactive status"""
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("admin_toggle_", ""))
    new_status = db.toggle_product_status(product_id)
    
    if new_status is not None:
        status_text = "activated" if new_status else "deactivated"
        await query.edit_message_text(f"✅ Product #{product_id} {status_text} successfully!")
        
        # Return to products view
        await admin_view_products(update, context)
    else:
        await query.edit_message_text(f"❌ Failed to update product status.")

async def admin_delete_product_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm product deletion"""
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.replace("admin_delete_", ""))
    product = db.get_product(product_id)
    
    if not product:
        await query.edit_message_text("❌ Product not found.")
        return
    
    id, name, description, price, category, brand, image_file_id, created_at, is_active = product
    
    context.user_data['deleting_product_id'] = product_id
    
    text = f"🗑️ *Confirm Product Deletion*\n\n"
    text += f"📦 *Product:* {name}\n"
    text += f"💰 *Price:* ${price:.2f}\n"
    text += f"📂 *Category:* {category}\n"
    text += f"🏷️ *Brand:* {brand}\n\n"
    text += f"⚠️ *This action cannot be undone!*"
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Delete Product", callback_data="admin_delete_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_manage_products")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete product from database"""
    query = update.callback_query
    await query.answer()
    
    product_id = context.user_data.get('deleting_product_id')
    
    if not product_id:
        await query.edit_message_text("❌ No product selected for deletion.")
        return
    
    success = db.delete_product(product_id)
    
    if success:
        await query.edit_message_text(f"✅ Product #{product_id} deleted successfully!")
        
        # Return to products management
        await admin_manage_products(update, context)
    else:
        await query.edit_message_text(f"❌ Failed to delete product. It might be referenced in existing orders.")

async def admin_add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📦 *Add New Product*\n\n"
        "Enter product name:",
        parse_mode='Markdown'
    )
    return States.ADMIN_ADD_PRODUCT_NAME

async def admin_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_product_name'] = update.message.text
    
    await update.message.reply_text(
        "Enter product description:",
        parse_mode='Markdown'
    )
    return States.ADMIN_ADD_PRODUCT_DESC

async def admin_add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_product_desc'] = update.message.text
    
    await update.message.reply_text(
        "Enter product price (numbers only, e.g., 29.99):",
        parse_mode='Markdown'
    )
    return States.ADMIN_ADD_PRODUCT_PRICE

async def admin_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
        context.user_data['admin_product_price'] = price
        
        # Get categories from both database AND the default categories
        db_categories = db.get_categories()
        # Combine with default categories and remove duplicates
        from config import CATEGORIES
        all_categories = list(set(db_categories + CATEGORIES))
        
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"admin_cat_{cat}")] for cat in all_categories]
        keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="admin_new_category")])
        
        await update.message.reply_text(
            "Select category:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.ADMIN_ADD_PRODUCT_CATEGORY
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Please enter numbers only (e.g., 29.99):")
        return States.ADMIN_ADD_PRODUCT_PRICE

async def admin_add_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_new_category":
        await query.edit_message_text("Enter new category name:")
        return States.ADMIN_ADD_PRODUCT_CATEGORY
    
    category = query.data.replace("admin_cat_", "")
    context.user_data['admin_product_category'] = category
    
    # Get brands from both database AND the default brands
    from config import BRANDS
    # For now, we'll use the default brands, but you can modify this to get from database if needed
    all_brands = BRANDS
    
    keyboard = [[InlineKeyboardButton(brand, callback_data=f"admin_brand_{brand}")] for brand in all_brands]
    keyboard.append([InlineKeyboardButton("➕ New Brand", callback_data="admin_new_brand")])
    
    await query.edit_message_text(
        "Select brand:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ADMIN_ADD_PRODUCT_BRAND

async def admin_add_product_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when admin enters a new category name via text"""
    new_category = update.message.text
    context.user_data['admin_product_category'] = new_category
    
    # Get brands
    from config import BRANDS
    all_brands = BRANDS
    
    keyboard = [[InlineKeyboardButton(brand, callback_data=f"admin_brand_{brand}")] for brand in all_brands]
    keyboard.append([InlineKeyboardButton("➕ New Brand", callback_data="admin_new_brand")])
    
    await update.message.reply_text(
        "Select brand:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ADMIN_ADD_PRODUCT_BRAND

async def admin_add_product_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_new_brand":
        await query.edit_message_text("Enter new brand name:")
        return States.ADMIN_ADD_PRODUCT_BRAND
    
    brand = query.data.replace("admin_brand_", "")
    context.user_data['admin_product_brand'] = brand
    
    await query.edit_message_text(
        "📸 Now send product image (or type /skip to add without image):"
    )
    return States.ADMIN_ADD_PRODUCT_IMAGE

async def admin_add_product_brand_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when admin enters a new brand name via text"""
    new_brand = update.message.text
    context.user_data['admin_product_brand'] = new_brand
    
    await update.message.reply_text(
        "📸 Now send product image (or type /skip to add without image):"
    )
    return States.ADMIN_ADD_PRODUCT_IMAGE

async def admin_add_product_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    image_file_id = None
    
    if update.message.photo:
        image_file_id = update.message.photo[-1].file_id
    elif update.message.text and update.message.text != '/skip':
        await update.message.reply_text("❌ Please send an image or type /skip")
        return States.ADMIN_ADD_PRODUCT_IMAGE
    
    # Add product to database
    product_id = db.add_product(
        name=context.user_data['admin_product_name'],
        description=context.user_data['admin_product_desc'],
        price=context.user_data['admin_product_price'],
        category=context.user_data['admin_product_category'],
        brand=context.user_data['admin_product_brand'],
        image_file_id=image_file_id
    )
    
    await update.message.reply_text(
        f"✅ Product added successfully! (ID: {product_id})"
    )
    
    # Return to admin panel - send a new message instead of trying to edit
    keyboard = [
        [InlineKeyboardButton("🛍️ Manage Products", callback_data="admin_manage_products")],
        [InlineKeyboardButton("📊 View Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")]
    ]
    
    await update.message.reply_text(
        "👑 *Admin Panel*\n\n"
        "Manage products, orders, and send broadcasts.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    return ConversationHandler.END

async def admin_view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    orders = db.get_all_orders()
    
    if not orders:
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        await query.edit_message_text(
            "📊 No orders found.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Show orders in a paginated or categorized way
    text = "📊 *All Orders*\n\n"
    text += "💡 *Tip:* Click status buttons to filter orders\n\n"
    
    # Group orders by status for better organization
    status_groups = {}
    for order in orders:
        # order contains: order_id, user_id, customer_name, customer_phone, customer_address, 
        # items_json, total_amount, status, payment_method, created_at
        status = order[7]  # status is at index 7
        if status not in status_groups:
            status_groups[status] = []
        status_groups[status].append(order)
    
    # Display orders by status group
    for status, orders_in_group in status_groups.items():
        status_emoji = {
            'pending': '⏳',
            'paid': '✅', 
            'shipped': '🚚',
            'completed': '🎉',
            'cancelled': '❌'
        }.get(status, '📦')
        
        text += f"{status_emoji} *{status.upper()}* ({len(orders_in_group)} orders)\n"
        
        for order in orders_in_group[:3]:  # Show first 3 orders per group
            order_id = order[0]
            customer_name = order[2]
            total = order[6]
            text += f"   └ {order_id} - {customer_name} - ${total:.2f}\n"
        
        if len(orders_in_group) > 3:
            text += f"   └ ... and {len(orders_in_group) - 3} more\n"
        text += "\n"
    
    keyboard = [
        [InlineKeyboardButton("⏳ Pending Orders", callback_data="admin_orders_pending")],
        [InlineKeyboardButton("✅ Paid Orders", callback_data="admin_orders_paid")],
        [InlineKeyboardButton("🚚 Shipped Orders", callback_data="admin_orders_shipped")],
        [InlineKeyboardButton("🎉 Completed Orders", callback_data="admin_orders_completed")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_view_orders_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show orders filtered by status with contact info and items"""
    query = update.callback_query
    await query.answer()
    
    status = query.data.replace("admin_orders_", "")
    orders = db.get_all_orders()
    
    # Filter orders by status
    filtered_orders = [order for order in orders if order[7] == status]
    
    if not filtered_orders:
        keyboard = [
            [InlineKeyboardButton("📊 All Orders", callback_data="admin_view_orders")],
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
        ]
        await query.edit_message_text(
            f"📊 No {status} orders found.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    status_emoji = {
        'pending': '⏳',
        'paid': '✅', 
        'shipped': '🚚',
        'completed': '🎉',
        'cancelled': '❌'
    }.get(status, '📦')
    
    text = f"{status_emoji} *{status.upper()} ORDERS*\n\n"
    
    for order in filtered_orders:
        order_id = order[0]
        customer_name = order[2]
        customer_phone = order[3]
        total = order[6]
        order_status = order[7]
        payment_method = order[8]
        created_at = order[9]
        items_json = order[5]  # Get items JSON
        
        text += f"🆔 *{order_id}*\n"
        text += f"👤 *Customer:* {customer_name}\n"
        text += f"📞 *Phone:* {customer_phone}\n"
        text += f"💰 *Total:* ${total:.2f}\n"
        text += f"💳 *Payment:* {payment_method or 'N/A'}\n"
        text += f"📅 *Date:* {created_at}\n"
        
        # Add order items
        try:
            items = json.loads(items_json)
            if items:
                text += f"📦 *Items:* "
                item_list = []
                for item in items[:3]:  # Show first 3 items
                    product_name = item.get('name', 'Unknown')
                    quantity = item.get('quantity', 1)
                    item_list.append(f"{product_name} x{quantity}")
                text += ", ".join(item_list)
                if len(items) > 3:
                    text += f" +{len(items) - 3} more"
                text += "\n"
        except Exception as e:
            logger.error(f"Error parsing items for order {order_id}: {e}")
        
        # Highlight custom payment orders that need attention
        if order_status == 'pending' and payment_method == 'custom':
            text += f"🔔 *REQUIRES MANUAL FOLLOW-UP*\n"
        
        # Add status update buttons
        if order_status == 'pending':
            text += "   ✅ Mark Paid | 🚚 Mark Shipped | ❌ Cancel\n"
        elif order_status == 'paid':
            text += "   🚚 Mark Shipped | 🎉 Complete | ❌ Cancel\n"
        elif order_status == 'shipped':
            text += "   🎉 Mark Completed | ❌ Cancel\n"
        
        text += "─" * 22 + "\n\n"
    
    # Add action buttons for each order
    keyboard = []
    for order in filtered_orders:
        order_id = order[0]
        order_status = order[7]
        payment_method = order[8]
        
        row_buttons = []
        if order_status == 'pending':
            row_buttons.append(InlineKeyboardButton(f"✅ {order_id}", callback_data=f"admin_paid_{order_id}"))
            if payment_method == 'custom':
                row_buttons.append(InlineKeyboardButton(f"💬 Contact", callback_data=f"admin_contact_{order_id}"))
            else:
                row_buttons.append(InlineKeyboardButton(f"🚚 {order_id}", callback_data=f"admin_shipped_{order_id}"))
        elif order_status == 'paid':
            row_buttons.append(InlineKeyboardButton(f"🚚 {order_id}", callback_data=f"admin_shipped_{order_id}"))
            row_buttons.append(InlineKeyboardButton(f"🎉 {order_id}", callback_data=f"admin_completed_{order_id}"))
        elif order_status == 'shipped':
            row_buttons.append(InlineKeyboardButton(f"🎉 {order_id}", callback_data=f"admin_completed_{order_id}"))
        
        if order_status != 'cancelled':
            row_buttons.append(InlineKeyboardButton(f"❌ {order_id}", callback_data=f"admin_cancelled_{order_id}"))
        
        if row_buttons:
            keyboard.append(row_buttons)
    
    keyboard.extend([
        [InlineKeyboardButton("📊 All Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_contact_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contact customer button for custom payment orders with full order details"""
    query = update.callback_query
    await query.answer()
    
    order_id = query.data.replace("admin_contact_", "")
    order = db.get_order_by_id(order_id)
    
    if not order:
        await query.edit_message_text(f"❌ Order {order_id} not found")
        return
    
    customer_name = order[2]
    customer_phone = order[3]
    customer_address = order[4]
    items_json = order[5]
    total = order[6]
    payment_method = order[8]
    
    text = f"📞 *Contact Customer for Order {order_id}*\n\n"
    text += f"👤 *Name:* {customer_name}\n"
    text += f"📞 *Phone:* {customer_phone}\n"
    text += f"📍 *Address:* {customer_address}\n"
    text += f"💰 *Total:* ${total:.2f}\n"
    text += f"💳 *Payment Method:* {payment_method}\n\n"
    
    # Add full order items
    text += "🛍️ *ORDER DETAILS:*\n"
    try:
        items = json.loads(items_json)
        for item in items:
            product_name = item.get('name', 'Unknown Product')
            quantity = item.get('quantity', 1)
            price = item.get('price', 0)
            item_total = price * quantity
            text += f"• {product_name} x{quantity} - ${item_total:.2f}\n"
    except Exception as e:
        logger.error(f"Error parsing order items: {e}")
        text += "• Error loading order items\n"
    
    if payment_method == 'custom':
        text += "\n💡 *Action Required:*\n"
        text += "• Contact customer to arrange payment\n"
        text += "• Discuss available payment options\n"
        text += "• Update order status once payment received\n"
    
    keyboard = [
        [InlineKeyboardButton("📊 Back to Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_update_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    order_id = parts[2]
    status = parts[1]
    
    # Update order status in database
    db.update_order_status(order_id, status)
    
    # ✅ SYNC TO GOOGLE SHEETS
    try:
        sheets.update_order_status(order_id, status)
        sheets_success = True
    except Exception as e:
        logger.error(f"Failed to update sheets for order {order_id}: {e}")
        sheets_success = False
    
    # Notify user about status update
    order = db.get_order_by_id(order_id)
    if order:
        user_id = order[1]  # user_id is at index 1
        await notify_user_order_update(context, user_id, order_id, status)
    
    # Confirm update to admin
    status_emoji = {
        'paid': '✅',
        'shipped': '🚚', 
        'completed': '🎉',
        'cancelled': '❌'
    }.get(status, '📦')
    
    message = f"{status_emoji} *Order {order_id} updated to {status.upper()}*"
    if sheets_success:
        message += "\n✅ Google Sheets updated successfully"
    else:
        message += "\n⚠️ Google Sheets update failed - check manually"
    
    message += "\n\nThe customer has been notified about this status change."
    
    await query.edit_message_text(
        message,
        parse_mode='Markdown'
    )
    
    # Return to orders view after a short delay
    await admin_view_orders(update, context)

# ========== BROADCAST FUNCTIONS ==========

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the broadcast process"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access denied.")
        return
    
    await query.edit_message_text(
        "📢 *Admin Broadcast*\n\n"
        "Please enter your broadcast message. You can include:\n"
        "• Text\n"
        "• Photos\n"
        "• Formatting (Markdown)\n\n"
        "Type /cancel to abort.",
        parse_mode='Markdown'
    )
    return States.ADMIN_BROADCAST_MESSAGE

async def admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process and confirm broadcast message"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied.")
        return ConversationHandler.END
    
    # Store the message in context
    if update.message.text:
        context.user_data['broadcast_message'] = update.message.text
        context.user_data['broadcast_type'] = 'text'
    elif update.message.photo:
        context.user_data['broadcast_photo'] = update.message.photo[-1].file_id
        context.user_data['broadcast_caption'] = update.message.caption or ""
        context.user_data['broadcast_type'] = 'photo'
    else:
        await update.message.reply_text("❌ Unsupported message type. Please send text or photo.")
        return States.ADMIN_BROADCAST_MESSAGE
    
    # Get user count for confirmation
    all_users = db.get_all_users()
    user_count = len(all_users)
    
    # Show preview and confirmation
    if context.user_data['broadcast_type'] == 'text':
        preview_text = f"📢 *BROADCAST PREVIEW*\n\n{context.user_data['broadcast_message']}\n\n"
    else:
        preview_text = f"📢 *BROADCAST PREVIEW*\n\n{context.user_data['broadcast_caption']}\n\n"
    
    preview_text += f"📍 This will be sent to *{user_count} users*.\n\n"
    preview_text += "✅ Confirm to send broadcast?"
    
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Send Broadcast", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ]
    
    if context.user_data['broadcast_type'] == 'text':
        await update.message.reply_text(
            preview_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_photo(
            chat_id=update.message.chat_id,
            photo=context.user_data['broadcast_photo'],
            caption=preview_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    return ConversationHandler.END

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send broadcast to all users"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ Access denied.")
        return
    
    # Get all users
    all_users = db.get_all_users()
    total_users = len(all_users)
    successful_sends = 0
    failed_sends = 0
    
    # Send progress message
    progress_msg = await query.edit_message_text(
        f"📤 Sending broadcast...\n0/{total_users} users"
    )
    
    # Send broadcast to all users
    broadcast_type = context.user_data.get('broadcast_type')
    
    for i, user in enumerate(all_users):
        user_id = user[0]
        
        try:
            if broadcast_type == 'text':
                await context.bot.send_message(
                    chat_id=user_id,
                    text=context.user_data['broadcast_message'],
                    parse_mode='Markdown'
                )
            else:  # photo
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=context.user_data['broadcast_photo'],
                    caption=context.user_data['broadcast_caption'],
                    parse_mode='Markdown'
                )
            successful_sends += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")
            failed_sends += 1
        
        # Update progress every 10 users or at the end
        if (i + 1) % 10 == 0 or (i + 1) == total_users:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=progress_msg.message_id,
                    text=f"📤 Sending broadcast...\n{i + 1}/{total_users} users\n"
                         f"✅ Success: {successful_sends}\n"
                         f"❌ Failed: {failed_sends}"
                )
            except:
                pass  # Ignore edit errors
    
    # Send final result
    result_text = f"🎉 *Broadcast Completed!*\n\n"
    result_text += f"📊 *Results:*\n"
    result_text += f"• ✅ Successful: {successful_sends} users\n"
    result_text += f"• ❌ Failed: {failed_sends} users\n"
    result_text += f"• 📱 Total: {total_users} users\n\n"
    
    if failed_sends > 0:
        result_text += "💡 *Note:* Failed sends are usually due to users who blocked the bot or haven't started a chat."
    
    keyboard = [[InlineKeyboardButton("👑 Back to Admin", callback_data="admin_panel")]]
    
    await context.bot.edit_message_text(
        chat_id=query.message.chat_id,
        message_id=progress_msg.message_id,
        text=result_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    # Clear broadcast data
    if 'broadcast_message' in context.user_data:
        del context.user_data['broadcast_message']
    if 'broadcast_photo' in context.user_data:
        del context.user_data['broadcast_photo']
    if 'broadcast_caption' in context.user_data:
        del context.user_data['broadcast_caption']
    if 'broadcast_type' in context.user_data:
        del context.user_data['broadcast_type']

async def admin_broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel broadcast"""
    query = update.callback_query
    await query.answer()
    
    # Clear broadcast data
    if 'broadcast_message' in context.user_data:
        del context.user_data['broadcast_message']
    if 'broadcast_photo' in context.user_data:
        del context.user_data['broadcast_photo']
    if 'broadcast_caption' in context.user_data:
        del context.user_data['broadcast_caption']
    if 'broadcast_type' in context.user_data:
        del context.user_data['broadcast_type']
    
    await query.edit_message_text(
        "❌ Broadcast cancelled.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 Back to Admin", callback_data="admin_panel")]])
    )

# ========== UTILITY HANDLERS ==========

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Categories", callback_data="browse_categories")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Use safe_edit_message to handle both text and photo messages
    await safe_edit_message(
        query,
        f"👋 Welcome {user.first_name} to our Shop Bot!\n\n"
        "Browse categories, add items to cart, and checkout securely.",
        reply_markup
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def main():
    # Print a startup message
    print("🚀 Starting Crypto Store Bot...")

    # Initialize application WITHOUT Updater (fixes the crash)
    application = Application.builder().token(BOT_TOKEN).updater(None).build()
    
    # Conversation handlers - DEFINE THEM FIRST
    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout_start$")],
        states={
            States.CHECKOUT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_name)],
            States.CHECKOUT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_phone)],
            States.CHECKOUT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_address)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False  # Add this to fix the warning
    )
    
    admin_add_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_product_start, pattern="^admin_add_product$")],
        states={
            States.ADMIN_ADD_PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_name)],
            States.ADMIN_ADD_PRODUCT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_desc)],
            States.ADMIN_ADD_PRODUCT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_price)],
            States.ADMIN_ADD_PRODUCT_CATEGORY: [
                CallbackQueryHandler(admin_add_product_category, pattern="^admin_cat_|admin_new_category$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_category_text)
                ],
            States.ADMIN_ADD_PRODUCT_BRAND: [
                CallbackQueryHandler(admin_add_product_brand, pattern="^admin_brand_|admin_new_brand$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_brand_text)
                ],
            States.ADMIN_ADD_PRODUCT_IMAGE: [MessageHandler(filters.PHOTO | filters.TEXT, admin_add_product_image)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False  # Add this to fix the warning
    )

    # NEW: Broadcast conversation handler
    admin_broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            States.ADMIN_BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT | filters.PHOTO, admin_broadcast_message)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    
    # NEW: Product editing conversation handler - DEFINE IT BEFORE USING
    admin_edit_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_field_select, pattern="^admin_edit_field_")],
        states={
            States.ADMIN_EDIT_PRODUCT_VALUE: [
                MessageHandler(filters.TEXT | filters.PHOTO, admin_edit_product_value)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False  # Add this to fix the warning
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(checkout_conv)
    application.add_handler(admin_add_product_conv)
    application.add_handler(admin_broadcast_conv) 
    application.add_handler(admin_edit_product_conv)  # NOW THIS WILL WORK
    
    # Callback query handlers - FIXED ORDER
    application.add_handler(CallbackQueryHandler(browse_categories, pattern="^browse_categories$"))
    application.add_handler(CallbackQueryHandler(show_products, pattern="^category_"))
    application.add_handler(CallbackQueryHandler(show_product_detail, pattern="^product_"))
    application.add_handler(CallbackQueryHandler(add_to_cart, pattern="^add_to_cart_"))
    application.add_handler(CallbackQueryHandler(view_cart, pattern="^view_cart$"))
    application.add_handler(CallbackQueryHandler(increase_quantity, pattern="^increase_"))
    application.add_handler(CallbackQueryHandler(decrease_quantity, pattern="^decrease_"))
    application.add_handler(CallbackQueryHandler(remove_from_cart, pattern="^remove_"))
    application.add_handler(CallbackQueryHandler(process_payment, pattern="^payment_"))
    application.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    
    # NEW PRODUCT MANAGEMENT HANDLERS
    application.add_handler(CallbackQueryHandler(admin_manage_products, pattern="^admin_manage_products$"))
    application.add_handler(CallbackQueryHandler(admin_view_products, pattern="^admin_view_products$"))
    application.add_handler(CallbackQueryHandler(admin_edit_products, pattern="^admin_edit_products$"))
    application.add_handler(CallbackQueryHandler(admin_edit_select_product, pattern="^admin_edit_select_"))
    application.add_handler(CallbackQueryHandler(admin_toggle_product_status, pattern="^admin_toggle_"))
    application.add_handler(CallbackQueryHandler(admin_delete_product_confirm, pattern="^admin_delete_[0-9]+$"))
    application.add_handler(CallbackQueryHandler(admin_delete_product, pattern="^admin_delete_confirm$"))
    
    # FIXED: Add order status handlers BEFORE the general view orders handler
    application.add_handler(CallbackQueryHandler(admin_view_orders_by_status, pattern="^admin_orders_"))
    application.add_handler(CallbackQueryHandler(admin_update_order_status, pattern="^admin_(paid|shipped|completed|cancelled)_"))
    application.add_handler(CallbackQueryHandler(admin_contact_customer, pattern="^admin_contact_"))
    application.add_handler(CallbackQueryHandler(admin_view_orders, pattern="^admin_view_orders$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_confirm, pattern="^broadcast_confirm$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_cancel, pattern="^broadcast_cancel$"))
    
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))

    # Start the bot
    print("🤖 Bot is running...")
    application.run_polling()

if __name__ == "__main__":

    main()
