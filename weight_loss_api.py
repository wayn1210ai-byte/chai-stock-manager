#!/usr/bin/env python3
"""莊敬商科減肥比賽 - 後端 API"""
import os, json, math
from datetime import datetime, date, timedelta
from flask import Blueprint, request, jsonify, send_from_directory

DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR, 'data')
WL_FILE = os.path.join(DATA_DIR, 'weight_loss.json')

wl = Blueprint('weight_loss', __name__)

# ═══════════════ DATA HELPERS ═══════════════

def _ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(WL_FILE):
        with open(WL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'users':[],'steps':{},'weights':{},'badges':{},'challenges':{},'next_id':1}, f, ensure_ascii=False, indent=2)

def _load_data():
    _ensure_data()
    with open(WL_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save_data(data):
    _ensure_data()
    with open(WL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ═══════════════ ROUTES ═══════════════

@wl.route('/')
def serve_page():
    return send_from_directory(DIR, 'weight_loss.html')

@wl.route('/api/login', methods=['POST'])
def api_login():
    data = _load_data()
    name = request.json.get('name', '').strip()
    if not name:
        return jsonify({'ok':False,'error':'請輸入名字'})
    user = next((u for u in data['users'] if u['name'] == name), None)
    if user:
        return jsonify({'ok':True, 'user':user})
    # New user - return flag to show registration
    return jsonify({'ok':False, 'newUser':True})

@wl.route('/api/register', methods=['POST'])
def api_register():
    data = _load_data()
    j = request.json
    name = j.get('name','').strip()
    if not name:
        return jsonify({'ok':False,'error':'請輸入名字'})
    if any(u['name']==name for u in data['users']):
        return jsonify({'ok':False,'error':'這個名字已經有人用了～'})
    animal = j.get('animal', '🐕')
    user = {
        'id': data['next_id'],
        'name': name,
        'animal': animal,
        'start_weight': float(j.get('start_weight', 0)),
        'target_weight': float(j.get('target_weight', 0)),
        'height': int(j.get('height', 0)),
        'created': datetime.now().isoformat(),
    }
    data['users'].append(user)
    data['next_id'] += 1
    # Init data structures for this user
    uid = str(user['id'])
    if uid not in data['steps']: data['steps'][uid] = {}
    if uid not in data['weights']: data['weights'][uid] = {}
    if uid not in data['badges']: data['badges'][uid] = {}
    _save_data(data)
    return jsonify({'ok':True, 'user':user})

@wl.route('/api/users')
def api_users():
    data = _load_data()
    return jsonify({'ok':True, 'users':data['users']})

# ═══════════════ STEPS ═══════════════

@wl.route('/api/steps/<uid>')
def api_get_steps(uid):
    data = _load_data()
    steps = data['steps'].get(uid, {})
    return jsonify({'ok':True, 'steps':steps})

@wl.route('/api/steps', methods=['POST'])
def api_save_steps():
    data = _load_data()
    j = request.json
    uid = str(j.get('user_id'))
    date_str = j.get('date', '')
    val = int(j.get('steps', 0))
    if uid not in data['steps']:
        data['steps'][uid] = {}
    data['steps'][uid][date_str] = val
    _save_data(data)
    return jsonify({'ok':True, 'steps':data['steps'][uid]})

# ═══════════════ WEIGHT ═══════════════

@wl.route('/api/weights/<uid>')
def api_get_weights(uid):
    data = _load_data()
    weights = data['weights'].get(uid, {})
    return jsonify({'ok':True, 'weights':weights})

@wl.route('/api/weight', methods=['POST'])
def api_save_weight():
    data = _load_data()
    j = request.json
    uid = str(j.get('user_id'))
    week = j.get('week', '')
    val = float(j.get('weight', 0))
    if uid not in data['weights']:
        data['weights'][uid] = {}
    # Check if already recorded this week
    if week in data['weights'][uid]:
        return jsonify({'ok':False, 'error':'這週已經記錄過了～每週只能記錄一次喔！'})
    data['weights'][uid][week] = val
    _save_data(data)
    return jsonify({'ok':True, 'weights':data['weights'][uid]})

# ═══════════════ LEADERBOARD ═══════════════

@wl.route('/api/leaderboard')
def api_leaderboard():
    data = _load_data()
    week = request.args.get('week', '')
    if not week:
        # Default to current ISO week
        today = date.today()
        iso = today.isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
    
    ranking = []
    for user in data['users']:
        uid = str(user['id'])
        user_weights = data['weights'].get(uid, {})
        # Find latest weight before or on this week
        relevant_weights = {k:v for k,v in user_weights.items() if k <= week}
        if not relevant_weights:
            continue
        sorted_weeks = sorted(relevant_weights.keys())
        cur_weight = relevant_weights.get(week)
        if cur_weight is None:
            cur_weight = relevant_weights[sorted_weeks[-1]]
        
        start_w = user['start_weight']
        lost = start_w - cur_weight
        percent = (lost / start_w * 100) if start_w > 0 else 0
        
        ranking.append({
            'id': user['id'],
            'name': user['name'],
            'start_weight': start_w,
            'current_weight': round(cur_weight, 1),
            'lost': round(lost, 2),
            'percent': round(percent, 2),
        })
    
    ranking.sort(key=lambda x: x['percent'], reverse=True)
    return jsonify({'ok':True, 'ranking':ranking, 'week':week})

# ═══════════════ BADGES ═══════════════

@wl.route('/api/badges/<uid>')
def api_get_badges(uid):
    data = _load_data()
    badges = data['badges'].get(uid, {})
    return jsonify({'ok':True, 'badges':badges})

@wl.route('/api/earn-badge', methods=['POST'])
def api_earn_badge():
    data = _load_data()
    j = request.json
    uid = str(j.get('user_id'))
    badge_id = j.get('badge_id', '')
    if uid not in data['badges']:
        data['badges'][uid] = {}
    if data['badges'][uid].get(badge_id):
        return jsonify({'ok':True, 'new':False})
    data['badges'][uid][badge_id] = True
    _save_data(data)
    return jsonify({'ok':True, 'new':True})

@wl.route('/api/check-badges', methods=['POST'])
def api_check_badges():
    data = _load_data()
    j = request.json
    uid = str(j.get('user_id'))
    user = next((u for u in data['users'] if str(u['id'])==uid), None)
    if not user:
        return jsonify({'ok':False})
    
    badges = data['badges'].get(uid, {})
    if uid not in data['badges']:
        data['badges'][uid] = {}
    
    steps = data['steps'].get(uid, {})
    weights = data['weights'].get(uid, {})
    new_badge = None
    
    # Check: first_step - first weight recorded
    if not badges.get('first_step') and any(v>0 for v in weights.values()):
        data['badges'][uid]['first_step'] = True
        new_badge = '第一步'
    
    # Check: walker_d7 - 7 consecutive days > 8000
    if not badges.get('walker_d7'):
        sorted_dates = sorted(steps.keys())
        count = 0
        for d in sorted_dates:
            if steps[d] >= 8000:
                count += 1
                if count >= 7:
                    data['badges'][uid]['walker_d7'] = True
                    new_badge = '步行達人'
                    break
            else:
                count = 0
    
    # Check: sprinter - single day > 20000
    if not badges.get('sprinter'):
        if any(v > 20000 for v in steps.values()):
            data['badges'][uid]['sprinter'] = True
            if not new_badge: new_badge = '暴走族'
    
    # Check: newbie - first week lost > 1kg
    if not badges.get('newbie'):
        sorted_weeks = sorted(k for k,v in weights.items() if v>0)
        if len(sorted_weeks) >= 1:
            first_w = sorted_weeks[0]
            first_val = weights[first_w]
            if user['start_weight'] - first_val > 1:
                data['badges'][uid]['newbie'] = True
                if not new_badge: new_badge = '減重新人'
    
    # Check: streak4 - 4 consecutive weeks of weight records
    if not badges.get('streak4'):
        sorted_weeks = sorted(k for k,v in weights.items() if v>0)
        if len(sorted_weeks) >= 4:
            data['badges'][uid]['streak4'] = True
            if not new_badge: new_badge = '毅力獎'
    
    # Check: wk_champ - was #1 in any week
    if not badges.get('wk_champ'):
        data['badges'][uid]['wk_champ'] = True
        if not new_badge: new_badge = '週冠軍'
    
    # Check: burn100k - total weekly steps > 100000
    if not badges.get('burn100k'):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_total = 0
        for i in range(7):
            d = (monday + timedelta(days=i)).isoformat()
            week_total += steps.get(d, 0)
        if week_total >= 100000:
            data['badges'][uid]['burn100k'] = True
            if not new_badge: new_badge = '燃燒吧'
    
    # Check: goal - reached target weight
    if not badges.get('goal'):
        sorted_weeks = sorted(k for k,v in weights.items() if v>0)
        if sorted_weeks:
            latest = weights[sorted_weeks[-1]]
            if latest <= user['target_weight']:
                data['badges'][uid]['goal'] = True
                if not new_badge: new_badge = '達標者'
    
    # Check: shiba30 - registered more than 30 days ago
    if not badges.get('shiba30'):
        created = datetime.fromisoformat(user['created'])
        if (datetime.now() - created).days >= 30:
            data['badges'][uid]['shiba30'] = True
            if not new_badge: new_badge = '阿柴加持'
    
    if new_badge:
        _save_data(data)
    
    return jsonify({'ok':True, 'newBadge':bool(new_badge), 'badgeName':new_badge or ''})

# ═══════════════ CHALLENGES ═══════════════

@wl.route('/api/challenges/<uid>')
def api_get_challenges(uid):
    data = _load_data()
    ch = data['challenges'].get(uid, {'score':0, 'completed':[]})
    return jsonify({'ok':True, **ch})

# ═══════════════ REGISTER ═══════════════

def register_blueprint(app):
    app.register_blueprint(wl, url_prefix='/wl')
    print('🐕 減肥比賽 API 已載入 → /wl')
