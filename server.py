import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import re
from datetime import datetime
import sys

# הגדרת האפליקציה
app = Flask(__name__, static_folder='.')
CORS(app)

# --- תבנית הדוח (HTML) ---
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>דוח מסכם - {{ family_name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Assistant:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --primary: #2c3e50; --accent: #ec4899; --bg-gray: #f8fafc; }
        body { font-family: 'Assistant', sans-serif; margin: 0; padding: 0; background: #555; color: #333; font-size: 10pt; display: block; }
        .page-container { width: 210mm; min-height: 297mm; background: white; margin: 30px auto; padding: 40px; box-sizing: border-box; box-shadow: 0 0 20px rgba(0,0,0,0.3); position: relative; }
        
        @media print {
            @page { size: A4; margin: 0; }
            body, html { width: 100%; height: 100%; margin: 0; padding: 0; background: white !important; display: block !important; overflow: visible !important; }
            .page-container { width: 100% !important; margin: 0 !important; padding: 15mm !important; box-shadow: none !important; border: none !important; min-height: auto !important; page-break-after: always; }
            .no-print { display: none !important; }
            tr, .kpi-container, .checklist-grid, .mem-item { page-break-inside: avoid; }
            .sec-title { page-break-after: avoid; }
            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
        }
        
        .header { text-align: center; border-bottom: 3px solid var(--accent); padding-bottom: 15px; margin-bottom: 25px; }
        .header img { height: 65px; margin-bottom: 8px; }
        .header h1 { margin: 0; font-size: 24pt; color: var(--primary); font-weight: 800; }
        .header p { margin: 4px 0; color: #666; font-size: 11pt; }
        .kpi-container { display: flex; justify-content: space-between; gap: 15px; margin-bottom: 30px; background: var(--bg-gray); padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; }
        .kpi-box { flex: 1; text-align: center; border-left: 1px solid #cbd5e1; }
        .kpi-box:last-child { border-left: none; }
        .kpi-title { font-size: 10pt; color: #64748b; font-weight: 700; text-transform: uppercase; margin-bottom: 5px; }
        .kpi-value { font-size: 18pt; font-weight: 800; color: #0f172a; line-height: 1; }
        .text-pink { color: var(--accent); } .text-green { color: #10b981; } .text-blue { color: #4361ee; }
        .sec-title { background: var(--primary); color: white; padding: 8px 15px; font-size: 12pt; font-weight: bold; margin-top: 30px; margin-bottom: 15px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; border-left: 5px solid var(--accent); }
        .members-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 25px; }
        .mem-item { background: #fff; padding: 10px; border-radius: 8px; border: 1px solid #e2e8f0; font-size: 10pt; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .mem-item strong { display: block; color: var(--accent); margin-bottom: 3px; font-size: 11pt; }
        .checklist-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 25px; }
        .check-card { display: flex; flex-direction: column; align-items: center; justify-content: start; padding: 12px 5px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; position: relative; min-height: 75px; }
        .check-card.found { background: #f0fdf4; border-color: #86efac; color: #166534; }
        .check-card.missing { background: #fef2f2; border-color: #fca5a5; color: #991b1b; opacity: 0.85; }
        .check-icon { font-size: 16pt; margin-bottom: 8px; }
        .check-label { font-size: 9pt; font-weight: 700; margin-bottom: 3px; }
        .check-status { font-size: 8pt; line-height: 1.1; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 9.5pt; table-layout: fixed; }
        th { background: #f1f5f9; color: #1e293b; padding: 10px 6px; font-weight: bold; border: 1px solid #cbd5e1; text-align: center; }
        td { padding: 8px 6px; border: 1px solid #e2e8f0; text-align: center; vertical-align: middle; word-wrap: break-word; }
        tr:nth-child(even) { background: #f8fafc; }
        .font-bold { font-weight: 700; }
        .text-start { text-align: right !important; padding-right: 8px !important; }
        .sum-row { background: #fff1f2 !important; font-weight: bold; border-top: 2px solid var(--accent); }
        .money { font-family: 'Courier New', Courier, monospace; letter-spacing: -0.5px; font-weight: 600; }
        .footer { text-align: center; font-size: 9pt; color: #94a3b8; border-top: 1px solid #eee; padding-top: 15px; margin-top: 40px; }
    </style>
</head>
<body>
    <div class="page-container">
        <div class="header">
            <img src="/logo.png" onerror="this.style.display='none'">
            <h1>סיכום תיק וניתוח צרכים</h1>
            <p>הוכן עבור: <strong>{{ family_name }}</strong> | תאריך הפקה: {{ date }}</p>
        </div>

        <div class="kpi-container">
            <div class="kpi-box"><div class="kpi-title">פרמיה חודשית</div><div class="kpi-value text-pink">₪{{ total_prem }}</div></div>
            <div class="kpi-box"><div class="kpi-title">סה"כ נכסים</div><div class="kpi-value text-green">₪{{ total_sav }}</div></div>
            <div class="kpi-box"><div class="kpi-title">כיסוי ריסק (חיים)</div><div class="kpi-value text-blue">₪{{ total_risk }}</div></div>
            <div class="kpi-box"><div class="kpi-title">מוצרים בתיק</div><div class="kpi-value">{{ total_count }}</div></div>
        </div>

        <div class="sec-title"><span>משתתפים</span> <i class="fas fa-users"></i></div>
        <div class="members-grid">{{ members_html | safe }}</div>

        <div class="sec-title"><span>מפת הגנות משפחתית</span> <i class="fas fa-shield-halved"></i></div>
        <div class="checklist-grid">{{ checklist_html | safe }}</div>

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

        <div style="page-break-inside: avoid;">
            <div class="sec-title"><span>תיק פיננסי ופנסיוני</span> <i class="fas fa-chart-line"></i></div>
            <table>
                <thead>
                    <tr>
                        <th style="width:12%">חוסך</th><th style="width:15%">מוצר</th><th style="width:12%">גוף מוסדי</th>
                        <th style="width:8%">סטטוס</th><th style="width:12%">צבירה</th><th style="width:10%">דמי ניהול</th><th>המלצות ומידע</th>
                    </tr>
                </thead>
                <tbody>{{ fin_rows | safe }}</tbody>
            </table>
        </div>

        <div class="footer">דוח זה הופק ע"י מערכת AgencyOS | כל הזכויות שמורות לאשר לוי סוכנות לביטוח (2011) בע"מ</div>
    </div>
    <script>
        window.onload = function() { setTimeout(function() { window.print(); }, 1000); };
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

def generate_single_html_report(data):
    total_prem = 0
    total_sav = 0
    total_risk = 0
    total_count = 0
    checklist_data = {k: set() for k in ['risk', 'health', 'ci', 'disability', 'accidents', 'nursing']}

    members_html = ""
    if data['members']:
        for name, m in data['members'].items():
            members_html += f'<div class="mem-item"><strong>{name}</strong><div>{m.get("age","")} {m.get("job","")}</div></div>'
    else:
        members_html = '<div style="grid-column:1/-1;text-align:center;color:#999;">--</div>'

    ins_rows = ""
    if data['raw_ins']:
        for r in sorted(data['raw_ins'], key=lambda x: x['client']):
            prem = r['premium']
            cov = r['coverage']
            ptype = r['type']
            total_prem += prem
            if 'חיים' in ptype or 'ריסק' in ptype: total_risk += cov
            total_count += 1
            if any(x in ptype for x in ['חיים', 'ריסק', 'מוות', 'משכנתא']): checklist_data['risk'].add(ptype)
            if any(x in ptype for x in ['בריאות', 'ניתוח', 'השתל', 'תרופות', 'אמבולטורי', 'ליווי', 'שב"ן']): checklist_data['health'].add(ptype)
            if any(x in ptype for x in ['מחלות', 'סרטן', 'גילוי']): checklist_data['ci'].add(ptype)
            if any(x in ptype for x in ['כושר', 'נכות', 'א.כ.ע']): checklist_data['disability'].add(ptype)
            if any(x in ptype for x in ['תאונות', 'שברים', 'נכויות']): checklist_data['accidents'].add(ptype)
            if 'סיעוד' in ptype: checklist_data['nursing'].add(ptype)
            ins_rows += f"""<tr><td class="font-bold">{r['client']}</td><td>{r['company']}</td><td><strong>{ptype}</strong></td><td>{r['policy']}</td><td>{r['start_date']}</td><td class="money">{f"₪{cov:,}" if cov else '-'}</td><td class="money">{f"₪{prem:,}" if prem else '-'}</td><td class="text-start">{r['notes']}</td></tr>"""
        if total_prem > 0: ins_rows += f'<tr class="sum-row"><td colspan="6" class="text-start">סה"כ פרמיה חודשית:</td><td class="money">₪{total_prem:,}</td><td></td></tr>'
    else:
        ins_rows = '<tr><td colspan="8" style="padding:20px; color:#999;">אין נתוני ביטוח</td></tr>'

    checklist_config = [
        {'key': 'risk', 'label': 'ביטוח חיים', 'icon': 'fa-heart-pulse'},
        {'key': 'health', 'label': 'בריאות פרטי', 'icon': 'fa-user-doctor'},
        {'key': 'ci', 'label': 'מחלות קשות', 'icon': 'fa-virus'},
        {'key': 'disability', 'label': 'אובדן כושר', 'icon': 'fa-wheelchair'},
        {'key': 'accidents', 'label': 'תאונות אישיות', 'icon': 'fa-car-crash'},
        {'key': 'nursing', 'label': 'ביטוח סיעודי', 'icon': 'fa-hands-holding-circle'},
    ]
    checklist_html = ""
    for item in checklist_config:
        found_items = checklist_data[item['key']]
        is_found = len(found_items) > 0
        css = "found" if is_found else "missing"
        icon = "fas fa-check" if is_found else "fas fa-times"
        txt = ", ".join(list(found_items)) if is_found else "חסר / לבדיקה"
        checklist_html += f'<div class="check-card {css}"><i class="fas {item["icon"]} check-icon"></i><div class="check-label">{item["label"]}</div><div class="check-status">{txt}</div></div>'

    fin_rows = ""
    if data['raw_fin']:
        for r in sorted(data['raw_fin'], key=lambda x: x['client']):
            bal = r['balance']
            total_sav += bal
            total_count += 1
            fin_rows += f"""<tr><td class="font-bold">{r['client']}</td><td><strong>{r['product']}</strong></td><td>{r['company']}</td><td>{r['status']}</td><td class="money" style="color:#166534;font-weight:bold;">{f"₪{bal:,}" if bal else '-'}</td><td>{r['fee']}</td><td class="text-start" style="font-size:8pt;">{r['rec']}</td></tr>"""
        if total_sav > 0: fin_rows += f'<tr class="sum-row"><td colspan="4" class="text-start">סה"כ נכסים:</td><td class="money">₪{total_sav:,}</td><td colspan="2"></td></tr>'
    else:
        fin_rows = '<tr><td colspan="7" style="padding:20px; color:#999;">אין נתוני פיננסים</td></tr>'

    return REPORT_TEMPLATE.replace('{{ family_name }}', data['family_name']) \
                          .replace('{{ date }}', datetime.now().strftime("%d/%m/%Y")) \
                          .replace('{{ members_html | safe }}', members_html) \
                          .replace('{{ checklist_html | safe }}', checklist_html) \
                          .replace('{{ ins_rows | safe }}', ins_rows) \
                          .replace('{{ fin_rows | safe }}', fin_rows) \
                          .replace('{{ total_prem }}', f"{total_prem:,}") \
                          .replace('{{ total_sav }}', f"{total_sav:,}") \
                          .replace('{{ total_risk }}', f"{total_risk:,}") \
                          .replace('{{ total_count }}', str(total_count))

# --- נתיבי Flask ---
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files: return jsonify({"error": "No files"}), 400
    files = request.files.getlist('files[]')
    grouped_reports = {} 

    for file in files:
        try:
            filename = file.filename
            clean_name = re.sub(r'\.(xlsx|xls|csv)$', '', filename)
            family_key = re.sub(r'(ניתוח תיק|ניהול סיכונים|פרטים אישיים|ביטוחים|פנסיה|\d+|עותק).*', '', clean_name).strip("- ").strip()
            if not family_key: family_key = "כללי"

            if family_key not in grouped_reports:
                grouped_reports[family_key] = { "family_name": family_key, "members": {}, "raw_ins": [], "raw_fin": [] }
            
            current_report = grouped_reports[family_key]
            dfs = []
            if filename.endswith('.csv'):
                try: dfs.append(pd.read_csv(file, encoding='utf-8'))
                except: 
                    file.stream.seek(0)
                    dfs.append(pd.read_csv(file, encoding='cp1255'))
            else:
                xls_dict = pd.read_excel(file, sheet_name=None)
                dfs = list(xls_dict.values())

            for df_raw in dfs:
                header_idx, ftype = find_header_and_type(df_raw)
                if header_idx == -1: continue

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
                    col_client = 'מבוטחים'
                    last_valid_client = None
                    for _, row in df.iterrows():
                        raw_name = clean_text(row.get(col_client))
                        if is_valid_name(raw_name): last_valid_client = raw_name
                        elif last_valid_client and (clean_currency(row.get('עלות')) > 0 or clean_currency(row.get('סכום פיצוי')) > 0): pass
                        else: continue

                        client_name = raw_name if is_valid_name(raw_name) else last_valid_client
                        prod = clean_text(row.get('ביטוח'))
                        if not prod: continue
                        prem = clean_currency(row.get('עלות'))
                        cov = clean_currency(row.get('סכום פיצוי'))
                        if prem == 0 and cov == 0 and not clean_text(row.get('הערות')): continue

                        for sub_client in re.split(r'[,&]', client_name):
                            sub_client = sub_client.strip()
                            if is_valid_name(sub_client):
                                current_report["raw_ins"].append({
                                    "client": sub_client, "company": clean_text(row.get('חברה')),
                                    "policy": clean_text(row.get('מ.פוליסה')), "start_date": clean_text(row.get('תחילת ביטוח')),
                                    "type": prod, "coverage": cov, "premium": prem, "notes": clean_text(row.get('הערות'))
                                })

                elif ftype == 'fin':
                    col_client = next((c for c in df.columns if 'לקוח' in c or 'חוסך' in c), None)
                    if not col_client: continue
                    for _, row in df.iterrows():
                        client = clean_text(row.get(col_client))
                        if not is_valid_name(client): continue
                        prod = clean_text(row.get('מוצר') or row.get('שם מוצר'))
                        bal = clean_currency(row.get('צבירה') or row.get('יתרה'))
                        if bal == 0 and not prod: continue
                        current_report["raw_fin"].append({
                            "client": client, "product": prod, "company": clean_text(row.get('חברה') or row.get('גוף מוסדי')),
                            "balance": bal, "status": clean_text(row.get('מצב קיים') or row.get('סטטוס')),
                            "fee": clean_text(row.get('דמי ניהול')), "rec": clean_text(row.get('המלצות'))
                        })

        except Exception as e:
            print(f"ERROR processing file {file.filename}: {e}")

    results = []
    for fam_name, data in grouped_reports.items():
        html_content = generate_single_html_report(data)
        results.append({ "family": fam_name, "html": html_content })

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)