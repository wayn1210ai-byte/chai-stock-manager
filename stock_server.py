#!/usr/bin/env python3
"""柴柴股票管家 - 完整後端伺服器 (含帳號 + 資料庫 + 股價代理 + Session 認證)"""
import os, json, hashlib, secrets, threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)

app = Flask(__name__, static_folder=DIR, static_url_path='')
app.config['JSON_AS_ASCII'] = False
app.config['SECRET_KEY'] = 'chai-stock-manager-secret-key-2026'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Allow CORS for same-origin and cross-origin in dev
from flask_cors import CORS
CORS(app, supports_credentials=True)

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ---------- USER AUTH ----------
def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_users():
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def get_user_data_path(username):
    return os.path.join(DATA_DIR, f'{username}.json')

def load_user_data(username):
    path = get_user_data_path(username)
    if not os.path.exists(path):
        return {'stocks': [], 'history': []}
    with open(path, 'r') as f:
        return json.load(f)

def save_user_data(username, data):
    path = get_user_data_path(username)
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def require_login():
    user = session.get('user')
    if not user:
        return None
    return user

# ---------- API: AUTH ----------
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    if not username or len(username) < 1:
        return jsonify({'success': False, 'error': '請輸入使用者名稱'})
    if len(password) < 4:
        return jsonify({'success': False, 'error': '密碼至少4碼'})
    with lock:
        users = load_users()
        if username in users:
            return jsonify({'success': False, 'error': '這個名稱已經有人用了～'})
        users[username] = {'password': hash_pw(password)}
        save_users(users)
        save_user_data(username, {'stocks': [], 'history': []})
    session['user'] = username
    return jsonify({'success': True, 'username': username})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    with lock:
        users = load_users()
        if username not in users:
            return jsonify({'success': False, 'error': '找不到這個使用者～'})
        if users[username]['password'] != hash_pw(password):
            return jsonify({'success': False, 'error': '密碼錯誤～'})
    session['user'] = username
    return jsonify({'success': True, 'username': username})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('user', None)
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
def api_me():
    user = session.get('user')
    if user:
        return jsonify({'loggedIn': True, 'username': user})
    return jsonify({'loggedIn': False})

# ---------- API: DATA ----------
@app.route('/api/data', methods=['GET', 'POST'])
def api_data():
    user = require_login()
    if not user:
        return jsonify({'success': False, 'error': '請先登入'}), 401
    if request.method == 'GET':
        data = load_user_data(user)
        # Transform backend format to SPA-compatible format
        spa_stocks = []
        for s in data.get('stocks', []):
            spa_stocks.append({
                'id': s.get('id', s.get('code', '')),
                'stockName': s.get('stockName', s.get('name', '')),
                'shares': s.get('shares', 0),
                'averagePrice': s.get('averagePrice', s.get('buy_price', 0)),
                'currentPrice': s.get('currentPrice', s.get('current_price', s.get('buy_price', 0)))
            })
        spa_history = []
        for h in data.get('history', []):
            spa_history.append({
                'id': h.get('id', ''),
                'timestamp': h.get('timestamp', h.get('date', '')),
                'action': h.get('action', '買入' if h.get('type') == 'buy' else '賣出'),
                'stockName': h.get('stockName', h.get('name', '')),
                'shares': h.get('shares', 0),
                'price': h.get('price', 0)
            })
        return jsonify({'success': True, 'data': {'stocks': spa_stocks, 'history': spa_history}})
    else:
        body = request.get_json()
        if not body or 'stocks' not in body or 'history' not in body:
            return jsonify({'success': False, 'error': '資料格式錯誤'})
        # Transform SPA format back to backend format
        backend_stocks = []
        for s in body.get('stocks', []):
            backend_stocks.append({
                'code': s.get('id', s.get('stockName', '')),
                'name': s.get('stockName', s.get('name', '')),
                'shares': s.get('shares', 0),
                'buy_price': s.get('averagePrice', s.get('avgPrice', 0)),
                'current_price': s.get('currentPrice', s.get('averagePrice', s.get('avgPrice', 0)))
            })
        backend_history = []
        for h in body.get('history', []):
            backend_history.append({
                'id': h.get('id', ''),
                'date': h.get('timestamp', h.get('time', '')),
                'type': 'buy' if h.get('action', '買入') == '買入' else 'sell',
                'name': h.get('stockName', h.get('name', '')),
                'shares': h.get('shares', 0),
                'price': h.get('price', 0)
            })
        with lock:
            save_user_data(user, {'stocks': backend_stocks, 'history': backend_history})
        return jsonify({'success': True})

# ---------- API: STOCK PRICE PROXY ----------
@app.route('/api/stock')
def api_stock():
    import urllib.request
    codes = request.args.get('codes', '')
    if not codes:
        return jsonify({'success': False, 'error': 'Missing codes'})
    code_list = [c.strip() for c in codes.split(',') if c.strip()]
    prices = {}
    for code in code_list:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{code}.TW?range=1d&interval=1d'
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            result = data.get('chart', {}).get('result', [])
            for item in result:
                meta = item.get('meta', {})
                symbol = meta.get('symbol', '').replace('.TW', '')
                price = meta.get('regularMarketPrice')
                if symbol and price:
                    prices[symbol] = price
        except Exception:
            pass
        import time
        time.sleep(0.3)
    return jsonify({'success': True, 'prices': prices})

# ---------- STATIC FILES ----------
@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(DIR, 'shiba-stock', 'assets'), filename)

@app.route('/')
def serve_index():
    return send_from_directory(os.path.join(DIR, 'shiba-stock'), 'index.html')

if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f'🐕 柴柴股票管家 v3 伺服器啟動成功!')
    print(f'📱 本機: http://localhost:{PORT}')
    print(f'📱 內網: http://{local_ip}:{PORT}')
    print(f'🔥 Session 認證 + 資料庫 + 股價代理')
    app.run(host='0.0.0.0', port=PORT, debug=False)
