import os
import html
import secrets
import bcrypt
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import pandas as pd
import re
from datetime import datetime
import json
import xml.etree.ElementTree as ET
from io import BytesIO
from werkzeug.utils import secure_filename
from pathlib import Path
import threading

# הגדרת האפליקציה
app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# הגבלת CORS - רק למקורות מותרים
CORS(app, resources={
    r"/*": {
        "origins": os.environ.get('ALLOWED_ORIGINS', 'http://localhost:5000').split(','),
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True
    }
})

# Rate Limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- סשנים פעילים (מחוברים כעת) ---
ACTIVE_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()
DEFAULT_PERMISSIONS = ['view_dashboards', 'upload', 'save_crm', 'delete']
ALL_PERMISSIONS = ['view_dashboards', 'upload', 'save_crm', 'delete', 'admin']

# --- אחסון משתמשים והפקות (data/users.json, data/productions.json) ---
DATA_DIR = Path(__file__).resolve().parent / 'data'
USERS_PATH = DATA_DIR / 'users.json'
PRODUCTIONS_PATH = DATA_DIR / 'productions.json'
DASHBOARDS_PATH = DATA_DIR / 'dashboards.json'
CLIENTS_PATH = DATA_DIR / 'clients.json'
_DASHBOARDS_LOCK = threading.Lock()
_CLIENTS_LOCK = threading.Lock()

