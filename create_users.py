import sqlite3
import hashlib
from blockchain import Wallet
import os
import json

def get_db():
    conn = sqlite3.connect('project_management.db')
    conn.row_factory = sqlite3.Row
    return conn

def create_user(username, password, role):
    # Tạo ví mới
    wallet = Wallet()
    private_key = wallet.get_private_key()
    public_key = wallet.get_public_key()
    
    # Lưu ví vào file trong thư mục Wallet
    wallet_dir = 'Wallet'
    os.makedirs(wallet_dir, exist_ok=True)
    wallet_file = os.path.join(wallet_dir, f"{username}_wallet.json")
    wallet.save_to_file(wallet_file)
    print(f"Saved wallet for {username} to {wallet_file}")

    # Hash password
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    # Lưu vào cơ sở dữ liệu
    conn = get_db()
    conn.execute('''
        INSERT INTO users (username, password, role, private_key, public_key)
        VALUES (?, ?, ?, ?, ?)
    ''', (username, hashed_password, role, private_key, public_key))
    conn.commit()
    conn.close()
    print(f"Created user: {username} ({role})")

# Create accounts
create_user('admin', '1', 'admin')
create_user('kiet', '1', 'user')
create_user('thien', '1', 'user')
create_user('thang', '1', 'user')
create_user('khanh', '1', 'user')