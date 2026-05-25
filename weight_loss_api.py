#!/usr/bin/env python3
"""莊敬商科減肥比賽 - 後端 API (PostgreSQL + JSON 雙模式)"""
import os, json, math, re, hashlib
from datetime import datetime, date, timedelta
from flask import Blueprint, request, jsonify, send_from_directory

DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR, 'data')
WL_FILE = os.path.join(DATA_DIR, 'weight_loss.json')
DATABASE_URL = os.environ.get('DATABASE_URL', '') or os.environ.get('RENDER_DATABASE_URL', '') or ''

wl = Blueprint('weight_loss', __name__)

# ═══════════════ DATABASE SETUP ═══════════════

def _fix_render_db_url(url):
    """Fix Render internal hostname - try appending domain suffix"""
    if not url: return url
    import re as _re
    # Try common Render patterns
    hostnames = ['render.com']
    for h in hostnames:
        m = _re.match(r'(postgresql://[^@]+@)([^:]+)(.*)', url)
        if m and '.' not in m.group(2) and m.group(2) != 'localhost':
            return m.group(1) + m.group(2) + '.' + h + m.group(3)
        # Already has dots
        if m and '.' in m.group(2):
            return url
    return url

# Try multiple env var names like stock_server
DATABASE_URL = ''
for key in ['DATABASE_URL', 'RENDER_DATABASE_URL', 'CHAI_STOCK_DB_DATABASE_URL',
            'CHAI_STOCK_DB_URL', 'POSTGRES_URL', 'POSTGRESQL_URL']:
    val = os.environ.get(key, '')
    if val:
        DATABASE_URL = val
        break

DATABASE_URL = _fix_render_db_url(DATABASE_URL)
DB_URL = DATABASE_URL
_use_pg = bool(DB_URL)
_pg_conn = None

def _get_pg():
    global _pg_conn
    if not _use_pg:
        return None
    try:
        import psycopg2
        if _pg_conn and _pg_conn.closed:
            _pg_conn = None
        if not _pg_conn:
            connected = False
            for ssl in ['require', 'allow', 'prefer']:
                try:
                    conn = psycopg2.connect(DB_URL, sslmode=ssl, connect_timeout=10)
                    conn.autocommit = True
                    cur = conn.cursor()
                    cur.execute('SELECT 1')
                    cur.close()
                    connected = True
                    break
                except Exception:
                    continue
            if connected:
                _pg_conn = psycopg2.connect(DB_URL, sslmode='require')
                _pg_conn.autocommit = True
                _init_pg_tables()
            else:
                return None
        return _pg_conn
    except Exception as e:
        print(f'⚠️ WL PostgreSQL connect error: {e}')
        return None