# ADMIN קבוע: שם ADMIN, סיסמה R!2345i
ADMIN_USERNAME = 'ADMIN'
ADMIN_PASSWORD_HASH = bcrypt.hashpw('R!2345i'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
ADMIN_ID = '0'

def _load_users_json():
    try:
        with open(USERS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_users_json(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(USERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_users_dict():
    """מחזיר dict: username -> {password_hash, id, role, created_at, permissions}. כולל ADMIN."""
    out = {
        ADMIN_USERNAME: {
            'password_hash': ADMIN_PASSWORD_HASH,
            'id': ADMIN_ID,
            'role': 'admin',
            'created_at': None,
            'permissions': list(ALL_PERMISSIONS)
        }
    }
    for u in _load_users_json():
        out[u['username']] = {
            'password_hash': u['password_hash'],
            'id': str(u['id']),
            'role': u.get('role', 'user'),
            'created_at': u.get('created_at'),
            'permissions': u.get('permissions') if isinstance(u.get('permissions'), list) else list(DEFAULT_PERMISSIONS)
        }
    return out

def user_by_id(user_id):
    for uname, ud in get_users_dict().items():
        if ud['id'] == str(user_id):
            return (uname, ud)
    return (None, None)

def create_user(username, password):
    users = _load_users_json()
    if any(u['username'] == username for u in users) or username == ADMIN_USERNAME:
        return False, 'משתמש כבר קיים'
    next_id = str(max([int(u['id']) for u in users], default=0) + 1)
    h = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    users.append({
        'username': username, 'password_hash': h, 'id': next_id,
        'role': 'user', 'created_at': datetime.utcnow().isoformat()
    })
    _save_users_json(users)
    return True, next_id

def update_user_password(user_id, new_password):
    users = _load_users_json()
    for u in users:
        if str(u['id']) == str(user_id):
            u['password_hash'] = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            _save_users_json(users)
            return True
    return False

def update_user_permissions(user_id, permissions):
    if str(user_id) == ADMIN_ID:
        return False
    users = _load_users_json()
    for u in users:
        if str(u['id']) == str(user_id):
            u['permissions'] = [p for p in permissions if p in ALL_PERMISSIONS]
            _save_users_json(users)
            return True
    return False

def delete_user(user_id):
    if str(user_id) == ADMIN_ID:
        return False
    users = _load_users_json()
    users = [u for u in users if str(u['id']) != str(user_id)]
    _save_users_json(users)
    return True

def _load_productions_json():
    try:
        with open(PRODUCTIONS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_productions_json(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PRODUCTIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_production(user_id, username, family_name, file_count, file_names=None):
    rec = {
        'user_id': str(user_id), 'username': username,
        'timestamp': datetime.utcnow().isoformat(),
        'family_name': family_name or 'כללי', 'file_count': file_count,
        'file_names': file_names or []
    }
    data = _load_productions_json()
    data.append(rec)
    _save_productions_json(data)

def get_productions(user_id=None, limit=50):
    data = _load_productions_json()
    if user_id is not None:
        data = [p for p in data if p.get('user_id') == str(user_id)]
    data = sorted(data, key=lambda p: p.get('timestamp', ''), reverse=True)
    return data[:limit]

# --- dashboards + clients (MENU_CRM) ---
def _load_dashboards_json():
    try:
        with open(DASHBOARDS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_dashboards_json(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _load_clients_json():
    try:
        with open(CLIENTS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_clients_json(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CLIENTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _next_id(store, prefix):
    today = datetime.utcnow().strftime('%Y%m%d')
    p = prefix + today + '-'
    same = [x for x in store if (x.get('id') or '').startswith(p)]
    return p + str(len(same) + 1).zfill(3)

def _next_crm_key(store=None):
    """מפתח CRM: 9 ספרות בלבד (למשל 000000001), ייחודי."""
    data = store if store is not None else _load_dashboards_json()
    existing = []
    for x in data:
        k = (x.get('crm_key') or '').strip()
        dig = ''.join(c for c in k if c.isdigit())
        if len(dig) == 9 and dig.isdigit():
            existing.append(int(dig))
    nxt = (max(existing, default=0) + 1)
    if nxt > 999999999:
        raise ValueError('CRM_KEY overflow')
    return str(nxt).zfill(9)

def api_list_dashboards(created_by=None):
    data = _load_dashboards_json()
    if created_by is not None:
        data = [d for d in data if d.get('created_by') == str(created_by)]
    return sorted(data, key=lambda d: d.get('created_at', ''), reverse=True)

def api_get_dashboard(dashboard_id):
    data = _load_dashboards_json()
    for d in data:
        if d.get('id') == dashboard_id:
            return d
    return None

def api_delete_dashboard(dashboard_id):
    with _DASHBOARDS_LOCK:
        data = _load_dashboards_json()
        prev = len(data)
        data = [d for d in data if d.get('id') != dashboard_id]
        if len(data) == prev:
            return False
        _save_dashboards_json(data)
    return True

def api_update_dashboard(dashboard_id, family_name=None, raw_data=None):
    with _DASHBOARDS_LOCK:
        data = _load_dashboards_json()
        for d in data:
            if d.get('id') != dashboard_id:
                continue
            if not d.get('crm_key'):
                d['crm_key'] = _next_crm_key(data)
            if family_name is not None:
                d['family_name'] = family_name.strip()
            if raw_data is not None:
                r = (d.get('reports') or [{}])[0]
                if not isinstance(r, dict):
                    r = {}
                r['raw_data'] = {
                    'raw_ins': raw_data.get('raw_ins') if isinstance(raw_data.get('raw_ins'), list) else (r.get('raw_data') or {}).get('raw_ins') or [],
                    'raw_fin': raw_data.get('raw_fin') if isinstance(raw_data.get('raw_fin'), list) else (r.get('raw_data') or {}).get('raw_fin') or [],
                    'members': raw_data.get('members') if isinstance(raw_data.get('members'), dict) else (r.get('raw_data') or {}).get('members') or {}
                }
                r['family'] = d.get('family_name', 'כללי')
                if not d.get('reports'):
                    d['reports'] = []
                d['reports'][0] = r
            _save_dashboards_json(data)
            return True
    return False

def api_create_dashboard(family_name, raw_data, html, insights_report, created_by, file_names=None):
    raw_data = raw_data or {}
    raw_ins = raw_data.get('raw_ins') or []
    raw_fin = raw_data.get('raw_fin') or []
    members = raw_data.get('members') or {}
    if not family_name or (not raw_ins and not raw_fin and not members):
        return None, 'family_name ו-raw_data נדרשים'
    with _CLIENTS_LOCK:
        clients = _load_clients_json()
        client_id = _next_id(clients, 'CLI-')
        clients.append({
            'id': client_id,
            'name': family_name,
            'phone': None,
            'created_at': datetime.utcnow().isoformat(),
            'created_by': str(created_by),
            'notes': None,
            'contact_email': None
        })
        _save_clients_json(clients)
    with _DASHBOARDS_LOCK:
        dashboards = _load_dashboards_json()
        dashboard_id = _next_id(dashboards, 'DSH-')
        crm_key = _next_crm_key(dashboards)
        report = {
            'family': family_name,
            'html': html or '',
            'raw_data': {'raw_ins': raw_ins, 'raw_fin': raw_fin, 'members': members},
            'insights_report': insights_report or {}
        }
        dashboards.append({
            'id': dashboard_id,
            'crm_key': crm_key,
            'client_id': client_id,
            'created_at': datetime.utcnow().isoformat(),
            'created_by': str(created_by),
            'family_name': family_name,
            'reports': [report],
            'file_names': file_names or []
        })
        _save_dashboards_json(dashboards)
    return api_get_dashboard(dashboard_id), None

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    uname, _ = user_by_id(user_id)
    if uname:
        ud = get_users_dict()[uname]
        return User(ud['id'], uname)
    return None

# פונקציית escape ל-HTML (מגנה מפני XSS)
def escape_html(text):
    """מבצע escape לכל התווים המיוחדים ב-HTML"""
    if text is None:
        return ''
    return html.escape(str(text))

def escape_html_attr(text):
    """מבצע escape עבור attributes ב-HTML"""
    if text is None:
        return ''
    text = str(text)
    return html.escape(text).replace('"', '&quot;').replace("'", '&#x27;')

# רשימת קבצים מותרים לסטטיק (מגן מפני Path Traversal). index.html לא כאן – נמסר רק דרך / עם אימות.
ALLOWED_STATIC_FILES = {
    'logo.png', 'דמויות.png', 'דמויות.PNG',
    'style.css', 'app.js', 'client.html', 'AgencyOS_Clean.html', 'AgencyOS_Fixed.html'
}
ALLOWED_STATIC_EXTENSIONS = {'.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.pdf'}

# הגדרות העלאת קבצים
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_UPLOAD_EXTENSIONS = {'.dat', '.csv', '.xlsx', '.xls'}
ALLOWED_MIME_TYPES = {
    'text/csv', 'application/vnd.ms-excel', 
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain', 'application/xml', 'text/xml'
}

# --- תבנית הדוח (HTML) ---
# שינויים: הוספת Chart.js, הוספת סקריפטים לגרף, הוספת עמודת סימולציה, ועיצוב אזור המלצות
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>ניתוח תיק לקוח - {{ family_name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Assistant:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --primary: #2c3e50; --accent: #ec4899; --bg-gray: #f8fafc; }
        body { 
            font-family: 'Assistant', sans-serif; 
            margin: 0; 
            padding: 0; 
            background: #555; 
            color: #333; 
            font-size: 10pt; 
            display: block; 
            direction: rtl;
            text-align: right;
            word-spacing: 0.1em;
            letter-spacing: 0.01em;
            white-space: normal;
            text-rendering: optimizeLegibility;
            unicode-bidi: embed;
        }
        .page-container { width: 210mm; min-height: 297mm; background: white; margin: 30px auto; padding: 40px; box-sizing: border-box; box-shadow: 0 0 20px rgba(0,0,0,0.3); position: relative; }
        
        @media print {
            @page { size: A4; margin: 10mm; }
            body, html { 
                width: 100%; 
                height: 100%; 
                margin: 0; 
                padding: 0; 
                background: white !important; 
                display: block !important; 
                overflow: visible !important; 
                direction: rtl !important;
                text-align: right !important;
                word-spacing: 0.1em !important;
                letter-spacing: 0.01em !important;
                white-space: normal !important;
                text-rendering: optimizeLegibility !important;
                unicode-bidi: embed !important;
            }
            .page-container { 
                width: 100% !important; 
                margin: 0 !important; 
                padding: 0 !important; 
                box-shadow: none !important; 
                border: none !important; 
                min-height: auto !important; 
                direction: rtl !important;
            }
            .no-print { display: none !important; }
            .coverage-modal { display: none !important; }
            /* אופטימיזציה של רווחים ב-PDF */
            .header { margin-bottom: 12px !important; padding-bottom: 8px !important; }
            .kpi-container { margin-bottom: 12px !important; padding: 12px !important; }
            .sec-title { margin-top: 10px !important; margin-bottom: 4px !important; padding: 5px 10px !important; }
            /* טבלאות מתחת לכותרות - רווח קטן */
            .sec-title + table { margin-top: 2px !important; }
            .members-grid { margin-bottom: 12px !important; gap: 8px !important; }
            .checklist-grid { margin-bottom: 12px !important; gap: 8px !important; }
            .charts-section { margin-top: 8px !important; margin-bottom: 12px !important; gap: 10px !important; }
            table { margin-bottom: 12px !important; }
            .recommendations-box { margin-top: 12px !important; padding: 12px !important; }
            .footer { margin-top: 15px !important; padding-top: 8px !important; }
            /* מניעת רווחים גדולים מיותרים */
            .page-container > *:first-child { margin-top: 0 !important; }
            .page-container > *:last-child { margin-bottom: 0 !important; }
            /* רווחים קטנים יותר בין סקשנים */
            div[style*="page-break"] { margin-top: 5px !important; margin-bottom: 5px !important; }
            /* רווחים קטנים יותר אחרי כותרות עמוד */
            .sec-title:first-child { margin-top: 5px !important; }
            /* רווחים קטנים יותר בין סקשנים */
            div[style*="page-break"] { margin-top: 5px !important; margin-bottom: 5px !important; }
            /* מניעת שבירת אלמנטים באמצע - הגנות חזקות */
            .kpi-container, .checklist-grid, .mem-item, .chart-wrapper, .recommendations-box, .charts-section, .check-card, .members-grid, .header, .footer { page-break-inside: avoid !important; }
            /* מניעת שבירה של טבלאות - אבל אם צריך, אז הכותרת תופיע שוב */
            .sec-title { 
                page-break-after: avoid !important; 
                page-break-inside: avoid !important; 
            }
            /* אם הכותרת לפני טבלה, ננסה לשמור אותם יחד */
            .sec-title + table { 
                page-break-before: avoid !important;
            }
            table { 
                page-break-inside: avoid !important;
                border-collapse: collapse !important;
            }
            /* כותרות טבלה יופיעו שוב בעמוד חדש */
            thead { 
                display: table-header-group !important; 
                page-break-after: avoid !important;
            }
            tfoot { 
                display: table-footer-group !important; 
                page-break-before: avoid !important;
            }
            tbody { 
                display: table-row-group !important; 
            }
            /* כל שורה בטבלה תישאר יחד */
            tr { 
                page-break-inside: avoid !important; 
                page-break-after: auto !important; 
            }
            td, th { 
                page-break-inside: avoid !important; 
            }
            h1, h2, h3, h4 { 
                page-break-after: avoid !important; 
            }
            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
        }
        
        .header { text-align: center; border-bottom: 3px solid var(--accent); padding-bottom: 10px; margin-bottom: 15px; position: relative; min-height: 85px; direction: rtl; }
        .header .header-content img { height: 65px; margin-bottom: 8px; }
        .header h1 { margin: 0; font-size: 24pt; color: var(--primary); font-weight: 800; word-spacing: 0.1em; white-space: normal; }
        .header p { margin: 4px 0; color: #666; font-size: 11pt; word-spacing: 0.1em; white-space: normal; }
        .agents-image { 
            position: absolute !important; left: 10px !important; top: 5px !important; 
            width: 90px !important; height: auto !important; opacity: 1 !important; 
            z-index: 0 !important; pointer-events: none !important;
        }
        .header-content { position: relative; z-index: 1; }

        .kpi-container { display: flex; justify-content: space-between; gap: 15px; margin-bottom: 15px; background: var(--bg-gray); padding: 12px; border-radius: 12px; border: 1px solid #e2e8f0; page-break-inside: avoid !important; direction: rtl; }
        .kpi-box { flex: 1; text-align: center; border-left: 1px solid #cbd5e1; word-spacing: 0.1em; white-space: normal; }
        .kpi-box:last-child { border-left: none; }
        .kpi-title { font-size: 10pt; color: #64748b; font-weight: 700; text-transform: uppercase; margin-bottom: 5px; word-spacing: 0.1em; white-space: normal; }
        .kpi-value { font-size: 18pt; font-weight: 800; color: #0f172a; line-height: 1; word-spacing: 0.1em; white-space: normal; }
        .text-pink { color: var(--accent); } .text-green { color: #10b981; } .text-blue { color: #4361ee; }

        .sec-title { background: var(--primary); color: white; padding: 5px 10px; font-size: 12pt; font-weight: bold; margin-top: 12px; margin-bottom: 4px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; border-left: 5px solid var(--accent); page-break-inside: avoid !important; page-break-after: avoid !important; word-spacing: 0.1em; white-space: normal; direction: rtl; }
        /* טבלאות מתחת לכותרות - רווח קטן */
        .sec-title + table { margin-top: 0; margin-bottom: 12px; }
        
        .members-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; page-break-inside: avoid !important; }
        .mem-item { background: #fff; padding: 10px; border-radius: 8px; border: 1px solid #e2e8f0; font-size: 10pt; box-shadow: 0 1px 2px rgba(0,0,0,0.05); page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; }
        .mem-item strong { display: block; color: var(--accent); margin-bottom: 3px; font-size: 11pt; word-spacing: 0.1em; white-space: normal; }

        .checklist-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 12px; page-break-inside: avoid !important; }
        .check-card { display: flex; flex-direction: column; align-items: center; justify-content: start; padding: 12px 5px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; position: relative; min-height: 85px; page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; cursor: pointer; transition: all 0.3s ease; }
        .check-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
        .check-card.found { background: #f0fdf4; border-color: #86efac; color: #166534; }
        .check-card.warning { background: #fffbeb; border-color: #fcd34d; color: #92400e; }
        .check-card.missing { background: #fef2f2; border-color: #fca5a5; color: #991b1b; opacity: 0.85; }
        
        /* Modal for coverage participants */
        .coverage-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 10000; display: none !important; justify-content: center; align-items: center; backdrop-filter: blur(5px); }
        .coverage-modal.active { display: flex !important; }
        .coverage-modal-content { background: white; width: 500px; max-width: 90vw; max-height: 80vh; padding: 30px; border-radius: 24px; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); overflow-y: auto; direction: rtl; }
        .coverage-modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #e2e8f0; }
        .coverage-modal-header h3 { margin: 0; font-size: 1.5rem; color: #1e293b; }
        .coverage-modal-close { cursor: pointer; font-size: 1.5rem; color: #94a3b8; background: none; border: none; padding: 5px; }
        .coverage-modal-close:hover { color: #1e293b; }
        .coverage-participants-list { list-style: none; padding: 0; margin: 0; }
        .coverage-participant-item { padding: 15px; margin-bottom: 10px; border-radius: 12px; border: 2px solid #e2e8f0; background: #f8fafc; transition: 0.3s; }
        .coverage-participant-item:hover { border-color: #4f46e5; background: #eef2ff; }
        .coverage-participant-name { font-weight: 600; font-size: 1.1rem; color: #1e293b; margin-bottom: 5px; }
        .coverage-participant-details { font-size: 0.9rem; color: #64748b; }
        .check-icon { font-size: 16pt; margin-bottom: 8px; }
        .check-label { font-size: 9pt; font-weight: 700; margin-bottom: 3px; word-spacing: 0.1em; white-space: normal; }
        .check-status { font-size: 8pt; line-height: 1.1; word-spacing: 0.1em; white-space: normal; }

        table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 9.5pt; table-layout: fixed; page-break-inside: avoid !important; direction: rtl; }
        th { background: #f1f5f9; color: #1e293b; padding: 10px 6px; font-weight: bold; border: 1px solid #cbd5e1; text-align: center; page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; }
        td { padding: 8px 6px; border: 1px solid #e2e8f0; text-align: center; vertical-align: middle; word-wrap: break-word; page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; }
        tr { page-break-inside: avoid !important; }
        tr:nth-child(even) { background: #f8fafc; }
        .font-bold { font-weight: 700; }
        .text-start { text-align: right !important; padding-right: 8px !important; }
        .sum-row { background: #fff1f2 !important; font-weight: bold; border-top: 2px solid var(--accent); }
        .money { font-family: 'Courier New', Courier, monospace; letter-spacing: -0.5px; font-weight: 600; }

        /* עיצוב המלצות */
        .recommendations-box { background: #fff; border: 2px solid #ec4899; border-radius: 12px; padding: 12px; margin-top: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; direction: rtl; }
        .rec-item { margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #eee; display: flex; gap: 10px; word-spacing: 0.1em; white-space: normal; direction: rtl; }
        .rec-item:last-child { border-bottom: none; margin-bottom: 0; }
        .rec-icon { color: #ec4899; font-size: 1.2em; margin-top: 2px; }

        /* עיצוב גרפים */
        .charts-section { display: flex; gap: 10px; margin-top: 8px; margin-bottom: 12px; justify-content: center; align-items: flex-start; page-break-inside: avoid !important; }
        .chart-wrapper { width: 28%; max-width: 220px; background: #fff; padding: 12px; border-radius: 12px; border: 1px solid #e2e8f0; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08); transition: transform 0.3s ease, box-shadow 0.3s ease; page-break-inside: avoid !important; }
        .chart-wrapper:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
        .chart-wrapper h4 { margin: 0 0 8px 0; padding: 0; color: #2c3e50; font-weight: 700; font-size: 10pt; white-space: normal; line-height: 1.2; word-spacing: 0.1em; direction: rtl; }
        .chart-wrapper canvas { max-width: 100% !important; max-height: 180px !important; height: auto !important; }

        .footer { text-align: center; font-size: 9pt; color: #94a3b8; border-top: 1px solid #eee; padding-top: 12px; margin-top: 25px; word-spacing: 0.1em; white-space: normal; direction: rtl; }
        
        /* תיקון כללי לכל הטקסט העברי - מניעת מילים מחוברות */
        * {
            word-spacing: 0.1em;
            letter-spacing: 0.01em;
        }
        
        /* וידוא שכל האלמנטים עם טקסט מקבלים את התיקון */
        p, span, div, h1, h2, h3, h4, h5, h6, li, td, th, strong, em, .header, .footer, .kpi-title, .kpi-value, .check-label, .check-status, .rec-item, .mem-item, .sec-title {
            word-spacing: 0.1em !important;
            white-space: normal !important;
        }
    </style>
</head>
<body>
    <div class="page-container">
        <div class="header">
            <img src="/דמויות.PNG" alt="" class="agents-image" onerror="var img=this; setTimeout(function(){img.src='/דמויות.png'; img.onerror=function(){img.style.display='none';};}, 100);">
            <div class="header-content">
                <img src="/logo.png" onerror="this.style.display='none'">
                <h1>ניתוח תיק לקוח</h1>
                <p>הוכן עבור: <strong>{{ family_name }}</strong> | תאריך הפקה: {{ date }}</p>
            </div>
        </div>

        <div class="kpi-container">
            <div class="kpi-box"><div class="kpi-title">פרמיה חודשית</div><div class="kpi-value text-pink">₪{{ total_prem }}</div></div>
            <div class="kpi-box"><div class="kpi-title">סה"כ נכסים</div><div class="kpi-value text-green">₪{{ total_sav }}</div></div>
            <div class="kpi-box"><div class="kpi-title">סה"כ ביטוחים</div><div class="kpi-value text-blue">₪{{ total_risk }}</div></div>
            <div class="kpi-box"><div class="kpi-title">מוצרים בתיק</div><div class="kpi-value">{{ total_count }}</div></div>
        </div>

        <div style="page-break-inside: avoid;">
            <div class="sec-title"><span>משתתפים</span> <i class="fas fa-users"></i></div>
            <div class="members-grid">{{ members_html | safe }}</div>
        </div>

        <div style="page-break-inside: avoid;">
            <div class="sec-title"><span>מפת הגנות משפחתית</span> <i class="fas fa-shield-halved"></i></div>
            <div class="checklist-grid">{{ checklist_html | safe }}</div>
        </div>

        <div style="page-break-before: always; page-break-inside: avoid;">
            <div class="sec-title"><span>תיק ביטוחי</span> <i class="fas fa-shield-alt"></i></div>
            <table>
            <thead>
                <tr>
                    <th style="width:12%">מבוטח</th><th style="width:10%">חברה</th><th style="width:15%">סוג כיסוי</th>
                    <th style="width:10%">פוליסה</th><th style="width:10%">תחילה</th><th style="width:12%">סכום ביטוח</th>
                    <th style="width:8%">פרמיה</th><th>הערות</th>
                </tr>
            </thead>
            <tbody>{{ ins_rows | safe }}</tbody>
        </table>
        </div>

        <div style="page-break-before: always; page-break-inside: avoid;">
            <div class="sec-title"><span>מפת נכסים פיננסיים</span> <i class="fas fa-chart-pie"></i></div>
            <div class="checklist-grid">{{ fin_checklist_html | safe }}</div>

            <div class="charts-section" style="page-break-inside: avoid; margin-top: 12px; margin-bottom: 8px;">
                <div class="chart-wrapper">
                    <h4>חלוקת נכסים לפי רמת סיכון</h4>
                    <canvas id="riskChart" style="max-height: 180px !important;"></canvas>
                </div>
                 <div class="chart-wrapper">
                    <h4>התפלגות מוצרים</h4>
                    <canvas id="productChart" style="max-height: 180px !important;"></canvas>
                </div>
                <div class="chart-wrapper">
                    <h4>חלוקה לפי הוני/קבצתי</h4>
                    <canvas id="equityFixedChart" style="max-height: 180px !important;"></canvas>
                </div>
            </div>

            {{ client_summary_html | safe }}

            <div class="sec-title" style="margin-top:8px;"><span>תיק פיננסי ופנסיוני</span> <i class="fas fa-chart-line"></i></div>
            <table>
                <thead>
                    <tr>
                        <th style="width:12%">חוסך</th><th style="width:15%">מוצר</th><th style="width:10%">גוף מוסדי</th>
                        <th style="width:8%">רמת סיכון</th><th style="width:10%">צבירה</th><th style="width:10%">צפי פרישה</th>
                        <th style="width:8%">דמי ניהול</th><th>סטטוס</th>
                    </tr>
                </thead>
                <tbody>{{ fin_rows | safe }}</tbody>
            </table>
        </div>
        
        <div style="page-break-inside: avoid;">
            <div class="sec-title"><span>סיכום סימולציה לפרישה לפי לקוח</span> <i class="fas fa-calculator"></i></div>
            <table>
                <thead>
                    <tr>
                        <th style="width:25%">לקוח</th>
                        <th style="width:15%">מספר מוצרים</th>
                        <th style="width:30%">קצבה עם הפקדות</th>
                        <th style="width:30%">קבצה בלי הפקדות</th>
                    </tr>
                </thead>
                <tbody>{{ simulation_summary_html | safe }}</tbody>
            </table>
        </div>

        <div class="footer">דוח זה הופק ע"י מערכת AgencyOS | כל הזכויות שמורות לאשר לוי סוכנות לביטוח )2011( בע"מ</div>
    </div>

    <!-- Modal for Coverage Participants -->
    <div id="coverageModal" class="coverage-modal" onclick="if(event.target===this) closeCoverageModal()">
        <div class="coverage-modal-content" onclick="event.stopPropagation()">
            <div class="coverage-modal-header">
                <h3 id="coverageModalTitle">רשימת מבוטחים</h3>
                <button class="coverage-modal-close" onclick="closeCoverageModal()">×</button>
            </div>
            <ul class="coverage-participants-list" id="coverageParticipantsList">
                <!-- Participants will be inserted here -->
            </ul>
        </div>
    </div>

    <script>
        // פונקציית עזר ל-escape HTML
        function escapeHtml(text) {
            if (!text) return '';
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.toString().replace(/[&<>"']/g, function(m) { return map[m]; });
        }
        
        // פונקציה להצגת רשימת מבוטחים מכרטיסייה (שימוש ב-data attributes)
        function showCoverageParticipantsFromCard(cardElement) {
            try {
                const coverageKey = cardElement.getAttribute('data-coverage-key');
                const coverageLabel = JSON.parse(cardElement.getAttribute('data-coverage-label'));
                const membersWithCoverage = JSON.parse(cardElement.getAttribute('data-coverage-members'));
                const allMembersAttr = cardElement.getAttribute('data-all-members');
                const allMembers = allMembersAttr ? JSON.parse(allMembersAttr) : membersWithCoverage;
                showCoverageParticipants(coverageKey, coverageLabel, membersWithCoverage, allMembers);
            } catch (e) {
                console.error('Error parsing coverage data:', e);
                alert('שגיאה בטעינת נתוני הכיסוי');
            }
        }
        
        // פונקציה להצגת רשימת מבוטחים בכיסוי מסוים
        function showCoverageParticipants(coverageKey, coverageLabel, membersWithCoverage, allMembers) {
            const modal = document.getElementById('coverageModal');
            const modalTitle = document.getElementById('coverageModalTitle');
            const participantsList = document.getElementById('coverageParticipantsList');
            
            if (!modal || !modalTitle || !participantsList) {
                console.error('Modal elements not found');
                return;
            }
            
            modalTitle.textContent = coverageLabel + ' - רשימת מבוטחים';
            participantsList.innerHTML = '';
            
            // יצירת Set של מבוטחים עם כיסוי לבדיקה מהירה
            const membersWithCoverageSet = new Set(membersWithCoverage || []);
            
            // תמיד נציג את כל המשפחה - allMembers תמיד יכיל את כל המשפחה
            let membersToDisplay = [];
            
            if (allMembers && allMembers.length > 0) {
                // יש רשימת כל המשפחה - נציג את כולם
                membersToDisplay = allMembers.slice(); // עותק של הרשימה
            } else {
                // אם אין allMembers (fallback) - נשתמש ברשימה של מי שיש לו כיסוי
                membersToDisplay = (membersWithCoverage || []).slice();
            }
            
            // אם אין שום מבוטח להצגה
            if (membersToDisplay.length === 0) {
                participantsList.innerHTML = '<li class="coverage-participant-item"><div class="coverage-participant-name" style="text-align:center; color:#94a3b8;">אין מבוטחים בכיסוי זה</div></li>';
                modal.classList.add('active');
                return;
            }
            
            // מיון: קודם ירוקים (יש כיסוי), אחר כך אדומים (אין כיסוי)
            membersToDisplay.sort(function(a, b) {
                const aHasCoverage = membersWithCoverageSet.has(a);
                const bHasCoverage = membersWithCoverageSet.has(b);
                if (aHasCoverage && !bHasCoverage) return -1; // a ירוק, b אדום - a קודם
                if (!aHasCoverage && bHasCoverage) return 1;  // a אדום, b ירוק - b קודם
                // שניהם באותו מצב - שמור על סדר אלפביתי
                return a.localeCompare(b);
            });
            
            // הצגת כל המבוטחים - מי שיש לו כיסוי בירוק, מי שאין לו באדום
            membersToDisplay.forEach(function(member) {
                const hasCoverage = membersWithCoverageSet.has(member);
                const li = document.createElement('li');
                li.className = 'coverage-participant-item';
                
                if (hasCoverage) {
                    // יש כיסוי - ירוק
                    li.style.borderColor = '#10b981';
                    li.style.background = '#dcfce7';
                    li.innerHTML = '<div class="coverage-participant-name" style="color:#166534;"><i class="fas fa-check-circle" style="color:#10b981; margin-left:8px;"></i>' + 
                                   escapeHtml(member) + '</div>' +
                                   '<div class="coverage-participant-details" style="color:#166534;">מבוטח בכיסוי ' + escapeHtml(coverageLabel) + '</div>';
                } else {
                    // אין כיסוי - אדום
                    li.style.borderColor = '#ef4444';
                    li.style.background = '#fee2e2';
                    li.innerHTML = '<div class="coverage-participant-name" style="color:#991b1b;"><i class="fas fa-times-circle" style="color:#ef4444; margin-left:8px;"></i>' + 
                                   escapeHtml(member) + '</div>' +
                                   '<div class="coverage-participant-details" style="color:#991b1b;">ללא כיסוי ' + escapeHtml(coverageLabel) + '</div>';
                }
                participantsList.appendChild(li);
            });
            
            modal.classList.add('active');
        }
        
        // פונקציה לסגירת המודאל
        function closeCoverageModal() {
            document.getElementById('coverageModal').classList.remove('active');
        }
        
        // נתונים לגרפים
        const riskData = {{ risk_chart_data | tojson }};
        const productData = {{ product_chart_data | tojson }};
        const equityFixedData = {{ equity_fixed_chart_data | tojson }};

        // יצירת גרף סיכון
        if (document.getElementById('riskChart')) {
            new Chart(document.getElementById('riskChart'), {
                type: 'pie',
                data: {
                    labels: Object.keys(riskData),
                    datasets: [{
                        data: Object.values(riskData),
                        backgroundColor: ['#ec4899', '#3b82f6', '#10b981', '#f59e0b', '#6366f1', '#8b5cf6'],
                        borderWidth: 2,
                        borderColor: '#ffffff',
                        hoverOffset: 15
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    aspectRatio: 1.1,
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 2000,
                        easing: 'easeOutQuart'
                    },
                    plugins: { 
                        legend: { 
                            position: 'bottom',
                            labels: {
                                padding: 8,
                                font: { size: 9, weight: '600' },
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            enabled: true,
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 13, weight: 'bold' },
                            bodyFont: { size: 12 },
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    return label + ': ₪' + value.toLocaleString() + ' (' + percentage + '%)';
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    }
                }
            });
        }

        // יצירת גרף מוצרים
        if (document.getElementById('productChart')) {
             new Chart(document.getElementById('productChart'), {
                type: 'doughnut',
                data: {
                    labels: Object.keys(productData),
                    datasets: [{
                        data: Object.values(productData),
                        backgroundColor: ['#ec4899', '#3b82f6', '#10b981', '#f59e0b', '#6366f1'],
                        borderWidth: 2,
                        borderColor: '#ffffff',
                        hoverOffset: 20
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    aspectRatio: 1.1,
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 2000,
                        easing: 'easeOutQuart'
                    },
                    plugins: { 
                        legend: { 
                            position: 'bottom',
                            labels: {
                                padding: 8,
                                font: { size: 9, weight: '600' },
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            enabled: true,
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 13, weight: 'bold' },
                            bodyFont: { size: 12 },
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = ((value / total) * 100).toFixed(1);
                                    return label + ': ' + value + ' מוצרים (' + percentage + '%)';
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    },
                    cutout: '60%'
                }
            });
        }

        // יצירת גרף הוני/קבצתי
        if (document.getElementById('equityFixedChart')) {
            new Chart(document.getElementById('equityFixedChart'), {
                type: 'pie',
                data: {
                    labels: Object.keys(equityFixedData),
                    datasets: [{
                        data: Object.values(equityFixedData),
                        backgroundColor: ['#3b82f6', '#10b981'],
                        borderWidth: 2,
                        borderColor: '#ffffff',
                        hoverOffset: 15
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    aspectRatio: 1.1,
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 2000,
                        easing: 'easeOutQuart'
                    },
                    plugins: { 
                        legend: { 
                            position: 'bottom',
                            labels: {
                                padding: 8,
                                font: { size: 9, weight: '600' },
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            enabled: true,
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: { size: 13, weight: 'bold' },
                            bodyFont: { size: 12 },
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
                                    return label + ': ₪' + value.toLocaleString() + ' (' + percentage + '%)';
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

# --- פונקציות עזר ---
def clean_text(val):
    if isinstance(val, pd.Series): val = val.iloc[0]
    if pd.isna(val) or str(val).lower() in ['nan', 'none', '0', '0.0', '']: return ""
    return str(val).strip()

def clean_currency(val):
    if isinstance(val, pd.Series): val = val.iloc[0]
    if pd.isna(val): return 0
    s = str(val).replace('₪', '').replace(',', '').replace('%', '').strip()
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except: return 0

def is_valid_name(name):
    if not name or not isinstance(name, str): return False
    name = name.strip()
    if len(name) < 2: return False
    if name.replace('.','').isdigit(): return False
    if re.match(r'^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$', name): return False
    if name in ['שם', 'שם פרטי', 'שם משפחה', 'מבוטח', 'מבוטחים', 'לקוח', 'סה"כ', 'nan', 'none', 'פרטי לקוח', 'המלצות', 'קיים', '']: return False
    return True

def find_header_and_type(df):
    for i in range(min(len(df), 50)):
        row_values = df.iloc[i].astype(str).values
        row_str = " ".join(row_values)
        if "סכום פיצוי" in row_str and "מבוטחים" in row_str: return i, 'ins'
        if "צבירה" in row_str and "דמי ניהול" in row_str: return i, 'fin'
        if "שם" in row_values and "גיל" in row_values: return i, 'det'
    return -1, None

def strip_namespace(tag):
    """הסרת namespace מ-XML tag"""
    if '}' in tag:
        return tag.split('}')[1]
    return tag

def find_element_text(element, tag_name, default=""):
    """מציאת אלמנט לפי שם (ללא namespace) והחזרת טקסט"""
    if element is None:
        return default
    for child in element.iter():
        if strip_namespace(child.tag) == tag_name:
            text = child.text
            return text.strip() if text else default
    return default

def find_all_elements(element, tag_name):
    """מציאת כל האלמנטים לפי שם (ללא namespace)"""
    results = []
    if element is None:
        return results
    for child in element.iter():
        if strip_namespace(child.tag) == tag_name:
            results.append(child)
    return results

def parse_dat_file_insurance(file_content):
    """
    פענוח קבצי DAT של מסלקה (Mislaka) לפוליסות ביטוח חיים.
    מחזיר רשימה של dictionaries עם נתוני ביטוח.
    """
    insurance_data = []
    
    try:
        # ניסיון לפרסר כ-XML
        if isinstance(file_content, bytes):
            try:
                root = ET.parse(BytesIO(file_content)).getroot()
            except ET.ParseError:
                try:
                    xml_str = file_content.decode('cp1255')
                    root = ET.fromstring(xml_str)
                except:
                    xml_str = file_content.decode('utf-8', errors='ignore')
                    root = ET.fromstring(xml_str)
        else:
            root = ET.fromstring(file_content)
        
        # חיפוש YeshutYatzran
        yeshut_yatzran = None
        for elem in root.iter():
            if strip_namespace(elem.tag) == 'YeshutYatzran':
                yeshut_yatzran = elem
                break
        
        if not yeshut_yatzran:
            return []
        
        company = find_element_text(yeshut_yatzran, 'SHEM-YATZRAN', '')
        print(f"  [ביטוח] חברה: {company}")
        
        # חיפוש כל ה-Mutzarim
        mutzarim = []
        for elem in yeshut_yatzran.iter():
            if strip_namespace(elem.tag) == 'Mutzar':
                mutzarim.append(elem)
        
        print(f"  [ביטוח] נמצאו {len(mutzarim)} מצטרפים")
        for mutzar in mutzarim:
            # חילוץ פרטי הלקוח
            yeshut_lakoach = None
            for elem in mutzar.iter():
                if strip_namespace(elem.tag) == 'YeshutLakoach':
                    yeshut_lakoach = elem
                    break
            
            shem_prati = find_element_text(yeshut_lakoach, 'SHEM-PRATI', '') if yeshut_lakoach else ''
            shem_mishpacha = find_element_text(yeshut_lakoach, 'SHEM-MISHPACHA', '') if yeshut_lakoach else ''
            client_name = f"{shem_prati} {shem_mishpacha}".strip()
            
            if not client_name:
                client_name = "לקוח לא מזוהה"
            
            # חיפוש כל הפוליסות
            heshbonot = []
            for elem in mutzar.iter():
                if strip_namespace(elem.tag) == 'HeshbonOPolisa':
                    heshbonot.append(elem)
            
            print(f"    [ביטוח] נמצאו {len(heshbonot)} פוליסות")
            for heshbon in heshbonot:
                # מספר פוליסה
                policy_num = find_element_text(heshbon, 'MISPAR-POLISA-O-HESHBON', '')
                
                # תאריך תחילה
                taarich_hitztarfut = find_element_text(heshbon, 'TAARICH-HITZTARFUT-MUTZAR', '')
                start_date = ''
                if taarich_hitztarfut and len(taarich_hitztarfut) == 8:
                    # פורמט YYYYMMDD -> DD/MM/YYYY
                    start_date = f"{taarich_hitztarfut[6:8]}/{taarich_hitztarfut[4:6]}/{taarich_hitztarfut[0:4]}"
                
                # חיפוש Kisuim (כיסויים) - שני סוגים:
                # 1. ZihuiKisui (כיסוי ביטוח חיים רגיל)
                # 2. KisuiBKerenPensia (כיסוי בקרן פנסיה)
                
                # סוג 1: ZihuiKisui
                kisuim = []
                for elem in heshbon.iter():
                    if strip_namespace(elem.tag) == 'ZihuiKisui':
                        kisuim.append(elem)
                
                print(f"      [ביטוח] נמצאו {len(kisuim)} ZihuiKisui בפוליסה")
                for kisui in kisuim:
                    # שם כיסוי
                    shem_kisui = find_element_text(kisui, 'SHEM-KISUI-YATZRAN', '')
                    if not shem_kisui:
                        continue
                    
                    # סכום ביטוח - חיפוש ב-SchumeiBituahYesodi
                    coverage = 0
                    schumei = None
                    for elem in kisui.iter():
                        if strip_namespace(elem.tag) == 'SchumeiBituahYesodi':
                            schumei = elem
                            break
                    
                    if schumei:
                        schum_bituch = find_element_text(schumei, 'SCHUM-BITUAH-LEMAVET', '0')
                        try:
                            coverage = float(schum_bituch.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        except (ValueError, AttributeError):
                            coverage = 0
                    
                    # פרמיה - חיפוש ב-PirteiKisuiBeMutzar
                    premium = 0
                    pirtei_kisui = None
                    for elem in kisui.iter():
                        if strip_namespace(elem.tag) == 'PirteiKisuiBeMutzar':
                            pirtei_kisui = elem
                            break
                    
                    if pirtei_kisui:
                        dmei_bituch = find_element_text(pirtei_kisui, 'DMEI-BITUAH-LETASHLUM-BAPOAL', '0')
                        try:
                            premium = float(dmei_bituch.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        except (ValueError, AttributeError):
                            premium = 0
                    
                    # תאריך תחילה של הכיסוי
                    if not start_date and pirtei_kisui:
                        taarich_tchilat = find_element_text(pirtei_kisui, 'TAARICH-TCHILAT-KISUY', '')
                        if taarich_tchilat and len(taarich_tchilat) == 8:
                            start_date = f"{taarich_tchilat[6:8]}/{taarich_tchilat[4:6]}/{taarich_tchilat[0:4]}"
                    
                    # הוספת הרשומה אם יש כיסוי או פרמיה
                    print(f"        [ביטוח] כיסוי: {shem_kisui}, סכום: {coverage}, פרמיה: {premium}")
                    if coverage > 0 or premium > 0:
                        record = {
                            "client": client_name,
                            "company": company,
                            "policy": policy_num,
                            "start_date": start_date,
                            "type": shem_kisui,
                            "coverage": int(coverage) if coverage == int(coverage) else coverage,
                            "premium": int(premium) if premium == int(premium) else premium,
                            "notes": ""
                        }
                        insurance_data.append(record)
                        print(f"        [ביטוח] ✓ נוספה רשומה: {client_name} - {shem_kisui} (כיסוי: {coverage}, פרמיה: {premium})")
                    else:
                        print(f"        [ביטוח] ✗ דילוג על רשומה (כיסוי: {coverage}, פרמיה: {premium})")
                
                # סוג 2: KisuiBKerenPensia (כיסוי בקרן פנסיה) - נמצא תחת ZihuiKisui
                # חיפוש בכל ה-ZihuiKisui שכבר נמצאו
                for kisui in kisuim:
                    kisui_pensia = None
                    for elem in kisui.iter():
                        if strip_namespace(elem.tag) == 'KisuiBKerenPensia':
                            kisui_pensia = elem
                            break
                    
                    if not kisui_pensia:
                        continue
                    print(f"      [ביטוח] נמצא KisuiBKerenPensia")
                    
                    # אובדן כושר עבודה
                    alut_nechut = find_element_text(kisui_pensia, 'ALUT-KISUI-NECHUT', '0')
                    sach_pensiat_nechut = find_element_text(kisui_pensia, 'SACH-PENSIAT-NECHUT', '0')
                    try:
                        nechut_coverage = float(sach_pensiat_nechut.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        if nechut_coverage > 0:
                            record = {
                                "client": client_name,
                                "company": company,
                                "policy": policy_num,
                                "start_date": start_date,
                                "type": "אובדן כושר עבודה",
                                "coverage": int(nechut_coverage) if nechut_coverage == int(nechut_coverage) else nechut_coverage,
                                "premium": 0,
                                "notes": ""
                            }
                            insurance_data.append(record)
                            print(f"        [ביטוח] ✓ נוספה רשומה: אובדן כושר עבודה (כיסוי: {nechut_coverage})")
                    except (ValueError, AttributeError):
                        pass
                    
                    # פנסיית שאירים
                    kitzbat_sheerim_alman = find_element_text(kisui_pensia, 'KITZBAT-SHEERIM-LEALMAN-O-ALMANA', '0')
                    try:
                        sheerim_coverage = float(kitzbat_sheerim_alman.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        if sheerim_coverage > 0:
                            record = {
                                "client": client_name,
                                "company": company,
                                "policy": policy_num,
                                "start_date": start_date,
                                "type": "פנסיית שאירים",
                                "coverage": int(sheerim_coverage) if sheerim_coverage == int(sheerim_coverage) else sheerim_coverage,
                                "premium": 0,
                                "notes": ""
                            }
                            insurance_data.append(record)
                            print(f"        [ביטוח] ✓ נוספה רשומה: פנסיית שאירים (כיסוי: {sheerim_coverage})")
                    except (ValueError, AttributeError):
                        pass
                    
                    # ביטוח יסודי/חיים - חיפוש ב-SACHAR-KOVEA-LE-NECHUT-VE-SHEERIM או ALUT-KISUY-SHEERIM
                    sachar_kovea = find_element_text(kisui_pensia, 'SACHAR-KOVEA-LE-NECHUT-VE-SHEERIM', '0')
                    alut_kisuy_sheerim = find_element_text(kisui_pensia, 'ALUT-KISUY-SHEERIM', '0')
                    try:
                        yesodi_coverage = 0
                        if sachar_kovea and sachar_kovea != '0':
                            yesodi_coverage = float(sachar_kovea.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        elif alut_kisuy_sheerim and alut_kisuy_sheerim != '0':
                            yesodi_coverage = float(alut_kisuy_sheerim.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                        
                        if yesodi_coverage > 0:
                            record = {
                                "client": client_name,
                                "company": company,
                                "policy": policy_num,
                                "start_date": start_date,
                                "type": "ביטוח יסודי",
                                "coverage": int(yesodi_coverage) if yesodi_coverage == int(yesodi_coverage) else yesodi_coverage,
                                "premium": 0,
                                "notes": ""
                            }
                            insurance_data.append(record)
                            print(f"        [ביטוח] ✓ נוספה רשומה: ביטוח יסודי (כיסוי: {yesodi_coverage})")
                    except (ValueError, AttributeError):
                        pass
    
    except Exception as e:
        print(f"שגיאה בפענוח ביטוח חיים מקובץ DAT/XML: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    print(f"  [ביטוח] סה\"כ הוחזרו {len(insurance_data)} רשומות ביטוח")
    return insurance_data

def parse_dat_file(file_content):
    """
    פענוח קבצי DAT של מסלקה (Mislaka) בפורמט XML.
    מחזיר רשימה של dictionaries עם נתונים פיננסיים.
    """
    financial_data = []
    
    try:
        # ניסיון לפרסר כ-XML
        if isinstance(file_content, bytes):
            # נסה מספר encodings
            try:
                root = ET.parse(BytesIO(file_content)).getroot()
            except ET.ParseError:
                # נסה עם encoding אחר
                try:
                    xml_str = file_content.decode('cp1255')
                    root = ET.fromstring(xml_str)
                except:
                    xml_str = file_content.decode('utf-8', errors='ignore')
                    root = ET.fromstring(xml_str)
        else:
            root = ET.fromstring(file_content)
        
        root_tag = strip_namespace(root.tag)
        print(f"✓ XML נפרס בהצלחה, root tag: {root_tag}")
        
        # המבנה: Mimshak -> YeshutYatzran -> Mutzarim -> Mutzar -> HeshbonotOPolisot -> HeshbonOPolisa
        
        # חיפוש YeshutYatzran (חברה)
        yeshut_yatzran = None
        count_checked = 0
        for elem in root.iter():
            tag = strip_namespace(elem.tag)
            count_checked += 1
            if count_checked <= 10:  # הדפס רק את הראשונים
                print(f"  בדיקת תג: {tag}")
            if tag == 'YeshutYatzran':
                yeshut_yatzran = elem
                print(f"✓ נמצא YeshutYatzran!")
                break
        
        if not yeshut_yatzran:
            print(f"✗ לא נמצא YeshutYatzran אחרי בדיקת {count_checked} תגים")
        
        if not yeshut_yatzran:
            print("לא נמצא YeshutYatzran, מנסה חיפוש חלופי...")
            # נסיון חלופי: חיפוש ישיר של HeshbonOPolisa
            heshbonot = []
            for elem in root.iter():
                if strip_namespace(elem.tag) == 'HeshbonOPolisa':
                    heshbonot.append(elem)
            if heshbonot:
                print(f"נמצאו {len(heshbonot)} פוליסות ישירות, משתמש ב-root")
                yeshut_yatzran = root
        
        if not yeshut_yatzran:
            print("לא נמצא YeshutYatzran, מחזיר רשימה ריקה")
            return []
        
        # חילוץ שם החברה
        company = find_element_text(yeshut_yatzran, 'SHEM-YATZRAN', '')
        print(f"✓ חברה: '{company}'")
        
        # חיפוש כל ה-Mutzarim (מצטרפים) - Mutzar נמצא תחת Mutzarim
        mutzarim = []
        count_mutzar = 0
        for elem in yeshut_yatzran.iter():
            tag = strip_namespace(elem.tag)
            if tag == 'Mutzar':
                mutzarim.append(elem)
                count_mutzar += 1
                print(f"  ✓ נמצא Mutzar #{count_mutzar}")
        
        print(f"✓ נמצאו {len(mutzarim)} מצטרפים (Mutzar)")
        
        # אם אין Mutzarim, נחפש ישירות HeshbonOPolisa
        if not mutzarim:
            print("לא נמצאו Mutzarim, מחפש ישירות HeshbonOPolisa...")
            heshbonot = []
            for elem in yeshut_yatzran.iter():
                if strip_namespace(elem.tag) == 'HeshbonOPolisa':
                    heshbonot.append(elem)
            if heshbonot:
                # יצירת Mutzar מדומה
                mutzarim = [yeshut_yatzran]
        
        for mutzar_idx, mutzar in enumerate(mutzarim):
            print(f"מעבד מצטרף {mutzar_idx + 1}/{len(mutzarim)}")
            
            # חילוץ פרטי הלקוח מ-YeshutLakoach
            yeshut_lakoach = None
            for elem in mutzar.iter():
                if strip_namespace(elem.tag) == 'YeshutLakoach':
                    yeshut_lakoach = elem
                    break
            
            shem_prati = find_element_text(yeshut_lakoach, 'SHEM-PRATI', '') if yeshut_lakoach else ''
            shem_mishpacha = find_element_text(yeshut_lakoach, 'SHEM-MISHPACHA', '') if yeshut_lakoach else ''
            client_name = f"{shem_prati} {shem_mishpacha}".strip()
            
            if not client_name:
                client_name = "לקוח לא מזוהה"
            
            print(f"  לקוח: {client_name}")
            
            # חיפוש כל הפוליסות (HeshbonotOPolisot -> HeshbonOPolisa)
            heshbonot = []
            count_heshbon = 0
            
            # נסיון ראשון: חיפוש ישיר תחת Mutzar
            for elem in mutzar.iter():
                tag = strip_namespace(elem.tag)
                if tag == 'HeshbonOPolisa':
                    if elem not in heshbonot:  # מניעת כפילויות
                        heshbonot.append(elem)
                        count_heshbon += 1
                        print(f"    ✓ נמצא HeshbonOPolisa #{count_heshbon} (ישירות תחת Mutzar)")
            
            # נסיון שני: חיפוש תחת HeshbonotOPolisot
            heshbonot_opolisot = None
            for elem in mutzar.iter():
                tag = strip_namespace(elem.tag)
                if tag == 'HeshbonotOPolisot':
                    heshbonot_opolisot = elem
                    print(f"    ✓ נמצא HeshbonotOPolisot")
                    break
            
            if heshbonot_opolisot:
                for elem in heshbonot_opolisot.iter():
                    tag = strip_namespace(elem.tag)
                    if tag == 'HeshbonOPolisa':
                        if elem not in heshbonot:  # מניעת כפילויות
                            heshbonot.append(elem)
                            count_heshbon += 1
                            print(f"    ✓ נמצא HeshbonOPolisa #{count_heshbon} (תחת HeshbonotOPolisot)")
            
            print(f"    ✓ סה\"כ נמצאו {len(heshbonot)} פוליסות/חשבונות")
            
            for heshbon_idx, heshbon in enumerate(heshbonot):
                print(f"    מעבד פוליסה {heshbon_idx + 1}/{len(heshbonot)}")
                
                # שם מוצר
                product_name = find_element_text(heshbon, 'SHEM-TOCHNIT', '')
                if not product_name:
                    # נסיון חלופי: חיפוש שם מוצר מתגים אחרים
                    product_name = find_element_text(heshbon, 'SHEM-KISUI-YATZRAN', '')
                    if not product_name:
                        product_name = find_element_text(heshbon, 'SHEM-MASLUL-HABITUAH', '')
                        if not product_name:
                            product_name = "מוצר לא מזוהה"
                print(f"      ✓ שם מוצר: '{product_name}'")
            
                # סטטוס
                status_code = find_element_text(heshbon, 'STATUS-POLISA-O-CHESHBON', '')
                status_map = {'1': 'פעיל', '2': 'קפוא', '4': 'מבוטל', '10': 'פעיל'}
                status = status_map.get(status_code, status_code if status_code else '')
                
                # יתרה (צבירה) - חיפוש ב-BlockItrot -> Yitrot -> PerutYitrot -> TOTAL-CHISACHON-MTZBR
                balance = 0
                # חיפוש כל ה-BlockItrot (יכול להיות תחת PirteiTaktziv או ישירות תחת HeshbonOPolisa)
                block_itrot_list = []
                for elem in heshbon.iter():
                    if strip_namespace(elem.tag) == 'BlockItrot':
                        if elem not in block_itrot_list:  # מניעת כפילויות
                            block_itrot_list.append(elem)
                            print(f"      ✓ נמצא BlockItrot #{len(block_itrot_list)}")
                
                print(f"      ✓ נמצאו {len(block_itrot_list)} BlockItrot")
                
                # עיבוד כל ה-BlockItrot
                for block_idx, block_itrot in enumerate(block_itrot_list, 1):
                    print(f"      מעבד BlockItrot #{block_idx}/{len(block_itrot_list)}")
                    print(f"      ✓ מעבד BlockItrot")
                    # חיפוש Yitrot תחילה, ואז PerutYitrot בתוכו
                    yitrot = None
                    for elem in block_itrot.iter():
                        if strip_namespace(elem.tag) == 'Yitrot':
                            yitrot = elem
                            break
                    
                    if yitrot:
                        print(f"      ✓ נמצא Yitrot")
                        # חיפוש כל PerutYitrot - רק בילדים הישירים של Yitrot
                        perut_yitrot_list = []
                        for child in yitrot:
                            if strip_namespace(child.tag) == 'PerutYitrot':
                                perut_yitrot_list.append(child)
                                print(f"      ✓ נמצא PerutYitrot ישירות תחת Yitrot")
                        
                        # אם לא נמצאו בילדים הישירים, נחפש בכל הילדים
                        if not perut_yitrot_list:
                            print(f"      נסיון חלופי: חיפוש בכל הילדים של Yitrot")
                            for elem in yitrot.iter():
                                if strip_namespace(elem.tag) == 'PerutYitrot' and elem != yitrot:
                                    perut_yitrot_list.append(elem)
                        
                        print(f"      ✓ נמצאו {len(perut_yitrot_list)} PerutYitrot")
                        for idx, perut in enumerate(perut_yitrot_list, 1):
                            total_chisachon = find_element_text(perut, 'TOTAL-CHISACHON-MTZBR', '0')
                            try:
                                val = float(total_chisachon.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                                print(f"      ✓ PerutYitrot #{idx}: TOTAL-CHISACHON-MTZBR = '{total_chisachon}' -> {val:.2f}")
                                balance += val
                            except (ValueError, AttributeError) as e:
                                print(f"      ✗ שגיאה בהמרת TOTAL-CHISACHON-MTZBR '{total_chisachon}' ב-PerutYitrot #{idx}: {e}")
                        print(f"      ✓ סה\"כ יתרה מסוכמת: {balance:.2f}")
                    else:
                        print(f"      ✗ לא נמצא Yitrot ב-BlockItrot #{block_idx}")
                    
                    # נסיון נוסף: חיפוש ישיר של TOTAL-CHISACHON-MTZBR ב-BlockItrot
                    if balance == 0:
                        for elem in block_itrot.iter():
                            if strip_namespace(elem.tag) == 'TOTAL-CHISACHON-MTZBR':
                                try:
                                    val_text = elem.text.strip() if elem.text else '0'
                                    val_text = val_text.replace(',', '').replace('₪', '').replace(' ', '').strip()
                                    if val_text:
                                        balance = float(val_text)
                                        print(f"      ✓ נמצא TOTAL-CHISACHON-MTZBR ישירות: {balance}")
                                        break
                                except (ValueError, AttributeError):
                                    pass
                
                if len(block_itrot_list) > 0:
                    print(f"      ✓ סה\"כ יתרה מסוכמת מכל ה-BlockItrot: {balance:.2f}")
                
                # נסיון חלופי: YITRAT-SOF-SHANA (רק אם לא נמצאו PerutYitrot)
                if balance == 0:
                    # נסיון נוסף: חיפוש ישיר של YITRAT-SOF-SHANA
                    yitrat_sof_shana = find_element_text(heshbon, 'YITRAT-SOF-SHANA', '0')
                    print(f"      נסיון חלופי: YITRAT-SOF-SHANA = '{yitrat_sof_shana}'")
                    if yitrat_sof_shana and yitrat_sof_shana != '0':
                        try:
                            balance = float(yitrat_sof_shana.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                            print(f"      ✓ YITRAT-SOF-SHANA -> יתרה: {balance}")
                        except (ValueError, AttributeError) as e:
                            print(f"      ✗ שגיאה בהמרת YITRAT-SOF-SHANA: {e}")
                            balance = 0
                    else:
                        print(f"      ✗ YITRAT-SOF-SHANA לא נמצא או אפס")
                else:
                    print(f"      ✓ יתרה מסוכמת מ-BlockItrot (PerutYitrot): {balance:.2f}")
                
                # דמי ניהול - חיפוש השדות הנכונים
                # חשוב: הערכים מ-SHEUR-DMEI-NIHUL-HISACHON-MIVNE ו-SHEUR-DMEI-NIHUL כבר באחוזים (0.75 = 0.75%)
                # הערכים מ-SHEUR-DMEI-NIHUL-TZVIRA הם עשרוניים (0.0617 = 6.17%)
                accumulation_fee_text = ''
                deposit_fee_text = ''
                accumulation_fee_source = ''  # נשמור מאיפה הערך בא
                deposit_fee_source = ''  # נשמור מאיפה הערך בא
                
                # חיפוש ב-MivneDmeiNihul -> PerutMivneDmeiNihul -> SHEUR-DMEI-NIHUL
                mivne_dmei_nihul = None
                for elem in heshbon.iter():
                    if strip_namespace(elem.tag) == 'MivneDmeiNihul':
                        mivne_dmei_nihul = elem
                        break
                
                if mivne_dmei_nihul:
                    # חיפוש ב-PerutMivneDmeiNihul
                    for perut in mivne_dmei_nihul.iter():
                        if strip_namespace(perut.tag) == 'PerutMivneDmeiNihul':
                            fee_val = find_element_text(perut, 'SHEUR-DMEI-NIHUL', '')
                            if fee_val and not accumulation_fee_text:
                                accumulation_fee_text = fee_val
                                accumulation_fee_source = 'MivneDmeiNihul'  # כבר באחוזים
                                print(f"      ✓ נמצא דמי ניהול מצבירה מ-MivneDmeiNihul: {fee_val}")
                
                # אם לא מצאנו, נחפש ב-PirteiTaktziv -> PerutMasluleiHashkaa -> SHEUR-DMEI-NIHUL-HISACHON-MIVNE
                if not accumulation_fee_text:
                    pirtei_taktziv = None
                    for elem in heshbon.iter():
                        if strip_namespace(elem.tag) == 'PirteiTaktziv':
                            pirtei_taktziv = elem
                            break
                    
                    if pirtei_taktziv:
                        for elem in pirtei_taktziv.iter():
                            if strip_namespace(elem.tag) == 'PerutMasluleiHashkaa':
                                fee_val = find_element_text(elem, 'SHEUR-DMEI-NIHUL-HISACHON-MIVNE', '')
                                if fee_val and not accumulation_fee_text:
                                    accumulation_fee_text = fee_val
                                    accumulation_fee_source = 'PerutMasluleiHashkaa'  # כבר באחוזים
                                    print(f"      ✓ נמצא דמי ניהול מצבירה מ-PerutMasluleiHashkaa (תחת PirteiTaktziv): {fee_val}")
                                    break
                
                # חיפוש דמי ניהול מהפקדה ב-PirteiTaktziv -> PerutMasluleiHashkaa
                if not deposit_fee_text:
                    pirtei_taktziv = None
                    for elem in heshbon.iter():
                        if strip_namespace(elem.tag) == 'PirteiTaktziv':
                            pirtei_taktziv = elem
                            break
                    
                    if pirtei_taktziv:
                        for elem in pirtei_taktziv.iter():
                            if strip_namespace(elem.tag) == 'PerutMasluleiHashkaa':
                                fee_val = find_element_text(elem, 'SHEUR-DMEI-NIHUL-HAFKADA', '')
                                if fee_val and not deposit_fee_text:
                                    deposit_fee_text = fee_val
                                    deposit_fee_source = 'PerutMasluleiHashkaa'  # כבר באחוזים
                                    print(f"      ✓ נמצא דמי ניהול מהפקדה מ-PerutMasluleiHashkaa (תחת PirteiTaktziv): {fee_val}")
                                    break
                
                # אם עדיין לא מצאנו, נשתמש ב-HotzaotBafoalLehodeshDivoach (fallback)
                if not accumulation_fee_text or not deposit_fee_text:
                    hotzaot = None
                    for elem in heshbon.iter():
                        if strip_namespace(elem.tag) == 'HotzaotBafoalLehodeshDivoach':
                            hotzaot = elem
                            break
                    
                    if hotzaot:
                        if not accumulation_fee_text:
                            accumulation_fee_text = find_element_text(hotzaot, 'SHEUR-DMEI-NIHUL-TZVIRA', '')
                            if accumulation_fee_text:
                                accumulation_fee_source = 'HotzaotBafoalLehodeshDivoach'  # עשרוני, צריך להכפיל
                                print(f"      ⚠ שימוש ב-HotzaotBafoalLehodeshDivoach (fallback) לדמי ניהול מצבירה: {accumulation_fee_text}")
                        if not deposit_fee_text:
                            deposit_fee_text = find_element_text(hotzaot, 'SHEUR-DMEI-NIHUL-HAFKADA', '')
                            if deposit_fee_text:
                                deposit_fee_source = 'HotzaotBafoalLehodeshDivoach'  # גם באחוזים (1.0 = 1%)
                                print(f"      ⚠ שימוש ב-HotzaotBafoalLehodeshDivoach (fallback) לדמי ניהול מהפקדה: {deposit_fee_text}")
                
                fee_parts = []
                if accumulation_fee_text:
                    try:
                        acc_fee = float(accumulation_fee_text.replace(',', '').strip() or '0')
                        # אם הערך בא מ-MivneDmeiNihul או PerutMasluleiHashkaa, הוא כבר באחוזים
                        # אם הערך בא מ-HotzaotBafoalLehodeshDivoach, הוא עשרוני וצריך להכפיל ב-100
                        if accumulation_fee_source in ['MivneDmeiNihul', 'PerutMasluleiHashkaa']:
                            # הערך כבר באחוזים (0.75 = 0.75%, 0.02 = 0.02%)
                            acc_fee_pct = acc_fee
                        elif accumulation_fee_source == 'HotzaotBafoalLehodeshDivoach':
                            # הערך עשרוני, צריך להכפיל ב-100 (0.0617 = 6.17%)
                            acc_fee_pct = acc_fee * 100
                        else:
                            # fallback: אם לא יודעים מאיפה, נבדוק לפי הערך
                            if 0.5 <= acc_fee <= 5.0:
                                acc_fee_pct = acc_fee  # כבר באחוזים
                            elif acc_fee < 0.5 and acc_fee > 0:
                                acc_fee_pct = acc_fee * 100  # עשרוני
                            else:
                                acc_fee_pct = acc_fee  # כבר באחוזים
                        
                        if acc_fee_pct > 0:
                            fee_parts.append(f"{acc_fee_pct:.2f}% צבירה")
                    except (ValueError, AttributeError):
                        pass
                
                if deposit_fee_text:
                    try:
                        dep_fee = float(deposit_fee_text.replace(',', '').strip() or '0')
                        # חשוב: כל הערכים של דמי ניהול מהפקדה הם כבר באחוזים!
                        # בין אם הם באים מ-PerutMasluleiHashkaa או מ-HotzaotBafoalLehodeshDivoach
                        # (1.0 = 1%, 1.8 = 1.8%) - לא להכפיל ב-100!
                        dep_fee_pct = dep_fee  # תמיד באחוזים, לא להכפיל
                        if dep_fee_pct > 0:
                            fee_parts.append(f"{dep_fee_pct:.2f}% הפקדה")
                    except (ValueError, AttributeError):
                        pass
                
                fee_str = ", ".join(fee_parts) if fee_parts else ''
                
                # סימולציה פנסיונית
                simulation = 0
                yitra_lefi_gil = None
                for elem in heshbon.iter():
                    if strip_namespace(elem.tag) == 'YitraLefiGilPrisha':
                        yitra_lefi_gil = elem
                        break
                
                if yitra_lefi_gil:
                    kupot = None
                    for elem in yitra_lefi_gil.iter():
                        if strip_namespace(elem.tag) == 'Kupot':
                            kupot = elem
                            break
                    
                    if kupot:
                        # חיפוש כל Kupa
                        kupa_elements = []
                        for elem in kupot.iter():
                            if strip_namespace(elem.tag) == 'Kupa':
                                kupa_elements.append(elem)
                        
                        print(f"      ✓ נמצאו {len(kupa_elements)} Kupa")
                        for idx, kupa in enumerate(kupa_elements, 1):
                            kitzvat_text = find_element_text(kupa, 'KITZVAT-HODSHIT-TZFUYA', '0')
                            try:
                                sim_val = float(kitzvat_text.replace(',', '').replace('₪', '').replace(' ', '').strip() or '0')
                                print(f"      ✓ Kupa #{idx}: KITZVAT-HODSHIT-TZFUYA = '{kitzvat_text}' -> {sim_val:.2f}")
                                if sim_val > 0:
                                    simulation = sim_val
                                    print(f"      ✓ נבחרה סימולציה: {simulation:.2f}")
                                    break
                            except (ValueError, AttributeError) as e:
                                print(f"      ✗ שגיאה בהמרת KITZVAT-HODSHIT-TZFUYA '{kitzvat_text}' ב-Kupa #{idx}: {e}")
                        if simulation == 0:
                            print(f"      ✗ לא נמצאה סימולציה חיובית")
                
                # הוספת הרשומה אם יש יתרה או סימולציה
                print(f"      פוליסה: '{product_name}', יתרה: {balance}, סימולציה: {simulation}, סטטוס: '{status}'")
                
                if balance > 0 or simulation > 0:
                    record = {
                        "client": client_name,
                        "product": product_name,
                        "company": company,
                        "balance": int(balance) if balance == int(balance) else balance,
                        "status": status,
                        "fee": fee_str,
                        "simulation": int(simulation) if simulation == int(simulation) else simulation,
                        "risk": "",
                        "rec": ""
                    }
                    financial_data.append(record)
                    print(f"      ✓ נוספה רשומה #{len(financial_data)}: {client_name} - {product_name} (יתרה: {balance}, סימולציה: {simulation})")
                else:
                    print(f"      ✗ דילוג על רשומה (יתרה: {balance}, סימולציה: {simulation} - שניהם אפס)")
    
    except ET.ParseError as e:
        print(f"שגיאת פרסור XML: {e}")
        import traceback
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"שגיאה בפענוח קובץ DAT/XML: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    print(f"✓ סה\"כ הוחזרו {len(financial_data)} רשומות פיננסיות מ-parse_dat_file")
    if len(financial_data) > 0:
        print(f"✓ דוגמה לרשומה ראשונה: {financial_data[0]}")
    return financial_data

def generate_single_html_report(data):
    total_prem = 0
    total_sav = 0
    total_risk = 0
    total_count = 0
    checklist_data = {k: set() for k in ['risk', 'health', 'ci', 'disability', 'accidents', 'nursing']}
    # מפת הגנה משפחתית - נצטרך לבדוק אם יש לכל המשפחה
    family_members = set(data.get('members', {}).keys())
    checklist_by_member = {k: set() for k in ['risk', 'health', 'ci', 'disability', 'accidents', 'nursing']}
    # איסוף סכומים עבור כל סוג כיסוי (במיוחד לאובדן כושר עבודה)
    checklist_amounts = {k: 0 for k in ['risk', 'health', 'ci', 'disability', 'accidents', 'nursing']}
    fin_checklist_data = {k: {'products': set(), 'total': 0, 'count': 0} for k in ['pension', 'gemel', 'hishtalmut', 'managers', 'gemel_investment']}
    
    # נתונים לגרפים
    risk_distribution = {}
    product_distribution = {}
    equity_fixed_distribution = {'הוני': 0, 'קבצתי': 0}  # חלוקה לפי הוני/קבצתי
    
    # סיכום סימולציה לפי לקוח
    simulation_by_client = {}

    members_html = ""
    if data['members']:
        for name, m in data['members'].items():
            name_escaped = escape_html(name)
            age_escaped = escape_html(m.get("age",""))
            job_escaped = escape_html(m.get("job",""))
            members_html += f'<div class="mem-item"><strong>{name_escaped}</strong><div>{age_escaped} {job_escaped}</div></div>'
    else:
        members_html = '<div style="grid-column:1/-1;text-align:center;color:#999;">--</div>'

    ins_rows = ""
    if data['raw_ins']:
        # בדיקת כפילויות - נשתמש ב-set כדי לזהות רשומות כפולות
        seen_records = set()
        unique_records = []
        
        for r in sorted(data['raw_ins'], key=lambda x: x['client']):
            # יצירת מפתח ייחודי לכל רשומה
            record_key = (r.get('client', ''), r.get('type', ''), r.get('policy', ''), r.get('coverage', 0), r.get('premium', 0))
            
            # בדיקה אם הרשומה כבר קיימת
            if record_key in seen_records:
                print(f"⚠ כפילות נמצאת: {r.get('client')} - {r.get('type')} - {r.get('policy')} - כיסוי: {r.get('coverage')}")
                continue  # דילוג על כפילויות
            
            seen_records.add(record_key)
            unique_records.append(r)
        
        print(f"✓ סה\"כ רשומות ביטוח: {len(data['raw_ins'])}, אחרי הסרת כפילויות: {len(unique_records)}")
        
        for r in unique_records:
            prem = r['premium']
            cov = r['coverage']
            ptype = r['type']
            total_prem += prem
            # סה"כ כל הכיסויים הביטוחיים (לא רק חיים/ריסק)
            total_risk += cov
            total_count += 1
            
            # חלוקת שמות משותפים (כמו "אייל ואפרת" -> ["אייל", "אפרת"])
            client_name = (r['client'] or '').strip()
            client_names = []
            
            if client_name:
                # חלוקה לפי פסיק, &, ו-ו' (ו' בעברית) - עם תמיכה ב-ו' עם רווח או בלי
                # דוגמאות: "אייל ואפרת", "אייל,אפרת", "אייל&אפרת", "אייל ו אפרת"
                parts = re.split(r'[,&]|\s+ו\s+|\s+ו\s*|^ו\s+', client_name)
                for part in parts:
                    name = part.strip()
                    # בדיקה שהשם תקין - לא ריק, לא מספר, לא תאריך
                    if name and len(name) > 1:
                        # בדיקה שזה לא מספר
                        if not name.replace('.', '').replace('-', '').isdigit():
                            # בדיקה שזה לא תאריך
                            if not re.match(r'^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$', name):
                                client_names.append(name)
            
            # אם לא הצלחנו לחלק, נשתמש בשם המקורי
            if not client_names:
                client_names = [client_name] if client_name else []
            
            # הוספה לכל סוג כיסוי - לכל שם בנפרד
            for client in client_names:
                if any(x in ptype for x in ['חיים', 'ריסק', 'מוות', 'משכנתא']): 
                    checklist_data['risk'].add(ptype)
                    checklist_by_member['risk'].add(client)
                if any(x in ptype for x in ['בריאות', 'ניתוח', 'השתל', 'תרופות', 'אמבולטורי', 'ליווי', 'שב"ן']): 
                    checklist_data['health'].add(ptype)
                    checklist_by_member['health'].add(client)
                if any(x in ptype for x in ['מחלות', 'סרטן', 'גילוי']): 
                    checklist_data['ci'].add(ptype)
                    checklist_by_member['ci'].add(client)
                if any(x in ptype for x in ['כושר', 'נכות', 'א.כ.ע']): 
                    checklist_data['disability'].add(ptype)
                    checklist_by_member['disability'].add(client)
                    checklist_amounts['disability'] += cov  # הוספת הסכום לאובדן כושר עבודה
                if any(x in ptype for x in ['תאונות', 'שברים', 'נכויות']): 
                    checklist_data['accidents'].add(ptype)
                    checklist_by_member['accidents'].add(client)
                if 'סיעוד' in ptype: 
                    checklist_data['nursing'].add(ptype)
                    checklist_by_member['nursing'].add(client)
            # הצגת סכום לאובדן כושר עבודה - הסכום תמיד מוצג, אבל חשוב במיוחד לא.כ.ע
            coverage_display = f"₪{cov:,.2f}" if cov else '-'
            client_escaped = escape_html(r['client'])
            company_escaped = escape_html(r['company'])
            ptype_escaped = escape_html(ptype)
            policy_escaped = escape_html(r['policy'])
            start_date_escaped = escape_html(r['start_date'])
            notes_escaped = escape_html(r['notes'])
            ins_rows += f"""<tr><td class="font-bold">{client_escaped}</td><td>{company_escaped}</td><td><strong>{ptype_escaped}</strong></td><td>{policy_escaped}</td><td>{start_date_escaped}</td><td class="money">{coverage_display}</td><td class="money">{f"₪{prem:,.2f}" if prem else '-'}</td><td class="text-start">{notes_escaped}</td></tr>"""
        if total_prem > 0: ins_rows += f'<tr class="sum-row"><td colspan="6" class="text-start">סה"כ פרמיה חודשית:</td><td class="money">₪{total_prem:,.2f}</td><td></td></tr>'
    else:
        ins_rows = '<tr><td colspan="8" style="padding:20px; color:#999;">אין נתוני ביטוח</td></tr>'

    checklist_config = [
        {'key': 'risk', 'label': 'ביטוח חיים', 'icon': 'fa-heart-pulse'},
        {'key': 'health', 'label': 'בריאות פרטי', 'icon': 'fa-user-doctor'},
        {'key': 'ci', 'label': 'מחלות קשות', 'icon': 'fa-virus'},
        {'key': 'disability', 'label': 'אובדן כושר', 'icon': 'fa-wheelchair'},
        {'key': 'accidents', 'label': 'תאונות אישיות', 'icon': 'fa-user-shield'},
        {'key': 'nursing', 'label': 'ביטוח סיעודי', 'icon': 'fa-hands-holding-circle'},
    ]
    checklist_html = ""
    for item in checklist_config:
        found_items = checklist_data[item['key']]
        is_found = len(found_items) > 0
        
        # בדיקה אם יש כיסוי לכל המשפחה (או לכל מי שצריך להיות מכוסה)
        has_for_all_family = False
        
        # קביעת מי צריך להיות מכוסה לפי סוג הכיסוי
        members_that_need_coverage = []
        if item['key'] in ['risk', 'disability']:
            # ביטוח חיים וכושר עבודה - רק להורים
            parents = [m for m in family_members if 'ילד' not in str(data.get('members', {}).get(m, {}).get('job', ''))]
            members_that_need_coverage = parents if parents else []
        else:
            # כל השאר - לכל המשפחה
            members_that_need_coverage = list(family_members) if family_members else []
        
        # בדיקה אם יש כיסוי לכל מי שצריך להיות מכוסה
        if members_that_need_coverage:
            members_with_coverage = checklist_by_member[item['key']]
            # בדיקה אם כל מי שצריך להיות מכוסה אכן מכוסה
            # נרמול שמות - הסרת רווחים מיותרים והשוואה case-insensitive
            members_that_need_coverage_normalized = {m.strip().lower(): m.strip() for m in members_that_need_coverage}
            members_with_coverage_normalized = {m.strip().lower() for m in members_with_coverage}
            
            # בדיקה אם כל מי שצריך להיות מכוסה אכן מכוסה
            has_for_all_family = all(
                normalized_key in members_with_coverage_normalized 
                for normalized_key in members_that_need_coverage_normalized.keys()
            )
            
            # Debug logging
            if not has_for_all_family and is_found:
                missing = [
                    members_that_need_coverage_normalized[n] 
                    for n in members_that_need_coverage_normalized.keys() 
                    if n not in members_with_coverage_normalized
                ]
                if missing:
                    print(f"⚠ {item['label']}: חסרים {len(missing)} מבוטחים - {missing}")
                    print(f"   צריך: {sorted([m.strip() for m in members_that_need_coverage])}")
                    print(f"   יש: {sorted([m.strip() for m in members_with_coverage])}")
        
        # ירוק רק אם יש כיסוי לכל המשפחה (או לכל מי שצריך), אחרת אדום
        css = "found" if (is_found and has_for_all_family) else "missing"
        icon = "fas fa-check" if (is_found and has_for_all_family) else "fas fa-times"
        if is_found:
            # Escape כל הפריטים שנמצאו
            escaped_items = [escape_html(item) for item in found_items]
            txt = ", ".join(escaped_items)
        else:
            txt = "חסר / לבדיקה"
        
        # הוספת סכום לאובדן כושר עבודה
        if item['key'] == 'disability' and checklist_amounts['disability'] > 0:
            txt += f"<br><strong style='font-size:9pt;'>₪{checklist_amounts['disability']:,.2f}</strong>"
        
        label_escaped = escape_html(item["label"])
        # יצירת רשימת מבוטחים עבור כרטיסייה זו
        # members_with_coverage = מי שיש לו כיסוי בכיסוי זה
        members_with_coverage = list(checklist_by_member[item['key']])
        # all_members = תמיד כל המשפחה - נציג את כולם עם הסטטוס שלהם
        all_family_members = sorted(list(family_members)) if family_members else []
        
        # שימוש ב-data attributes עם JSON שנשמר בצורה בטוחה
        try:
            members_with_coverage_json = json.dumps(members_with_coverage, ensure_ascii=False)
            all_members_json = json.dumps(all_family_members, ensure_ascii=False)
            members_with_coverage_attr = members_with_coverage_json.replace('&', '&amp;').replace('"', '&quot;')
            all_members_attr = all_members_json.replace('&', '&amp;').replace('"', '&quot;')
            label_json_str = json.dumps(label_escaped, ensure_ascii=False)
            label_json_attr = label_json_str.replace('&', '&amp;').replace('"', '&quot;')
            key_escaped = item["key"].replace('&', '&amp;').replace('"', '&quot;')
            
            checklist_html += f'<div class="check-card {css}" data-coverage-key="{key_escaped}" data-coverage-label="{label_json_attr}" data-coverage-members="{members_with_coverage_attr}" data-all-members="{all_members_attr}" onclick="showCoverageParticipantsFromCard(this)"><i class="fas {item["icon"]} check-icon"></i><div class="check-label">{label_escaped}</div><div class="check-status">{txt}</div></div>'
        except Exception as e:
            print(f"⚠ שגיאה ביצירת checklist HTML עבור {item['key']}: {e}")
            # Fallback - בלי data attributes
            checklist_html += f'<div class="check-card {css}"><i class="fas {item["icon"]} check-icon"></i><div class="check-label">{label_escaped}</div><div class="check-status">{txt}</div></div>'

    # סיכום לפי מבוטח
    client_summary = {}
    
    fin_rows = ""
    print(f"✓ generate_single_html_report: יש {len(data.get('raw_fin', []))} רשומות ב-raw_fin")
    if data.get('raw_fin'):
        print(f"✓ מעבד {len(data['raw_fin'])} רשומות פיננסיות")
        for r in sorted(data['raw_fin'], key=lambda x: x.get('client', '')):
            bal = r['balance']
            prod = r['product'] or ''
            client = r['client']
            status = r.get('status', '').strip()
            risk = r.get('risk', '')
            sim = r.get('simulation', 0)
            rec = r.get('rec', '')

            total_sav += bal
            total_count += 1
            
            # צבירת נתונים לגרפים
            if risk:
                risk_distribution[risk] = risk_distribution.get(risk, 0) + bal
                # חלוקה לפי הוני/קבצתי (מופיע במסלקה)
                risk_lower = risk.lower()
                if 'הוני' in risk or 'מניות' in risk or 'סיכון' in risk or 'equity' in risk_lower:
                    equity_fixed_distribution['הוני'] += bal
                elif 'קבצתי' in risk or 'קבוע' in risk or 'אג"ח' in risk or 'fixed' in risk_lower or 'אגרות' in risk:
                    equity_fixed_distribution['קבצתי'] += bal
                else:
                    # אם לא מזוהה, ננסה לזהות לפי שם המוצר
                    prod_lower = prod.lower()
                    if 'הוני' in prod or 'מניות' in prod or 'equity' in prod_lower:
                        equity_fixed_distribution['הוני'] += bal
                    elif 'קבצתי' in prod or 'קבוע' in prod or 'אג"ח' in prod or 'fixed' in prod_lower:
                        equity_fixed_distribution['קבצתי'] += bal
            else:
                risk_distribution['לא ידוע'] = risk_distribution.get('לא ידוע', 0) + bal
                # ננסה לזהות לפי שם המוצר
                prod_lower = prod.lower()
                if 'הוני' in prod or 'מניות' in prod or 'equity' in prod_lower:
                    equity_fixed_distribution['הוני'] += bal
                elif 'קבצתי' in prod or 'קבוע' in prod or 'אג"ח' in prod or 'fixed' in prod_lower:
                    equity_fixed_distribution['קבצתי'] += bal
            
            # צבירת נתונים לגרף מוצרים (פנסיה, השתלמות וכו')
            prod_type_key = 'אחר'
            if 'פנסיה' in prod: prod_type_key = 'פנסיה'
            elif 'השתלמות' in prod: prod_type_key = 'השתלמות'
            elif 'גמל' in prod: prod_type_key = 'גמל'
            elif 'מנהלים' in prod: prod_type_key = 'מנהלים'
            product_distribution[prod_type_key] = product_distribution.get(prod_type_key, 0) + 1


            # סיכום לפי מבוטח
            if client not in client_summary:
                client_summary[client] = {'total': 0, 'count': 0, 'active': 0, 'inactive': 0}
            client_summary[client]['total'] += bal
            client_summary[client]['count'] += 1
            if 'פעיל' in status:
                client_summary[client]['active'] += 1
            else:
                client_summary[client]['inactive'] += 1
            
            # איסוף סימולציה לפי לקוח - קצבה עם הפקדות וקבצה בלי הפקדות
            if client not in simulation_by_client:
                simulation_by_client[client] = {'annuity_with_deposits': 0, 'fixed_without_deposits': 0, 'product_count': 0}
            simulation_by_client[client]['product_count'] += 1
            # זיהוי סוג סימולציה לפי סוג המוצר
            if sim and sim > 0:
                if 'פנסיה' in prod or 'קצבה' in prod:
                    # קצבה עם הפקדות
                    simulation_by_client[client]['annuity_with_deposits'] += sim
                else:
                    # קבצה בלי הפקדות
                    simulation_by_client[client]['fixed_without_deposits'] += sim
            
            # זיהוי סוג מוצר פיננסי לצ'ק ליסט
            if not prod: continue
            prod_clean = str(prod).strip()
            if not prod_clean: continue
            
            # לוגיקת סיווג מוצרים...
            if 'פנסיה' in prod_clean or 'פנסיוני' in prod_clean:
                fin_checklist_data['pension']['products'].add(prod_clean)
                fin_checklist_data['pension']['total'] += bal
                fin_checklist_data['pension']['count'] += 1
            elif 'השתלמות' in prod_clean:
                fin_checklist_data['hishtalmut']['products'].add(prod_clean)
                fin_checklist_data['hishtalmut']['total'] += bal
                fin_checklist_data['hishtalmut']['count'] += 1
            elif ('גמל' in prod_clean and 'קופת' in prod_clean) or 'ק.גמל' in prod_clean:
                # בדיקה אם זה קופת גמל להשקעה או רגיל
                if 'השקעה' in prod_clean or 'להשקעה' in prod_clean:
                    fin_checklist_data['gemel_investment']['products'].add(prod_clean)
                    fin_checklist_data['gemel_investment']['total'] += bal
                    fin_checklist_data['gemel_investment']['count'] += 1
                else:
                    fin_checklist_data['gemel']['products'].add(prod_clean)
                    fin_checklist_data['gemel']['total'] += bal
                    fin_checklist_data['gemel']['count'] += 1
            elif ('מנהלים' in prod_clean and 'ביטוח' in prod_clean) or 'ב.מנהלים' in prod_clean:
                fin_checklist_data['managers']['products'].add(prod_clean)
                fin_checklist_data['managers']['total'] += bal
                fin_checklist_data['managers']['count'] += 1
            
            # בניית השורה בטבלה
            status_class = 'style="opacity:0.6;"' if 'מסולק' in status else ''
            sim_display = f"₪{sim:,.2f}" if sim > 0 else "-"
            client_escaped = escape_html(r['client'])
            product_escaped = escape_html(r['product'])
            company_escaped = escape_html(r['company'])
            risk_escaped = escape_html(risk)
            fee_escaped = escape_html(r['fee'])
            status_escaped = escape_html(r['status'])
            fin_rows += f"""<tr {status_class}>
                <td class="font-bold">{client_escaped}</td>
                <td><strong>{product_escaped}</strong></td>
                <td>{company_escaped}</td>
                <td style="font-size:9pt;">{risk_escaped}</td>
                <td class="money" style="color:#166534;font-weight:bold;">{f"₪{bal:,.2f}" if bal else '-'}</td>
                <td class="money" style="color:#2563eb;">{sim_display}</td>
                <td>{fee_escaped}</td>
                <td>{status_escaped}</td>
            </tr>"""

        if total_sav > 0: fin_rows += f'<tr class="sum-row"><td colspan="4" class="text-start">סה"כ נכסים:</td><td class="money">₪{total_sav:,.2f}</td><td colspan="3"></td></tr>'
        print(f"✓ נוצרו {len(data['raw_fin'])} שורות בטבלה הפיננסית, סה\"כ נכסים: {total_sav}")
    else:
        print(f"✗ אין נתונים ב-raw_fin - הטבלה תהיה ריקה")
        fin_rows = '<tr><td colspan="8" style="padding:20px; color:#999;">אין נתוני פיננסים</td></tr>'

    # בניית הצ'ק ליסט הפיננסי (ללא שינוי מהקוד המקורי, רק ההדבקה)
    fin_checklist_html = "" # (קוד זהה למקור בקיצור...)
    for item in fin_checklist_data: # לוגיקה מקוצרת כאן לצורך הקוד, הלוגיקה המלאה נמצאת בקוד המלא
         pass 
    # שחזור הלוגיקה המלאה של הצ'ק ליסט:
    fin_checklist_config = [
        {'key': 'pension', 'label': 'קרן פנסיה', 'icon': 'fa-piggy-bank'},
        {'key': 'gemel', 'label': 'קופת גמל', 'icon': 'fa-wallet'},
        {'key': 'gemel_investment', 'label': 'קופת גמל להשקעה', 'icon': 'fa-chart-line'},
        {'key': 'hishtalmut', 'label': 'קרן השתלמות', 'icon': 'fa-graduation-cap'},
        {'key': 'managers', 'label': 'ביטוח מנהלים', 'icon': 'fa-briefcase'},
    ]
    for item in fin_checklist_config:
        cat_data = fin_checklist_data[item['key']]
        found_items = cat_data['products']
        is_found = len(found_items) > 0
        total_amount = cat_data['total']
        count = cat_data['count']
        if is_found and total_amount > 100000: css, icon = "found", "fas fa-check"
        elif is_found: css, icon = "warning", "fas fa-exclamation-triangle"
        else: css, icon = "missing", "fas fa-times"
        if is_found:
            product_names = [escape_html(name) for name in list(found_items)[:2]]
            txt = ", ".join(product_names) + (f" +{len(found_items)-2}" if len(found_items)>2 else "")
            if total_amount > 0: txt += f"<br><strong style='font-size:9pt;'>₪{total_amount:,.2f}</strong>"
        else: txt = "חסר / לבדיקה"
        label_escaped = escape_html(item["label"])
        fin_checklist_html += f'<div class="check-card {css}"><i class="fas {item["icon"]} check-icon"></i><div class="check-label">{label_escaped}</div><div class="check-status">{txt}</div></div>'
    
    # סיכום לפי מבוטח
    client_summary_html = ""
    if client_summary:
        client_summary_html = '<div class="sec-title" style="margin-top:8px;"><span>סיכום לפי מבוטח</span> <i class="fas fa-user-chart"></i></div><div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:8px;">'
        for client, summary in sorted(client_summary.items()):
            active_pct = (summary['active'] / summary['count'] * 100) if summary['count'] > 0 else 0
            status_color = '#10b981' if active_pct >= 50 else '#f59e0b' if active_pct > 0 else '#ef4444'
            client_escaped = escape_html_attr(client)  # Escape עבור JavaScript attribute
            client_display = escape_html(client)  # Escape עבור תצוגה
            client_summary_html += f'''<div style="background:#f8fafc; padding:12px; border-radius:8px; border:1px solid #e2e8f0;">
                <strong class="clickable-client" style="color:#ec4899; display:block; margin-bottom:5px; cursor:pointer;" onclick="window.parent.postMessage({{type:'showClientProducts', clientName:'{client_escaped}'}}, '*');" title="לחץ לראות מוצרים">{client_display}</strong>
                <div style="font-size:9pt; color:#64748b;">סה"כ: <strong style="color:#166534;">₪{summary['total']:,}</strong></div>
                <div style="font-size:9pt; color:#64748b;">{summary['count']} מוצרים | <span style="color:{status_color};">{summary['active']} פעילים</span></div>
            </div>'''
        client_summary_html += '</div>'
    
    # בניית טבלת סיכום סימולציה לפי לקוח - קצבה עם הפקדות וקבצה בלי הפקדות
    simulation_summary_html = ""
    if simulation_by_client:
        total_annuity = 0
        total_fixed = 0
        for client, sim_data in sorted(simulation_by_client.items()):
            product_count = sim_data['product_count']
            annuity = sim_data.get('annuity_with_deposits', 0)
            fixed = sim_data.get('fixed_without_deposits', 0)
            total_annuity += annuity
            total_fixed += fixed
            annuity_display = f"₪{annuity:,.2f}" if annuity > 0 else "-"
            fixed_display = f"₪{fixed:,.2f}" if fixed > 0 else "-"
            client_escaped = escape_html(client)
            simulation_summary_html += f'<tr><td class="font-bold text-start">{client_escaped}</td><td>{product_count}</td><td class="money" style="color:#2563eb;font-weight:bold;">{annuity_display}</td><td class="money" style="color:#10b981;font-weight:bold;">{fixed_display}</td></tr>'
        
        # שורות סיכום
        if total_annuity > 0 or total_fixed > 0:
            simulation_summary_html += f'<tr class="sum-row"><td colspan="2" class="text-start">סה"כ:</td><td class="money" style="color:#2563eb;font-weight:bold;">₪{total_annuity:,.2f}</td><td class="money" style="color:#10b981;font-weight:bold;">₪{total_fixed:,.2f}</td></tr>'
    else:
        simulation_summary_html = '<tr><td colspan="4" style="padding:20px; color:#999;">אין נתוני סימולציה</td></tr>'
    
    return REPORT_TEMPLATE.replace('{{ family_name }}', data['family_name']) \
                          .replace('{{ date }}', datetime.now().strftime("%d/%m/%Y")) \
                          .replace('{{ members_html | safe }}', members_html) \
                          .replace('{{ checklist_html | safe }}', checklist_html) \
                          .replace('{{ fin_checklist_html | safe }}', fin_checklist_html) \
                          .replace('{{ client_summary_html | safe }}', client_summary_html) \
                          .replace('{{ simulation_summary_html | safe }}', simulation_summary_html) \
                          .replace('{{ ins_rows | safe }}', ins_rows) \
                          .replace('{{ fin_rows | safe }}', fin_rows) \
                          .replace('{{ total_prem }}', f"{total_prem:,.2f}") \
                          .replace('{{ total_sav }}', f"{total_sav:,.2f}") \
                          .replace('{{ total_risk }}', f"{total_risk:,.2f}") \
                          .replace('{{ total_count }}', str(total_count)) \
                          .replace('{{ risk_chart_data | tojson }}', json.dumps(risk_distribution)) \
                          .replace('{{ product_chart_data | tojson }}', json.dumps(product_distribution)) \
                          .replace('{{ equity_fixed_chart_data | tojson }}', json.dumps(equity_fixed_distribution))

def _parse_age(val):
    """מפרק גיל מטקסט (למשל '35' או '35-40') ומחזיר מספר או None."""
    if val is None or (isinstance(val, float) and (val != val or val == 0)): return None
    s = str(val).strip().replace(',', '.')
    m = re.match(r'^(\d+)', s)
    return int(m.group(1)) if m else None

def _aggregate_per_client(raw_ins, raw_fin, members):
    """מאגד נתונים לכל לקוח: פרמיה, כיסוי ריסק חיים, צבירה, גיל."""
    agg = {}
    for r in raw_ins or []:
        c = (r.get('client') or '').strip()
        if not c: continue
        if c not in agg: agg[c] = {'prem': 0, 'risk': 0, 'sav': 0, 'age': None, 'has_risk': False}
        prem = float(r.get('premium') or 0)
        cov = float(r.get('coverage') or 0)
        ptype = (r.get('type') or '')
        agg[c]['prem'] += prem
        if any(x in ptype for x in ['חיים', 'ריסק', 'מוות', 'משכנתא']):
            agg[c]['risk'] += cov
            agg[c]['has_risk'] = True
    for r in raw_fin or []:
        c = (r.get('client') or '').strip()
        if not c: continue
        if c not in agg: agg[c] = {'prem': 0, 'risk': 0, 'sav': 0, 'age': None, 'has_risk': False}
        agg[c]['sav'] += float(r.get('balance') or 0)
    for name, m in (members or {}).items():
        age = _parse_age(m.get('age'))
        if name in agg: agg[name]['age'] = age
        # ניסיון התאמה חלקית (שם משפחה וכו')
        for c in agg:
            if c not in (members or {}) and (name in c or c in name) and agg[c]['age'] is None:
                agg[c]['age'] = age
                break
    return agg

def _generate_insights(agg, raw_ins, raw_fin):
    """מייצר רשימת תובנות מנתונים מאוגדים. מחזיר [{client, text, severity}]."""
    insights = []
    SAV_LOW = 50_000
    SAV_AGE_THRESHOLD = 30
    for client, d in agg.items():
        prem, risk, sav, age = d['prem'], d['risk'], d['sav'], d.get('age')
        if prem > 0 and risk == 0:
            insights.append({'client': client, 'text': 'משלם פרמיות אך ללא כיסוי ריסק חיים', 'severity': 'חשוב'})
        if age is not None and age > SAV_AGE_THRESHOLD and sav < SAV_LOW:
            insights.append({'client': client, 'text': f'צבירה פנסיונית נמוכה (₪{sav:,.0f}) ביחס לגיל', 'severity': 'להערכה'})
        if prem > 0 and risk > 0 and risk < 100_000:
            insights.append({'client': client, 'text': f'כיסוי ריסק חיים נמוך (₪{risk:,.0f})', 'severity': 'חשוב'})
    # פיזור דמי ניהול / ריכוז – לפי גופים
    companies = {}
    for r in (raw_fin or []):
        c = (r.get('client') or '').strip()
        co = (r.get('company') or r.get('fee') or '').strip() or 'לא צוין'
        if not c: continue
        companies.setdefault(c, set()).add(co)
    for client, g in companies.items():
        if len(g) == 1 and agg.get(client, {}).get('sav', 0) > 0:
            insights.append({'client': client, 'text': 'ריכוז במוצר/גוף אחד – כדאי להעריך פיזור', 'severity': 'להערכה'})
    # חסרים מוצרים סטנדרטיים: אין פנסיה/ביטוח מנהלים/השתלמות
    fin_products = {}
    keywords_prod = ['פנסיה', 'מנהלים', 'השתלמות', 'קופ"ג', 'קרן']
    for r in (raw_fin or []):
        c = (r.get('client') or '').strip()
        p = (r.get('product') or '').strip()
        if not c: continue
        s = fin_products.setdefault(c, set())
        for kw in keywords_prod:
            if kw in p: s.add(kw)
    for client, d in agg.items():
        if d.get('sav', 0) == 0: continue
        prods = fin_products.get(client, set())
        missing = []
        if 'פנסיה' not in prods: missing.append('פנסיה')
        if 'מנהלים' not in prods: missing.append('ביטוח מנהלים')
        if missing:
            insights.append({'client': client, 'text': f'חסרים מוצרים סטנדרטיים: {", ".join(missing)}', 'severity': 'להערכה'})
    return insights

def _generate_recommendations_from_insights(insights):
    """מייצר המלצות טיפול מתוך תובנות. מחזיר [{title, recommendation, background, client}]."""
    recs = []
    for i in insights:
        t = i['text']
        c = i.get('client', '')
        if 'ריסק חיים' in t and 'ללא כיסוי' in t:
            recs.append({'title': 'כיסוי ריסק חיים', 'recommendation': 'לבחון הוספת ביטוח חיים/ריסק כדי להגן על המשפחה במקרה פטירה.', 'background': t, 'client': c, 'priority': 1})
        elif 'צבירה פנסיונית נמוכה' in t:
            recs.append({'title': 'חיסכון פנסיוני', 'recommendation': 'להעריך הגדלת הפרשה לפנסיה או הפעלת תוכנית חיסכון ארוכת טווח.', 'background': t, 'client': c, 'priority': 2})
        elif 'כיסוי ריסק חיים נמוך' in t:
            recs.append({'title': 'כיסוי ריסק חיים', 'recommendation': 'לבדוק אם כיסוי ריסק החיים הקיים מספק לפי הכנסה וחובות.', 'background': t, 'client': c, 'priority': 1})
        elif 'ריכוז' in t and 'פיזור' in t:
            recs.append({'title': 'פיזור השקעות', 'recommendation': 'להשוות מוצרים בדמי ניהול ולבחון פיזור בין גופים.', 'background': t, 'client': c, 'priority': 3})
        elif 'חסרים מוצרים' in t:
            recs.append({'title': 'מוצרים חסרים', 'recommendation': 'לבחון השלמת תיק עם פנסיה, ביטוח מנהלים או השתלמות בהתאם לצרכים.', 'background': t, 'client': c, 'priority': 2})
    recs.sort(key=lambda x: (x['priority'], x.get('client', '')))
    return recs

def _executive_summary(insights, recommendations, family_name):
    """מחזיר 2–4 משפטים סיכום."""
    name = family_name or 'הלקוח'
    if not insights and not recommendations:
        return f"תיק {name} נראה מאוזן. לא זוהו חריגות מרכזיות; מומלץ להמשיך במעקב שגרתי."
    parts = []
    n = len(insights)
    if n > 0:
        parts.append(f"זוהו {n} תובנות רלוונטיות בתיק {name}.")
    high = [i for i in insights if i.get('severity') == 'חשוב']
    if high:
        parts.append("בין הנקודות החשובות: כיסוי ריסק חיים ועקביות בחיסכון פנסיוני.")
    if recommendations:
        parts.append(f"מומלץ לטפל ב־{len(recommendations)} נושאים לפי סדר העדיפות שבדוח.")
    if not parts:
        parts.append(f"מומלץ לעבור על התובנות וההמלצות המפורטות בדוח ולהתאים תוכנית טיפול ל־{name}.")
    return " ".join(parts)

def generate_insights_report(data):
    """מייצר דוח תובנות והמלצות טיפול. מחזיר dict ל־API."""
    raw_ins = data.get('raw_ins') or []
    raw_fin = data.get('raw_fin') or []
    members = data.get('members') or {}
    family_name = data.get('family_name') or 'כללי'
    agg = _aggregate_per_client(raw_ins, raw_fin, members)
    insights = _generate_insights(agg, raw_ins, raw_fin)
    recommendations = _generate_recommendations_from_insights(insights)
    summary = _executive_summary(insights, recommendations, family_name)
    # נספח טבלאות מקוצר – סיכום ביטוח/פיננסי לפי לקוח (מקוצר)
    appendix_ins = [{'client': r.get('client'), 'type': r.get('type'), 'coverage': r.get('coverage'), 'premium': r.get('premium')} for r in raw_ins[:50]]
    appendix_fin = [{'client': r.get('client'), 'product': r.get('product'), 'balance': r.get('balance'), 'fee': r.get('fee')} for r in raw_fin[:50]]
    return {
        'executive_summary': summary,
        'insights': insights,
        'recommendations': recommendations,
        'appendix_ins': appendix_ins,
        'appendix_fin': appendix_fin,
        'family_name': family_name,
    }

def generate_recommendations_data(data):
    # פונקציה זו מחזירה נתונים גולמיים ל-Frontend אם צריך (לשימוש בדשבורד)
    # שמורה לתאימות לאחור; דוח תובנות חדש מגיע מ־generate_insights_report.
    return []

def _has_permission(user, perm):
    if not user or not getattr(user, 'username', None):
        return False
    if user.username == ADMIN_USERNAME:
        return True
    ud = get_users_dict().get(user.username) or {}
    perms = ud.get('permissions') or []
    return perm in perms

@app.before_request
def _update_active_session():
    if current_user.is_authenticated and session.get('_auth_token'):
        token = session['_auth_token']
        with _SESSIONS_LOCK:
            if token in ACTIVE_SESSIONS:
                ACTIVE_SESSIONS[token]['last_seen_at'] = datetime.utcnow().isoformat()

# --- נתיבי Flask ---
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            return jsonify({"error": "שם משתמש וסיסמה נדרשים"}), 400
        
        users = get_users_dict()
        if username in users:
            user_data = users[username]
            if bcrypt.checkpw(password.encode('utf-8'), user_data['password_hash'].encode('utf-8')):
                user = User(user_data['id'], username)
                login_user(user)
                token = secrets.token_hex(16)
                session['_auth_token'] = token
                with _SESSIONS_LOCK:
                    ACTIVE_SESSIONS[token] = {
                        'user_id': user_data['id'],
                        'username': username,
                        'login_at': datetime.utcnow().isoformat(),
                        'last_seen_at': datetime.utcnow().isoformat()
                    }
                return jsonify({"success": True, "message": "התחברות הצליחה"})
        
        return jsonify({"error": "שם משתמש או סיסמה שגויים"}), 401
    
    return send_from_directory('templates', 'login.html')

@app.route('/logout')
@login_required
def logout():
    token = session.pop('_auth_token', None)
    if token:
        with _SESSIONS_LOCK:
            ACTIVE_SESSIONS.pop(token, None)
    logout_user()
    return redirect(url_for('login'))

@app.route('/check_auth')
def check_auth():
    out = {"authenticated": current_user.is_authenticated}
    if current_user.is_authenticated:
        out["username"] = getattr(current_user, 'username', None)
    return jsonify(out)

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "נדרשת התחברות"}), 401
        if getattr(current_user, 'username', None) != ADMIN_USERNAME:
            return jsonify({"error": "גישה מנהלים בלבד"}), 403
        return f(*args, **kwargs)
    return wrapped

@app.route('/admin')
@login_required
@admin_required
def admin_page():
    return send_from_directory('templates', 'admin.html')

@app.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def admin_list_users():
    users = _load_users_json()
    out = []
    for u in users:
        out.append({
            "id": u["id"],
            "username": u["username"],
            "role": u.get("role", "user"),
            "created_at": u.get("created_at"),
            "permissions": u.get("permissions") if isinstance(u.get("permissions"), list) else list(DEFAULT_PERMISSIONS)
        })
    out.insert(0, {"id": ADMIN_ID, "username": ADMIN_USERNAME, "role": "admin", "created_at": None, "permissions": list(ALL_PERMISSIONS)})
    return jsonify(out)

@app.route('/admin/users', methods=['POST'])
@login_required
@admin_required
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "שם משתמש וסיסמה נדרשים"}), 400
    ok, msg = create_user(username, password)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"success": True, "id": msg})

@app.route('/admin/users/<user_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_user(user_id):
    data = request.get_json(silent=True) or {}
    new_password = (data.get("password") or "").strip()
    permissions = data.get("permissions")
    updated = False
    if isinstance(permissions, list):
        if not update_user_permissions(user_id, permissions):
            return jsonify({"error": "משתמש לא נמצא"}), 404
        updated = True
    if new_password:
        if not update_user_password(user_id, new_password):
            return jsonify({"error": "משתמש לא נמצא"}), 404
        updated = True
    if not updated:
        return jsonify({"error": "נדרשת סיסמה או הרשאות לעדכון"}), 400
    return jsonify({"success": True})

@app.route('/admin/users/<user_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_user(user_id):
    if not delete_user(user_id):
        return jsonify({"error": "לא ניתן למחוק את ADMIN"}), 400
    return jsonify({"success": True})

@app.route('/admin/productions')
@login_required
@admin_required
def admin_productions():
    user_id = request.args.get("user_id")
    limit = int(request.args.get("limit", 50))
    data = get_productions(user_id=user_id if user_id else None, limit=limit)
    return jsonify(data)

@app.route('/admin/sessions')
@login_required
@admin_required
def admin_sessions():
    with _SESSIONS_LOCK:
        out = [
            {"username": v["username"], "user_id": v["user_id"], "login_at": v["login_at"], "last_seen_at": v["last_seen_at"]}
            for v in ACTIVE_SESSIONS.values()
        ]
    return jsonify(out)

@app.route('/admin/permissions-list')
@login_required
@admin_required
def admin_permissions_list():
    return jsonify({"permissions": [
        {"id": "view_dashboards", "label": "צפייה בדשבורדים ורשימות"},
        {"id": "upload", "label": "העלאת קבצים וצור דשבורד"},
        {"id": "save_crm", "label": "שמירה ל-CRM"},
        {"id": "delete", "label": "מחיקת תיקים ודשבורדים"},
        {"id": "admin", "label": "ניהול מערכת (מנהל)"}
    ]})

@app.route('/render_report', methods=['POST'])
@login_required
def render_report():
    """מקבל raw_data (raw_ins, raw_fin, members) ומחזיר HTML + insights_report – לשימוש אחרי מיזוג 'הוסף קבצים'."""
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    data = request.get_json(silent=True) or {}
    raw = data.get("raw_data") or data
    merged = {
        "family_name": raw.get("family_name") or "כללי",
        "members": raw.get("members") or {},
        "raw_ins": raw.get("raw_ins") or [],
        "raw_fin": raw.get("raw_fin") or [],
    }
    try:
        html_content = generate_single_html_report(merged)
        insights_report = generate_insights_report(merged)
        return jsonify({"html": html_content, "insights_report": insights_report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboards', methods=['GET'])
@login_required
def api_dashboards_list():
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'view_dashboards'):
        return jsonify({"error": "אין הרשאה לצפייה"}), 403
    created_by = request.args.get('created_by')
    data = api_list_dashboards(created_by=created_by)
    return jsonify(data)

@app.route('/api/dashboards', methods=['POST'])
@login_required
def api_dashboards_create():
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'save_crm'):
        return jsonify({"error": "אין הרשאה לשמירה ל-CRM"}), 403
    body = request.get_json(silent=True) or {}
    family_name = (body.get('family_name') or body.get('family') or 'כללי').strip()
    raw_data = body.get('raw_data') or {}
    raw_data = {
        'raw_ins': raw_data.get('raw_ins') or [],
        'raw_fin': raw_data.get('raw_fin') or [],
        'members': raw_data.get('members') or {}
    }
    html = body.get('html') or ''
    insights_report = body.get('insights_report') or {}
    file_names = body.get('file_names') or []
    if not family_name:
        return jsonify({"error": "family_name נדרש"}), 400
    dash, err = api_create_dashboard(family_name, raw_data, html, insights_report, current_user.id, file_names)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(dash), 201

@app.route('/api/dashboards/<dashboard_id>')
@login_required
def api_dashboards_get(dashboard_id):
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'view_dashboards'):
        return jsonify({"error": "אין הרשאה לצפייה"}), 403
    d = api_get_dashboard(dashboard_id)
    if not d:
        return jsonify({"error": "דשבורד לא נמצא"}), 404
    return jsonify(d)

@app.route('/api/dashboards/<dashboard_id>', methods=['DELETE'])
@login_required
def api_dashboards_delete(dashboard_id):
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'delete'):
        return jsonify({"error": "אין הרשאה למחיקה"}), 403
    if not api_delete_dashboard(dashboard_id):
        return jsonify({"error": "דשבורד לא נמצא"}), 404
    return jsonify({"success": True})

@app.route('/api/dashboards/<dashboard_id>', methods=['PUT'])
@login_required
def api_dashboards_update(dashboard_id):
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'save_crm'):
        return jsonify({"error": "אין הרשאה לעדכון CRM"}), 403
    body = request.get_json(silent=True) or {}
    family_name = body.get('family_name')
    raw_data = body.get('raw_data')
    if not family_name and not raw_data:
        return jsonify({"error": "נדרש family_name או raw_data לעדכון"}), 400
    if not api_update_dashboard(dashboard_id, family_name=family_name, raw_data=raw_data):
        return jsonify({"error": "דשבורד לא נמצא"}), 404
    d = api_get_dashboard(dashboard_id)
    return jsonify(d)

@app.route('/')
@login_required
def index():
    """מסך הבית אחרי התחברות – מערכת CRM מאוחדת (client)"""
    return send_from_directory('.', 'client.html')

@app.route('/360')
@login_required
def page_360():
    """מבט 360 – העלאה, דשבורד, שמור ל-CRM"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    # הגנה מפני Path Traversal
    path_obj = Path(path)
    
    # index.html נמסר רק דרך / עם אימות – לא דרך סטטיק
    if path.strip().lower() == 'index.html':
        return jsonify({"error": "קובץ לא מורשה"}), 403
    
    # בדיקה שהנתיב לא מכיל .. או /
    if '..' in path or path_obj.is_absolute():
        return jsonify({"error": "נתיב לא חוקי"}), 403
    
    # בדיקה אם הקובץ ברשימת הקבצים המותרים
    filename = path_obj.name
    if filename in ALLOWED_STATIC_FILES:
        return send_from_directory('.', path)
    
    # בדיקה לפי סיומת
    if path_obj.suffix.lower() in ALLOWED_STATIC_EXTENSIONS:
        # בדיקה שהקובץ בתיקיית הפרויקט בלבד
        full_path = Path('.').resolve() / path
        if not str(full_path).startswith(str(Path('.').resolve())):
            return jsonify({"error": "נתיב לא חוקי"}), 403
        return send_from_directory('.', path)
    
    return jsonify({"error": "קובץ לא מורשה"}), 403

@app.route('/upload', methods=['POST'])
def upload_files():
    if not current_user.is_authenticated:
        return jsonify({"error": "נדרשת התחברות"}), 401
    if not _has_permission(current_user, 'upload'):
        return jsonify({"error": "אין הרשאה להעלאת קבצים"}), 403
    if 'files[]' not in request.files: return jsonify({"error": "No files"}), 400
    files = request.files.getlist('files[]')
    grouped_reports = {} 
    
    print(f"\n{'='*60}")
    print(f"התחלת עיבוד {len(files)} קבצים")
    print(f"{'='*60}\n")

    for file_idx, file in enumerate(files, 1):
        try:
            filename = file.filename
            print(f"\n{'='*80}")
            print(f"[{file_idx}/{len(files)}] מעבד קובץ: {filename}")
            print(f"{'='*80}")
            
            # זיהוי סוג הקובץ
            filename_lower = filename.lower()
            is_dat = filename_lower.endswith('.dat')
            is_csv = filename_lower.endswith('.csv')
            is_xlsx = filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls')
            print(f"  [זיהוי קובץ] שם: {filename}, DAT: {is_dat}, CSV: {is_csv}, Excel: {is_xlsx}")
            
            # וידוא שהקובץ לא ריק
            file.stream.seek(0, 2)  # מעבר לסוף הקובץ
            file_size = file.stream.tell()
            file.stream.seek(0)  # חזרה לתחילת הקובץ
            print(f"  [גודל קובץ] {file_size} bytes")
            
            if file_size == 0:
                print(f"  [⚠] קובץ ריק - מדלג")
                continue
            
            # כל הקבצים יעובדו יחד בדוח אחד
            family_key = "כללי"
            
            print(f"  → כל הקבצים יעובדו יחד תחת: '{family_key}'")

            if family_key not in grouped_reports:
                grouped_reports[family_key] = { "family_name": family_key, "members": {}, "raw_ins": [], "raw_fin": [] }
                print(f"  → נוצר דוח חדש עבור '{family_key}'")
            
            current_report = grouped_reports[family_key]
            raw_ins_before = len(current_report["raw_ins"])
            raw_fin_before = len(current_report["raw_fin"])
            print(f"  → לפני עיבוד: {raw_ins_before} ביטוחים, {raw_fin_before} פיננסיים")
            
            dfs = []
            
            # בדיקה אם קובץ DAT מכיל XML (פורמט מסלקה)
            if is_dat:
                print(f"  [DAT] זה קובץ DAT - מתחיל עיבוד...")
                file.stream.seek(0)
                file_bytes = file.read()
                file.stream.seek(0)
                
                # בדיקה אם זה תוכן XML
                is_xml = False
                try:
                    # זיהוי XML על ידי בדיקת הבייטים הראשונים
                    file_start = file_bytes[:1000].decode('utf-8', errors='ignore').strip()
                    print(f"קובץ {filename}: תחילת הקובץ (1000 תווים ראשונים): {file_start[:200]}...")
                    
                    # בדיקה אם זה XML - מחפש <?xml או <Mimshak או תגיות מסלקה
                    is_xml_check = (file_start.startswith('<?xml') or 
                                   file_start.startswith('<Mimshak') or
                                   (file_start.startswith('<') and any(tag in file_start for tag in ['Mimshak', 'YeshutYatzran', 'Mutzarim', 'HeshbonOPolisa', 'YeshutLakoach', 'BlockItrot', 'YitraLefiGilPrisha'])))
                    
                    print(f"בדיקת XML: startswith('<?xml')={file_start.startswith('<?xml')}, startswith('<Mimshak')={file_start.startswith('<Mimshak')}, contains tags={any(tag in file_start for tag in ['Mimshak', 'YeshutYatzran'])}")
                    
                    if is_xml_check:
                        is_xml = True
                        print(f"✓ זוהה קובץ XML (DAT): {filename} - יעובד לפיננסי (raw_fin) וביטוחי (raw_ins)")
                        
                        # זה קובץ DAT - נפענח אותו גם לפיננסי וגם לביטוחי
                        # 1. נתונים פיננסיים
                        financial_data = parse_dat_file(file_bytes)
                        print(f"✓ parse_dat_file החזיר {len(financial_data)} רשומות פיננסיות מקובץ {filename}")
                        
                        if financial_data:
                            print(f"✓ לפני הוספה: יש {len(current_report['raw_fin'])} רשומות ב-raw_fin")
                            current_report["raw_fin"].extend(financial_data)
                            print(f"✓ אחרי הוספה: יש {len(current_report['raw_fin'])} רשומות ב-raw_fin")
                            print(f"✓ הוספו {len(financial_data)} רשומות פיננסיות ל-raw_fin")
                            if len(financial_data) > 0:
                                print(f"✓ דוגמה לנתון פיננסי: {financial_data[0]}")
                        else:
                            print(f"⚠ לא נמצאו נתונים פיננסיים בקובץ {filename}")
                        
                        # 2. נתונים ביטוחיים
                        insurance_data = parse_dat_file_insurance(file_bytes)
                        print(f"✓ parse_dat_file_insurance החזיר {len(insurance_data)} רשומות ביטוחיות מקובץ {filename}")
                        
                        if insurance_data:
                            print(f"✓ לפני הוספה: יש {len(current_report['raw_ins'])} רשומות ב-raw_ins")
                            current_report["raw_ins"].extend(insurance_data)
                            print(f"✓ אחרי הוספה: יש {len(current_report['raw_ins'])} רשומות ב-raw_ins")
                            print(f"✓ הוספו {len(insurance_data)} רשומות ביטוחיות ל-raw_ins")
                            if len(insurance_data) > 0:
                                print(f"✓ דוגמה לנתון ביטוחי: {insurance_data[0]}")
                        else:
                            print(f"⚠ לא נמצאו נתונים ביטוחיים בקובץ {filename}")
                        
                        print(f"  [DAT] ✓ סיום עיבוד קובץ DAT - ממשיך לקובץ הבא")
                        continue  # דילוג על עיבוד DataFrame
                    else:
                        print(f"  [DAT] ✗ קובץ {filename} לא זוהה כ-XML")
                except UnicodeDecodeError:
                    # נסה עם encoding אחר
                    try:
                        file_start = file_bytes[:500].decode('cp1255', errors='ignore').strip()
                        if (file_start.startswith('<?xml') or 
                            file_start.startswith('<Mimshak') or
                            (file_start.startswith('<') and any(tag in file_start for tag in ['Mimshak', 'YeshutYatzran', 'Mutzarim', 'HeshbonOPolisa', 'YeshutLakoach', 'BlockItrot', 'YitraLefiGilPrisha']))):
                            is_xml = True
                            print(f"זוהה קובץ XML (DAT, cp1255): {filename} - יעובד לפיננסי (raw_fin) וביטוחי (raw_ins)")
                            
                            # נתונים פיננסיים
                            financial_data = parse_dat_file(file_bytes)
                            print(f"נמצאו {len(financial_data)} רשומות פיננסיות מקובץ {filename}")
                            if financial_data:
                                current_report["raw_fin"].extend(financial_data)
                                print(f"הוספו {len(financial_data)} רשומות פיננסיות ל-raw_fin")
                            
                            # נתונים ביטוחיים
                            insurance_data = parse_dat_file_insurance(file_bytes)
                            print(f"נמצאו {len(insurance_data)} רשומות ביטוחיות מקובץ {filename}")
                            if insurance_data:
                                current_report["raw_ins"].extend(insurance_data)
                                print(f"הוספו {len(insurance_data)} רשומות ביטוחיות ל-raw_ins")
                            
                            continue
                    except:
                        pass
                except Exception as e:
                    print(f"שגיאה בזיהוי XML בקובץ {filename}: {e}")
                    import traceback
                    traceback.print_exc()
                
                # אם לא XML, ננסה לפרסר כ-XML בכל מקרה (למקרה שהזיהוי נכשל)
                if not is_xml:
                    try:
                        # נסה לפרסר כ-XML בכל מקרה (DAT -> רק פיננסי)
                        print(f"מנסה לפרסר קובץ {filename} כ-XML (DAT) למרות שלא זוהה - יעובד רק לפיננסי")
                        financial_data = parse_dat_file(file_bytes)
                        if financial_data and len(financial_data) > 0:
                            print(f"נמצאו {len(financial_data)} רשומות פיננסיות (ניסיון שני)")
                            current_report["raw_fin"].extend(financial_data)
                        
                        # גם נתונים ביטוחיים
                        insurance_data = parse_dat_file_insurance(file_bytes)
                        if insurance_data and len(insurance_data) > 0:
                            print(f"נמצאו {len(insurance_data)} רשומות ביטוחיות (ניסיון שני)")
                            current_report["raw_ins"].extend(insurance_data)
                        
                        if financial_data or insurance_data:
                            continue
                    except Exception as e:
                        print(f"נכשל ניסיון פרסור XML: {e}")
                    
                    # אם עדיין לא XML, נטפל כ-CSV
                    print(f"מטפל בקובץ {filename} כ-CSV")
                    try: 
                        dfs.append(pd.read_csv(file, encoding='utf-8', sep=None, engine='python'))
                    except: 
                        try:
                            file.stream.seek(0)
                            dfs.append(pd.read_csv(file, encoding='cp1255', sep=None, engine='python'))
                        except:
                            file.stream.seek(0)
                            dfs.append(pd.read_csv(file, encoding='latin-1', sep=None, engine='python'))
            elif is_csv:
                # טיפול בקבצי CSV - נסה מספר encodings ומופרדים
                print(f"  [CSV] זה קובץ CSV - מתחיל עיבוד...")
                try: 
                    dfs.append(pd.read_csv(file, encoding='utf-8', sep=None, engine='python'))
                    print(f"  [CSV] ✓ קובץ CSV נקרא בהצלחה (UTF-8)")
                except Exception as e: 
                    print(f"  [CSV] ✗ שגיאה ב-UTF-8: {e}, מנסה cp1255...")
                    try:
                        file.stream.seek(0)
                        dfs.append(pd.read_csv(file, encoding='cp1255', sep=None, engine='python'))
                        print(f"  [CSV] ✓ קובץ CSV נקרא בהצלחה (cp1255)")
                    except Exception as e2:
                        print(f"  [CSV] ✗ שגיאה ב-cp1255: {e2}, מנסה latin-1...")
                        file.stream.seek(0)
                        dfs.append(pd.read_csv(file, encoding='latin-1', sep=None, engine='python'))
                        print(f"  [CSV] ✓ קובץ CSV נקרא בהצלחה (latin-1)")
            elif is_xlsx:
                # קבצי אקסל
                print(f"  [Excel] זה קובץ אקסל - מתחיל עיבוד...")
                print(f"  [Excel] → קורא קובץ אקסל: {filename}")
                try:
                    file.stream.seek(0)  # וידוא שהקובץ בתחילתו
                    xls_dict = pd.read_excel(file, sheet_name=None)
                    dfs = list(xls_dict.values())
                    print(f"  [Excel] ✓ נמצאו {len(dfs)} גיליונות בקובץ אקסל")
                    for sheet_idx, df in enumerate(dfs):
                        print(f"    → גיליון {sheet_idx+1}: {len(df)} שורות, {len(df.columns)} עמודות")
                except Exception as e:
                    print(f"  [Excel] ✗ שגיאה בקריאת קובץ אקסל {filename}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            else:
                print(f"  [⚠] קובץ לא מזוהה: {filename} - מדלג")
                continue

            if len(dfs) == 0:
                print(f"  [⚠] אין DataFrames לעיבוד - מדלג על קובץ {filename}")
                continue
                
            print(f"  → סה\"כ {len(dfs)} DataFrame(s) לעיבוד")
            for df_idx, df_raw in enumerate(dfs, 1):
                print(f"\n  [DataFrame {df_idx}/{len(dfs)}] מתחיל עיבוד DataFrame...")
                print(f"    → DataFrame: {len(df_raw)} שורות, {len(df_raw.columns)} עמודות")
                
                # טיפול מיוחד בקבצי CSV עם שני חלקים (ביטוח ופיננסי)
                if is_csv:
                    print(f"  → מעבד קובץ CSV: {filename}")
                    # חיפוש כל הכותרות בקובץ
                    sections = []
                    for i in range(min(len(df_raw), 100)):
                        row_values = df_raw.iloc[i].astype(str).values
                        row_str = " ".join(row_values)
                        # זיהוי חלק ביטוח
                        if ("מבוטח" in row_str or "מבוטחים" in row_str) and ("חברה" in row_str or "סוג כיסוי" in row_str or "פרמיה" in row_str or "סכום ביטוח" in row_str):
                            sections.append((i, 'ins'))
                        # זיהוי חלק פיננסי
                        elif ("חוסך" in row_str or "לקוח" in row_str) and ("צבירה" in row_str or "יתרה" in row_str) and ("דמי ניהול" in row_str or "סטטוס" in row_str):
                            sections.append((i, 'fin'))
                    
                    print(f"  → נמצאו {len(sections)} חלקים בקובץ CSV")
                    # טיפול בכל חלק בנפרד
                    for section_idx, (header_idx, ftype) in enumerate(sections):
                        print(f"  → מעבד חלק {section_idx + 1}/{len(sections)}: {ftype} (שורה {header_idx})")
                        # מציאת סוף החלק (התחלה של החלק הבא או סוף הקובץ)
                        next_section_start = sections[section_idx + 1][0] if section_idx + 1 < len(sections) else len(df_raw)
                        
                        df = df_raw.iloc[header_idx+1:next_section_start].reset_index(drop=True)
                        raw_cols = df_raw.iloc[header_idx].values
                        new_cols = []
                        col_counts = {}
                        for col in raw_cols:
                            c_str = str(col).strip()
                            if c_str in col_counts:
                                col_counts[c_str] += 1
                                new_cols.append(f"{c_str}.{col_counts[c_str]}")
                            else:
                                col_counts[c_str] = 0
                                new_cols.append(c_str)
                        df.columns = new_cols
                        
                        # טיפול לפי סוג החלק
                        if ftype == 'ins':
                            # טיפול בביטוח - עם כותרת "מבוטח" או "מבוטחים"
                            print(f"    → מעבד חלק ביטוח, {len(df)} שורות")
                            col_client = next((c for c in df.columns if 'מבוטח' in c), None)
                            if not col_client:
                                print(f"    ✗ לא נמצאה עמודת מבוטח")
                                continue
                            
                            print(f"    → עמודת לקוח: '{col_client}'")
                            ins_count_csv = 0
                            for _, row in df.iterrows():
                                client_name = clean_text(row.get(col_client))
                                if not is_valid_name(client_name):
                                    continue
                                
                                prod = clean_text(row.get('סוג כיסוי') or row.get('ביטוח'))
                                if not prod:
                                    continue
                                
                                prem = clean_currency(row.get('פרמיה') or row.get('עלות'))
                                cov = clean_currency(row.get('סכום ביטוח') or row.get('סכום פיצוי'))
                                
                                if prem == 0 and cov == 0 and not clean_text(row.get('הערות')):
                                    continue
                                
                                for sub_client in re.split(r'[,&+]', client_name):
                                    sub_client = sub_client.strip()
                                    if is_valid_name(sub_client):
                                        current_report["raw_ins"].append({
                                            "client": sub_client,
                                            "company": clean_text(row.get('חברה')),
                                            "policy": clean_text(row.get('פוליסה') or row.get('מ.פוליסה')),
                                            "start_date": clean_text(row.get('תחילה') or row.get('תחילת ביטוח')),
                                            "type": prod,
                                            "coverage": cov,
                                            "premium": prem,
                                            "notes": clean_text(row.get('הערות'))
                                        })
                                        ins_count_csv += 1
                            print(f"    ✓ נוספו {ins_count_csv} רשומות ביטוח מחלק CSV זה")
                        
                        elif ftype == 'fin':
                            # טיפול בפיננסי - רק בקבצי CSV, לא אקסל
                            print(f"    → מעבד חלק פיננסי, {len(df)} שורות")
                            col_client = next((c for c in df.columns if 'חוסך' in c or 'לקוח' in c), None)
                            if not col_client:
                                print(f"    ✗ לא נמצאה עמודת חוסך/לקוח")
                                continue
                            
                            print(f"    → עמודת לקוח: '{col_client}'")
                            fin_count_csv = 0
                            for _, row in df.iterrows():
                                client = clean_text(row.get(col_client))
                                if not is_valid_name(client):
                                    continue
                                
                                prod = clean_text(row.get('מוצר') or row.get('שם מוצר'))
                                bal = clean_currency(row.get('צבירה') or row.get('יתרה'))
                                
                                if bal == 0 and not prod:
                                    continue
                                
                                risk_level = clean_text(row.get('רמת סיכון'))
                                simulation = clean_currency(row.get('צפי פרישה') or row.get('סימולציה לפרישה'))
                                
                                current_report["raw_fin"].append({
                                    "client": client,
                                    "product": prod,
                                    "company": clean_text(row.get('גוף מוסדי') or row.get('חברה')),
                                    "balance": bal,
                                    "status": clean_text(row.get('סטטוס') or row.get('מצב קיים')),
                                    "fee": clean_text(row.get('דמי ניהול')),
                                    "rec": clean_text(row.get('המלצות')),
                                    "risk": risk_level,
                                    "simulation": simulation
                                })
                                fin_count_csv += 1
                            print(f"    ✓ נוספו {fin_count_csv} רשומות פיננסיות מחלק CSV זה")
                    
                    # דילוג על הלוגיקה הרגילה אם מצאנו חלקים
                    if sections:
                        continue
                
                # לוגיקה רגילה לקבצים אחרים (אקסל וכו')
                file_type_str = 'CSV' if is_csv else 'Excel' if is_xlsx else 'Unknown'
                print(f"  [לוגיקה רגילה] מחפש כותרת בקובץ {filename} (סוג קובץ: {file_type_str})...")
                header_idx, ftype = find_header_and_type(df_raw)
                if header_idx == -1:
                    print(f"  [לוגיקה רגילה] ✗ לא נמצאה כותרת בקובץ {filename}")
                    continue
                
                print(f"  [לוגיקה רגילה] ✓ נמצאה כותרת בשורה {header_idx}, סוג: {ftype} (קובץ: {filename})")

                df = df_raw.iloc[header_idx+1:].reset_index(drop=True)
                raw_cols = df_raw.iloc[header_idx].values
                new_cols = []
                col_counts = {}
                for col in raw_cols:
                    c_str = str(col).strip()
                    if c_str in col_counts:
                        col_counts[c_str] += 1
                        new_cols.append(f"{c_str}.{col_counts[c_str]}")
                    else:
                        col_counts[c_str] = 0
                        new_cols.append(c_str)
                df.columns = new_cols

                if ftype == 'det':
                    # לוגיקה קיימת... (ללא שינוי)
                    parent_name_col = next((c for c in df.columns if c == 'שם'), None)
                    parent_age_col = next((c for c in df.columns if 'גיל' in c and '.' not in c), None)
                    parent_job_col = next((c for c in df.columns if 'עיסוק' in c), None)
                    child_name_col = next((c for c in df.columns if 'שם' in c and c != parent_name_col), None)
                    child_age_col = next((c for c in df.columns if 'גיל' in c and c != parent_age_col), None)

                    for _, row in df.iterrows():
                        if parent_name_col:
                            p = clean_text(row.get(parent_name_col))
                            if is_valid_name(p): current_report["members"][p] = {"age": clean_text(row.get(parent_age_col)), "job": clean_text(row.get(parent_job_col))}
                        if child_name_col:
                            c = clean_text(row.get(child_name_col))
                            if is_valid_name(c): current_report["members"][c] = {"age": clean_text(row.get(child_age_col)), "job": "ילד/ה"}

                elif ftype == 'ins':
                     # לוגיקה קיימת... (ללא שינוי מהותי) - לקבצי אקסל
                    print(f"  [ביטוח] ====== מתחיל עיבוד ביטוח (ins) מקובץ {filename} (אקסל -> ביטוח) ======")
                    col_client = next((c for c in df.columns if 'מבוטח' in c), 'מבוטחים')
                    print(f"  [ביטוח] → עמודת לקוח: '{col_client}'")
                    print(f"  [ביטוח] → מספר שורות: {len(df)}")
                    print(f"  [ביטוח] → עמודות: {list(df.columns)}")
                    last_valid_client = None
                    ins_count = 0
                    for row_idx, (_, row) in enumerate(df.iterrows(), 1):
                        if row_idx <= 3:  # הדפס את 3 הראשונות
                            print(f"  [ביטוח] → שורה {row_idx}: {dict(row)}")
                        raw_name = clean_text(row.get(col_client))
                        if is_valid_name(raw_name): last_valid_client = raw_name
                        elif last_valid_client and (clean_currency(row.get('עלות')) > 0 or clean_currency(row.get('סכום פיצוי')) > 0): pass
                        else: continue

                        client_name = raw_name if is_valid_name(raw_name) else last_valid_client
                        prod = clean_text(row.get('ביטוח') or row.get('סוג כיסוי'))
                        if not prod: continue
                        prem = clean_currency(row.get('עלות') or row.get('פרמיה'))
                        cov = clean_currency(row.get('סכום פיצוי') or row.get('סכום ביטוח'))
                        if prem == 0 and cov == 0 and not clean_text(row.get('הערות')): continue

                        for sub_client in re.split(r'[,&+]', client_name):
                            sub_client = sub_client.strip()
                            if is_valid_name(sub_client):
                                current_report["raw_ins"].append({
                                    "client": sub_client, "company": clean_text(row.get('חברה')),
                                    "policy": clean_text(row.get('מ.פוליסה') or row.get('פוליסה')), "start_date": clean_text(row.get('תחילת ביטוח') or row.get('תחילה')),
                                    "type": prod, "coverage": cov, "premium": prem, "notes": clean_text(row.get('הערות'))
                                })
                                ins_count += 1
                                if ins_count <= 3:  # הדפס את 3 הראשונות
                                    print(f"  [ביטוח] ✓ נוספה רשומה #{ins_count}: {sub_client} - {prod} (כיסוי: {cov}, פרמיה: {prem})")
                    print(f"  [ביטוח] ====== סיום עיבוד ביטוח: נוספו {ins_count} רשומות ביטוח מקובץ {filename} ======")

                elif ftype == 'fin':
                    # קבצי אקסל עם ftype='fin' - נטפל בהם כביטוח (אקסל -> רק ביטוח)
                    print(f"⚠ קובץ אקסל מזוהה כ-'fin' (פיננסי) - נטפל כביטוח. רק קבצי DAT יעובדו לפיננסי.")
                    # נטפל בקובץ האקסל כביטוח במקום לדלג עליו
                    col_client = next((c for c in df.columns if 'מבוטח' in c or 'חוסך' in c or 'לקוח' in c), None)
                    if col_client:
                        print(f"  → מעבד קובץ אקסל כביטוח, עמודת לקוח: '{col_client}'")
                        ins_count = 0
                        for _, row in df.iterrows():
                            client_name = clean_text(row.get(col_client))
                            if not is_valid_name(client_name):
                                continue
                            
                            prod = clean_text(row.get('ביטוח') or row.get('סוג כיסוי') or row.get('מוצר'))
                            if not prod:
                                continue
                            
                            prem = clean_currency(row.get('עלות') or row.get('פרמיה'))
                            cov = clean_currency(row.get('סכום פיצוי') or row.get('סכום ביטוח') or row.get('כיסוי'))
                            
                            if prem == 0 and cov == 0 and not clean_text(row.get('הערות')):
                                continue
                            
                            for sub_client in re.split(r'[,&+]', client_name):
                                sub_client = sub_client.strip()
                                if is_valid_name(sub_client):
                                    current_report["raw_ins"].append({
                                        "client": sub_client,
                                        "company": clean_text(row.get('חברה') or row.get('גוף מוסדי')),
                                        "policy": clean_text(row.get('מ.פוליסה') or row.get('פוליסה')),
                                        "start_date": clean_text(row.get('תחילת ביטוח') or row.get('תחילה')),
                                        "type": prod,
                                        "coverage": cov,
                                        "premium": prem,
                                        "notes": clean_text(row.get('הערות'))
                                    })
                                    ins_count += 1
                        print(f"  ✓ נוספו {ins_count} רשומות ביטוח מקובץ אקסל (שזוהה כ-'fin')")
                    continue
            
            # סיכום עיבוד הקובץ
            raw_ins_after = len(current_report["raw_ins"])
            raw_fin_after = len(current_report["raw_fin"])
            ins_added = raw_ins_after - raw_ins_before
            fin_added = raw_fin_after - raw_fin_before
            print(f"\n{'='*80}")
            print(f"  ✓ סיום עיבוד קובץ {filename}:")
            print(f"    - נוספו {ins_added} רשומות ביטוח (לפני: {raw_ins_before}, אחרי: {raw_ins_after})")
            print(f"    - נוספו {fin_added} רשומות פיננסיות (לפני: {raw_fin_before}, אחרי: {raw_fin_after})")
            print(f"{'='*80}\n")

        except Exception as e:
            print(f"✗ שגיאה בעיבוד קובץ {file.filename}: {e}")
            import traceback
            traceback.print_exc()
            continue  # ממשיך לקבצים הבאים גם אם יש שגיאה

    # סיכום עיבוד
    print(f"\n{'='*60}")
    print(f"סיכום עיבוד:")
    for fam_name, data in grouped_reports.items():
        print(f"  {fam_name}:")
        print(f"    - ביטוחים: {len(data.get('raw_ins', []))} רשומות")
        print(f"    - פיננסיים: {len(data.get('raw_fin', []))} רשומות")
        print(f"    - משתתפים: {len(data.get('members', {}))} אנשים")
    print(f"{'='*60}\n")

    # איחוד כל הדוחות לדוח אחד
    print(f"\n=== איחוד כל הדוחות לדוח אחד ===")
    merged_data = {
        "family_name": "כללי",
        "members": {},
        "raw_ins": [],
        "raw_fin": []
    }
    
    # איחוד כל הנתונים
    for fam_name, data in grouped_reports.items():
        print(f"  → מאחד דוח '{fam_name}': {len(data.get('raw_ins', []))} ביטוחים, {len(data.get('raw_fin', []))} פיננסיים")
        # איחוד ביטוחים
        merged_data["raw_ins"].extend(data.get("raw_ins", []))
        # איחוד פיננסיים
        merged_data["raw_fin"].extend(data.get("raw_fin", []))
        # איחוד משתתפים
        merged_data["members"].update(data.get("members", {}))
    
    print(f"\n=== יצירת דוח מאוחד ===")
    print(f"✓ סה\"כ: {len(merged_data.get('raw_ins', []))} ביטוחים, {len(merged_data.get('raw_fin', []))} פיננסיים, {len(merged_data.get('members', {}))} משתתפים")
    
    html_content = generate_single_html_report(merged_data)
    insights_report = generate_insights_report(merged_data)
    results = [{ 
        "family": "כללי", 
        "html": html_content,
        "recommendations": [],
        "insights_report": insights_report,
        "raw_data": {
            "raw_ins": merged_data.get("raw_ins", []),
            "raw_fin": merged_data.get("raw_fin", []),
            "members": merged_data.get("members", {})
        }
    }]

    append_production(
        current_user.id,
        getattr(current_user, 'username', ''),
        "כללי",
        len(files),
        [f.filename for f in files]
    )

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)