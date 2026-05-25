#!/usr/bin/env python3
"""柴柴股票管家 - 完整後端伺服器 (PostgreSQL + JSON 雙模式)"""
import os, json, hashlib, threading, re, time, urllib.request, socket
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
from weight_loss_api import register_blueprint as register_wl

PORT = int(os.environ.get('PORT', 8765))
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR, 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
DATABASE_URL = os.environ.get('DATABASE_URL', '') or os.environ.get('RENDER_DATABASE_URL', '') or os.environ.get('CHAI_STOCK_DB_DATABASE_URL', '') or os.environ.get('POSTGRES_URL', '')

# Fix Render internal hostname - try appending domain suffix
import re as _re
def _fix_render_db_url(url):
    """If the hostname lacks a TLD, try appending .render.com"""
    if not url: return url
    m = _re.match(r'(postgresql://[^@]+@)([^:/]+)(.*)', url)
    if m:
        host = m.group(2)
        if '.' not in host:  # no TLD (e.g. dpg-xxx-a)
            for suffix in ['.oregon-postgres.render.com', '.render.com', '.us-east-1.render.com']:
                candidate = m.group(1) + host + suffix + m.group(3)
                try:
                    import socket
                    socket.gethostbyname(host + suffix)
                    print(f'✅ Resolved hostname: {host + suffix}')
                    return candidate
                except:
                    continue
    return url

DATABASE_URL = _fix_render_db_url(DATABASE_URL)
# Write fixed URL back to env so lazy-imported modules (like weight_loss_api) get it
if DATABASE_URL:
    os.environ['DATABASE_URL'] = DATABASE_URL
lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)

# ---------- DATABASE SETUP ----------
use_pg = False
pg_conn = None