def _init_pg_tables():
    try:
        conn = _get_pg()
        if not conn: return
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wl_users (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                animal TEXT DEFAULT '🐕',
                start_weight REAL DEFAULT 0,
                target_weight REAL DEFAULT 0,
                height INTEGER DEFAULT 0,
                password TEXT DEFAULT '',
                created TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS wl_steps (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES wl_users(id),
                date TEXT NOT NULL,
                value INTEGER DEFAULT 0,
                UNIQUE(user_id, date)
            );
            CREATE TABLE IF NOT EXISTS wl_weights (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES wl_users(id),
                week TEXT NOT NULL,
                value REAL DEFAULT 0,
                UNIQUE(user_id, week)
            );
            CREATE TABLE IF NOT EXISTS wl_badges (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES wl_users(id),
                badge_id TEXT NOT NULL,
                earned BOOLEAN DEFAULT true,
                UNIQUE(user_id, badge_id)
            );
        """)
        cur.close()
    except Exception as e:
        print(f'⚠️ PostgreSQL init error: {e}')

# ═══════════════ DATA HELPERS (PostgreSQL優先, JSON備援) ═══════════════

def _load_users():
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, animal, start_weight, target_weight, height, password, created FROM wl_users ORDER BY id")
            rows = cur.fetchall()
            cur.close()
            return [{'id':r[0],'name':r[1],'animal':r[2],'start_weight':r[3],'target_weight':r[4],'height':r[5],'password':r[6],'created':r[7]} for r in rows]
        except Exception:
            pass
    # JSON fallback
    return _load_json().get('users', [])

def _save_users(users):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wl_users")
            for u in users:
                pw = u.get('password', '')
                cur.execute("INSERT INTO wl_users (id, name, animal, start_weight, target_weight, height, password, created) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                          (u['id'],u['name'],u['animal'],u['start_weight'],u['target_weight'],u['height'],pw,u['created']))
            conn.commit()
            cur.close()
            return
        except Exception:
            pass
    # JSON fallback
    d = _load_json()
    d['users'] = users
    _save_json(d)

def _load_steps(uid):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT date, value FROM wl_steps WHERE user_id=%s", (int(uid),))
            rows = cur.fetchall()
            cur.close()
            return {r[0]:r[1] for r in rows}
        except Exception:
            pass
    d = _load_json()
    return d.get('steps', {}).get(uid, {})

def _save_steps(uid, date_str, val):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO wl_steps (user_id, date, value) VALUES (%s,%s,%s) ON CONFLICT (user_id, date) DO UPDATE SET value=%s",
                       (int(uid), date_str, val, val))
            conn.commit()
            cur.close()
            return
        except Exception:
            pass
    d = _load_json()
    if uid not in d['steps']: d['steps'][uid] = {}
    d['steps'][uid][date_str] = val
    _save_json(d)

def _load_weights(uid):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT week, value FROM wl_weights WHERE user_id=%s", (int(uid),))
            rows = cur.fetchall()
            cur.close()
            return {r[0]:r[1] for r in rows}
        except Exception:
            pass
    d = _load_json()
    return d.get('weights', {}).get(uid, {})

def _save_weight(uid, week, val):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO wl_weights (user_id, week, value) VALUES (%s,%s,%s) ON CONFLICT (user_id, week) DO UPDATE SET value=%s",
                       (int(uid), week, val, val))
            conn.commit()
            cur.close()
            return
        except Exception:
            pass
    d = _load_json()
    if uid not in d['weights']: d['weights'][uid] = {}
    d['weights'][uid][week] = val
    _save_json(d)

def _load_badges(uid):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT badge_id FROM wl_badges WHERE user_id=%s", (int(uid),))
            rows = cur.fetchall()
            cur.close()
            return {r[0]:True for r in rows}
        except Exception:
            pass
    d = _load_json()
    return d.get('badges', {}).get(uid, {})

def _save_badge(uid, badge_id):
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO wl_badges (user_id, badge_id) VALUES (%s,%s) ON CONFLICT (user_id, badge_id) DO NOTHING",
                       (int(uid), badge_id))
            conn.commit()
            cur.close()
            return
        except Exception:
            pass
    d = _load_json()
    if uid not in d['badges']: d['badges'][uid] = {}
    d['badges'][uid][badge_id] = True
    _save_json(d)

def _get_next_id():
    conn = _get_pg()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM wl_users")
            nid = cur.fetchone()[0]
            cur.close()
            return nid
        except Exception:
            pass
    d = _load_json()
    nid = d.get('next_id', 1)
    d['next_id'] = nid + 1
    _save_json(d)
    return nid

# JSON backup helpers
def _ensure_json():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(WL_FILE):
        with open(WL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'users':[],'steps':{},'weights':{},'badges':{},'challenges':{},'next_id':1}, f, ensure_ascii=False, indent=2)

def _load_json():
    _ensure_json()
    with open(WL_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save_json(data):
    _ensure_json()
    with open(WL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ═══════════════ ROUTES ═══════════════

@wl.route('/')
def serve_page():
    return send_from_directory(DIR, 'weight_loss.html')

@wl.route('/api/login', methods=['POST'])
def api_login():
    users = _load_users()
    name = request.json.get('name', '').strip()
    pw = request.json.get('password', '')
    if not name or not pw:
        return jsonify({'ok':False,'error':'請輸入使用者名稱和密碼～'})
    pwh = hashlib.sha256(pw.encode()).hexdigest()
    user = next((u for u in users if u['name'] == name), None)
    if user and user.get('password', '') == pwh:
        # Don't send password hash to client
        u = {k:v for k,v in user.items() if k != 'password'}
        return jsonify({'ok':True, 'user':u})
    return jsonify({'ok':False, 'error':'使用者名稱或密碼錯誤～'})

@wl.route('/api/register', methods=['POST'])
def api_register():
    j = request.json
    name = j.get('name','').strip()
    pw = j.get('password', '')
    if not name:
        return jsonify({'ok':False,'error':'請輸入使用者名稱～'})
    if not pw or len(pw) < 4:
        return jsonify({'ok':False,'error':'密碼至少4碼喔～'})
    users = _load_users()
    if any(u['name']==name for u in users):
        return jsonify({'ok':False,'error':'這個名稱已經有人用了～'})
    nid = _get_next_id()
    animal = j.get('animal', '🐕')
    pwh = hashlib.sha256(pw.encode()).hexdigest()
    user = {
        'id': nid,
        'name': name,
        'password': pwh,
        'animal': animal,
        'start_weight': float(j.get('start_weight', 0)),
        'target_weight': float(j.get('target_weight', 0)),
        'height': int(j.get('height', 0)),
        'created': datetime.now().isoformat(),
    }
    users.append(user)
    _save_users(users)
    # Don't send password hash to client
    u = {k:v for k,v in user.items() if k != 'password'}
    return jsonify({'ok':True, 'user':u})

@wl.route('/api/users')
def api_users():
    return jsonify({'ok':True, 'users':_load_users()})

# ═══════════════ STEPS ═══════════════

@wl.route('/api/steps/<uid>')
def api_get_steps(uid):
    return jsonify({'ok':True, 'steps':_load_steps(uid)})

@wl.route('/api/steps', methods=['POST'])
def api_save_steps():
    j = request.json
    uid = str(j.get('user_id'))
    date_str = j.get('date', '')
    val = int(j.get('steps', 0))
    _save_steps(uid, date_str, val)
    return jsonify({'ok':True, 'steps':_load_steps(uid)})

# ═══════════════ WEIGHT ═══════════════

@wl.route('/api/weights/<uid>')
def api_get_weights(uid):
    return jsonify({'ok':True, 'weights':_load_weights(uid)})

@wl.route('/api/weight', methods=['POST'])
def api_save_weight():
    j = request.json
    uid = str(j.get('user_id'))
    week = j.get('week', '')
    val = float(j.get('weight', 0))
    _save_weight(uid, week, val)
    return jsonify({'ok':True, 'weights':_load_weights(uid)})

# ═══════════════ BADGES ═══════════════

@wl.route('/api/badges/<uid>')
def api_get_badges(uid):
    return jsonify({'ok':True, 'badges':_load_badges(uid)})

@wl.route('/api/badge', methods=['POST'])
def api_earn_badge():
    j = request.json
    uid = str(j.get('user_id'))
    badge_id = j.get('badge_id', '')
    _save_badge(uid, badge_id)
    return jsonify({'ok':True, 'badges':_load_badges(uid)})

# ═══════════════ RANKINGS ═══════════════

@wl.route('/api/rankings')
def api_rankings():
    users = _load_users()
    rankings = []
    for u in users:
        uid = str(u['id'])
        ws = _load_weights(uid)
        sw = u['start_weight']
        vals = [ws[k] for k in sorted(ws.keys()) if ws[k] > 0]
        cw = vals[-1] if vals else sw
        lost = sw - cw
        pct = (lost/sw*100) if sw > 0 else 0
        steps = _load_steps(uid)
        total_steps = sum(steps.values())
        rankings.append({
            'id': u['id'],
            'name': u['name'],
            'animal': u['animal'],
            'start_weight': sw,
            'current_weight': round(cw,1),
            'lost': round(lost,1),
            'percent': round(pct,1),
            'total_steps': total_steps,
        })
    rankings.sort(key=lambda r: r['percent'], reverse=True)
    return jsonify({'ok':True, 'rankings':rankings})

@wl.route('/api/status')
def api_status():
    return jsonify({
        'ok': True,
        'database': 'PostgreSQL' if _use_pg and _get_pg() else 'JSON 檔案',
        'connected': bool(_use_pg and _get_pg()),
    })

# ═══════════════ REGISTER BLUEPRINT ═══════════════

def register_blueprint(app):
    app.register_blueprint(wl, url_prefix='/wl')
