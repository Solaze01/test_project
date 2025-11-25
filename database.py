import sqlite3
import json
from datetime import datetime
from config import DB_PATH

class Database:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Products table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                category TEXT NOT NULL,
                brand TEXT NOT NULL,
                image_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_address TEXT NOT NULL,
                items_json TEXT NOT NULL,
                total_amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                payment_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Cart table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cart (
                user_id INTEGER,
                product_id INTEGER,
                quantity INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, product_id),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_user(self, user_id, username, first_name, last_name):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
        conn.commit()
        conn.close()
    
    def get_all_users(self):
        """Get all users for broadcasting"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, last_name FROM users')
        users = cursor.fetchall()
        conn.close()
        return users
    
    def get_categories(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT category FROM products WHERE is_active = TRUE')
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        return categories or ["Electronics", "Clothing", "Books", "Home"]
    
    def get_products_by_category(self, category):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, description, price, brand, image_file_id 
            FROM products 
            WHERE category = ? AND is_active = TRUE
        ''', (category,))
        products = cursor.fetchall()
        conn.close()
        return products
    
    def get_product(self, product_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        product = cursor.fetchone()
        conn.close()
        return product
    
    def get_all_products(self):
        """Get all products for admin management"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, description, price, category, brand, image_file_id, is_active
            FROM products 
            ORDER BY created_at DESC
        ''')
        products = cursor.fetchall()
        conn.close()
        return products

    def update_product(self, product_id, field, value):
        """Update specific product field with better error handling"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        allowed_fields = ['name', 'description', 'price', 'category', 'brand', 'image_file_id', 'is_active']
        if field not in allowed_fields:
            print(f"❌ Invalid field: {field}")
            conn.close()
            return False
        
        try:
            # Handle different data types
            if field == 'price':
                value = float(value)
            elif field == 'is_active':
                value = bool(value)
            # For image_file_id and other text fields, value is already correct
            
            print(f"🔄 Updating product {product_id} - Field: {field}, Value type: {type(value)}, Value: {str(value)[:50]}...")
            
            # First check if product exists
            cursor.execute('SELECT id FROM products WHERE id = ?', (product_id,))
            if not cursor.fetchone():
                print(f"❌ Product {product_id} not found")
                conn.close()
                return False
            
            # Perform the update
            cursor.execute(f'UPDATE products SET {field} = ? WHERE id = ?', (value, product_id))
            conn.commit()
            
            # Verify the update worked
            cursor.execute(f'SELECT {field} FROM products WHERE id = ?', (product_id,))
            updated_value = cursor.fetchone()[0]
            print(f"✅ Update successful - New value: {str(updated_value)[:50]}...")
            
            conn.close()
            return True
            
        except Exception as e:
            print(f"❌ Error updating product {product_id} field {field}: {e}")
            conn.rollback()
            conn.close()
            return False

    def delete_product(self, product_id):
        """Delete product from database"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting product: {e}")
            conn.close()
            return False

    def toggle_product_status(self, product_id):
        """Toggle product active/inactive status"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            # Get current status
            cursor.execute('SELECT is_active FROM products WHERE id = ?', (product_id,))
            result = cursor.fetchone()
            if result:
                new_status = not result[0]
                cursor.execute('UPDATE products SET is_active = ? WHERE id = ?', (new_status, product_id))
                conn.commit()
                conn.close()
                return new_status
            conn.close()
            return None
        except Exception as e:
            print(f"Error toggling product status: {e}")
            conn.close()
            return None
        
    def add_to_cart(self, user_id, product_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO cart (user_id, product_id, quantity)
            VALUES (?, ?, COALESCE((SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?), 0) + 1)
        ''', (user_id, product_id, user_id, product_id))
        conn.commit()
        conn.close()
    
    def remove_from_cart(self, user_id, product_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM cart WHERE user_id = ? AND product_id = ?', (user_id, product_id))
        conn.commit()
        conn.close()
    
    def get_cart(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.product_id, p.name, p.price, c.quantity, p.image_file_id
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id = ?
        ''', (user_id,))
        cart_items = cursor.fetchall()
        conn.close()
        return cart_items
    
    def update_cart_quantity(self, user_id, product_id, quantity):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if quantity <= 0:
            cursor.execute('DELETE FROM cart WHERE user_id = ? AND product_id = ?', (user_id, product_id))
        else:
            cursor.execute('UPDATE cart SET quantity = ? WHERE user_id = ? AND product_id = ?', 
                          (quantity, user_id, product_id))
        conn.commit()
        conn.close()

    def get_cart_item_quantity(self, user_id, product_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?', (user_id, product_id))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    
    def clear_cart(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def create_order(self, order_id, user_id, customer_name, customer_phone, customer_address, items_json, total_amount, payment_method):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (order_id, user_id, customer_name, customer_phone, customer_address, items_json, total_amount, payment_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (order_id, user_id, customer_name, customer_phone, customer_address, items_json, total_amount, payment_method))
        conn.commit()
        conn.close()
    
    def get_user_orders(self, user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT order_id, items_json, total_amount, status, created_at
            FROM orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
        orders = cursor.fetchall()
        conn.close()
        return orders

    def get_order_by_id(self, order_id):
        """Get order by order_id"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT order_id, user_id, customer_name, customer_phone, customer_address, 
                   items_json, total_amount, status, payment_method, created_at
            FROM orders WHERE order_id = ?
        ''', (order_id,))
        order = cursor.fetchone()
        conn.close()
        return order
    
    def add_product(self, name, description, price, category, brand, image_file_id=None):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO products (name, description, price, category, brand, image_file_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, description, price, category, brand, image_file_id))
        product_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return product_id
    
    def get_all_orders(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT order_id, user_id, customer_name, customer_phone, customer_address, 
                   items_json, total_amount, status, payment_method, created_at
            FROM orders 
            ORDER BY created_at DESC
        ''')
        orders = cursor.fetchall()
        conn.close()
        return orders
    
    def update_order_status(self, order_id, status):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE orders SET status = ? WHERE order_id = ?', (status, order_id))
        conn.commit()
        conn.close()

# Global database instance
db = Database()