if DATABASE_URL:
    try:
        import psycopg2
        # Try connecting with different SSL modes
        connected = False
        last_error = ''
        for ssl in ['require', 'allow', 'prefer']:
            try:
                conn = psycopg2.connect(DATABASE_URL, sslmode=ssl, connect_timeout=10)
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute('SELECT 1')
                cur.close()
                conn.close()
                connected = True
                break
            except Exception as e:
                last_error = str(e)[:60]
                continue
        if connected:
            use_pg = True
            pg_conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            pg_conn.autocommit = True
            cur = pg_conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS stock_data (
                username TEXT NOT NULL,
                data JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (username)
            )
        ''')
        cur.close()
        use_pg = True
        print('✅ PostgreSQL 資料庫連線成功!')
    except Exception as e:
        print(f'⚠️ PostgreSQL 連線失敗，使用 JSON 檔案模式: {e}')
        use_pg = False

# JSON fallback: ensure files exist
if not use_pg:
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({}, f)

app = Flask(__name__, static_folder=DIR, static_url_path='')
app.config['JSON_AS_ASCII'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chai-stock-manager-key-2026')
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
CORS(app, supports_credentials=True)

# Fix stdout encoding
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ---------- STORAGE LAYER ----------
def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def db_load_users():
    """Load all users"""
    if use_pg:
        cur = pg_conn.cursor()
        cur.execute('SELECT username, password FROM users')
        rows = cur.fetchall()
        cur.close()
        return {r[0]: {'password': r[1]} for r in rows}
    else:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)

def db_save_users(users):
    if use_pg:
        cur = pg_conn.cursor()
        for username, data in users.items():
            cur.execute(
                'INSERT INTO users (username, password) VALUES (%s, %s) ON CONFLICT (username) DO UPDATE SET password = %s',
                (username, data['password'], data['password'])
            )
        cur.close()
    else:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

def db_load_data(username):
    """Load user stock data"""
    if use_pg:
        cur = pg_conn.cursor()
        cur.execute('SELECT data FROM stock_data WHERE username = %s', (username,))
        row = cur.fetchone()
        cur.close()
        if row:
            return row[0]
        return {'stocks': [], 'history': []}
    else:
        path = os.path.join(DATA_DIR, f'{username}.json')
        if not os.path.exists(path):
            return {'stocks': [], 'history': []}
        with open(path, 'r') as f:
            return json.load(f)

def db_save_data(username, data):
    if use_pg:
        cur = pg_conn.cursor()
        cur.execute(
            'INSERT INTO stock_data (username, data, updated_at) VALUES (%s, %s, NOW()) '
            'ON CONFLICT (username) DO UPDATE SET data = %s, updated_at = NOW()',
            (username, json.dumps(data, ensure_ascii=False), json.dumps(data, ensure_ascii=False))
        )
        cur.close()
    else:
        path = os.path.join(DATA_DIR, f'{username}.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def require_login():
    user = session.get('user')
    return user

# ---------- AUTH API ----------
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
        users = db_load_users()
        if username in users:
            return jsonify({'success': False, 'error': '這個名稱已經有人用了～'})
        users[username] = {'password': hash_pw(password)}
        db_save_users(users)
        db_save_data(username, {'stocks': [], 'history': []})
    session['user'] = username
    return jsonify({'success': True, 'username': username})

@app.route('/api/login', methods=['POST'])
def api_login():
    # Clear any stale session first
    session.pop('user', None)
    session.clear()
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    with lock:
        users = db_load_users()
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

# ---------- DATA API ----------
def transform_stock_out(s):
    return {
        'id': s.get('id', s.get('code', s.get('stockName', ''))),
        'stockName': s.get('stockName', s.get('name', '')),
        'shares': s.get('shares', 0),
        'averagePrice': s.get('averagePrice', s.get('buy_price', 0)),
        'currentPrice': s.get('currentPrice', s.get('current_price', s.get('buy_price', 0)))
    }

def transform_history_out(h):
    return {
        'id': h.get('id', ''),
        'timestamp': h.get('timestamp', h.get('date', h.get('time', ''))),
        'action': h.get('action', '買入' if h.get('type') == 'buy' else '賣出'),
        'stockName': h.get('stockName', h.get('name', '')),
        'shares': h.get('shares', 0),
        'price': h.get('price', 0)
    }

def transform_stock_in(s):
    return {
        'code': s.get('id', s.get('stockName', '')),
        'name': s.get('stockName', s.get('name', '')),
        'shares': s.get('shares', 0),
        'buy_price': s.get('averagePrice', s.get('avgPrice', 0)),
        'current_price': s.get('currentPrice', s.get('averagePrice', s.get('avgPrice', 0)))
    }

def transform_history_in(h):
    return {
        'id': h.get('id', ''),
        'date': h.get('timestamp', h.get('time', '')),
        'type': 'buy' if h.get('action', '買入') == '買入' else 'sell',
        'name': h.get('stockName', h.get('name', '')),
        'shares': h.get('shares', 0),
        'price': h.get('price', 0)
    }

@app.route('/api/data', methods=['GET', 'POST'])
def api_data():
    user = require_login()
    if not user:
        return jsonify({'success': False, 'error': '請先登入'}), 401
    if request.method == 'GET':
        data = db_load_data(user)
        return jsonify({'success': True, 'data': {
            'stocks': [transform_stock_out(s) for s in data.get('stocks', [])],
            'history': [transform_history_out(h) for h in data.get('history', [])]
        }})
    else:
        body = request.get_json()
        if not body or 'stocks' not in body:
            return jsonify({'success': False, 'error': '資料格式錯誤'})
        with lock:
            data = db_load_data(user)
            data['stocks'] = [transform_stock_in(s) for s in body.get('stocks', [])]
            if 'history' in body:
                data['history'] = [transform_history_in(h) for h in body.get('history', [])]
            db_save_data(user, data)
        return jsonify({'success': True})

# ---------- STOCK PRICE PROXY ----------
@app.route('/api/stock')
def api_stock():
    codes = request.args.get('codes', '')
    if not codes:
        return jsonify({'success': False, 'error': 'Missing codes'})
    code_list = [c.strip() for c in codes.split(',') if c.strip()]
    prices = {}
    for code in code_list:
        price = None
        for suffix in ['.TW', '.TWO']:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?range=1d&interval=1d'
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                for item in data.get('chart', {}).get('result', []):
                    meta = item.get('meta', {})
                    symbol = meta.get('symbol', '').replace('.TW', '').replace('.TWO', '')
                    p = meta.get('regularMarketPrice')
                    if symbol and p:
                        price = p
                        break
                if price:
                    break
            except Exception:
                pass
        if price:
            prices[code] = price
        time.sleep(0.3)
    return jsonify({'success': True, 'prices': prices})

# ---------- STATIC FILES ----------
@app.route('/assets/<path:filename>')
def serve_assets(filename):
    # Serve patched JS if available
    if filename.endswith('.js'):
        patched = os.path.join(DIR, 'shiba-stock', 'assets', filename)
        if os.path.exists(patched):
            return send_from_directory(os.path.join(DIR, 'shiba-stock', 'assets'), filename)
    return send_from_directory(os.path.join(DIR, 'shiba-stock', 'assets'), filename)

@app.route('/api/health')
def api_health():
    db_status = 'disconnected'
    db_mode = 'JSON 檔案'
    
    # Check all possible env var names for database URL
    candidates = ['DATABASE_URL', 'RENDER_DATABASE_URL', 'CHAI_STOCK_DB_DATABASE_URL', 
                  'CHAI_STOCK_DB_URL', 'POSTGRES_URL', 'POSTGRESQL_URL']
    found_vars = {}
    for key in candidates:
        val = os.environ.get(key, '')
        if val:
            found_vars[key] = val[:40] + '...'
        else:
            found_vars[key] = 'NOT SET'
    
    # Show the fixed URL
    fixed_url = DATABASE_URL[:60] + '...' if DATABASE_URL else 'EMPTY'
    
    if DATABASE_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=10)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute('SELECT 1')
            cur.close()
            conn.close()
            db_status = 'connected'
            db_mode = 'PostgreSQL'
        except Exception as e:
            db_status = f'error: {str(e)[:80]}'
    
    return jsonify({
        'status': 'ok',
        'database': db_mode,
        'db_connection': db_status,
        'env_vars': found_vars,
        'fixed_db_url': fixed_url
    })

@app.route('/')
def serve_index():
    return send_from_directory(os.path.join(DIR, 'shiba-stock'), 'index.html')

@app.route('/game')
def serve_game():
    return send_from_directory(DIR, 'game.html')

@app.route('/cats')
def serve_cats():
    return send_from_directory(os.path.join(DIR, 'shiba-stock'), 'cats.html')

@app.route('/heroes')
def serve_heroes():
    return send_from_directory(DIR, 'heroes_td.html')

try:
    register_wl(app)
    print('✅ 減肥比賽路由已註冊')
except Exception as e:
    print(f'⚠️ 減肥比賽路由註冊失敗: {e}')

if __name__ == '__main__':
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    mode = 'PostgreSQL' if use_pg else 'JSON 檔案'
    print(f'🐕 柴柴股票管家 v4 啟動!')
    print(f'📀 儲存模式: {mode}')
    print(f'📱 本機: http://localhost:{PORT}')
    print(f'📱 內網: http://{local_ip}:{PORT}')
    app.run(host='0.0.0.0', port=PORT, debug=False)

