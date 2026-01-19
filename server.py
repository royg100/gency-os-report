import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import re
from datetime import datetime
import json
import xml.etree.ElementTree as ET
from io import BytesIO

# הגדרת האפליקציה
app = Flask(__name__, static_folder='.')
CORS(app)

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
        .check-card { display: flex; flex-direction: column; align-items: center; justify-content: start; padding: 12px 5px; border-radius: 8px; border: 1px solid #e2e8f0; text-align: center; position: relative; min-height: 85px; page-break-inside: avoid !important; word-spacing: 0.1em; white-space: normal; }
        .check-card.found { background: #f0fdf4; border-color: #86efac; color: #166534; }
        .check-card.warning { background: #fffbeb; border-color: #fcd34d; color: #92400e; }
        .check-card.missing { background: #fef2f2; border-color: #fca5a5; color: #991b1b; opacity: 0.85; }
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

        <div style="page-break-inside: avoid;">
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
                        <th style="width:30%">לקוח</th>
                        <th style="width:35%">מספר מוצרים</th>
                        <th style="width:35%">סה"כ סימולציה לפרישה</th>
                    </tr>
                </thead>
                <tbody>{{ simulation_summary_html | safe }}</tbody>
            </table>
        </div>

        <div class="footer">דוח זה הופק ע"י מערכת AgencyOS | כל הזכויות שמורות לאשר לוי סוכנות לביטוח )2011( בע"מ</div>
    </div>

    <script>
        // נתונים לגרפים
        const riskData = {{ risk_chart_data | tojson }};
        const productData = {{ product_chart_data | tojson }};

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
                
                # דמי ניהול
                hotzaot = None
                for elem in heshbon.iter():
                    if strip_namespace(elem.tag) == 'HotzaotBafoalLehodeshDivoach':
                        hotzaot = elem
                        break
                
                accumulation_fee_text = find_element_text(hotzaot, 'SHEUR-DMEI-NIHUL-TZVIRA', '') if hotzaot else ''
                deposit_fee_text = find_element_text(hotzaot, 'SHEUR-DMEI-NIHUL-HAFKADA', '') if hotzaot else ''
                
                fee_parts = []
                if accumulation_fee_text:
                    try:
                        acc_fee = float(accumulation_fee_text.replace(',', '').strip() or '0')
                        acc_fee_pct = acc_fee * 100 if acc_fee < 1 and acc_fee > 0 else acc_fee
                        if acc_fee_pct > 0:
                            fee_parts.append(f"{acc_fee_pct:.2f}% צבירה")
                    except (ValueError, AttributeError):
                        pass
                
                if deposit_fee_text:
                    try:
                        dep_fee = float(deposit_fee_text.replace(',', '').strip() or '0')
                        dep_fee_pct = dep_fee * 100 if dep_fee < 1 and dep_fee > 0 else dep_fee
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
    fin_checklist_data = {k: {'products': set(), 'total': 0, 'count': 0} for k in ['pension', 'gemel', 'hishtalmut', 'managers', 'mutual', 'savings']}
    
    # נתונים לגרפים
    risk_distribution = {}
    product_distribution = {}
    
    # סיכום סימולציה לפי לקוח
    simulation_by_client = {}

    members_html = ""
    if data['members']:
        for name, m in data['members'].items():
            members_html += f'<div class="mem-item"><strong>{name}</strong><div>{m.get("age","")} {m.get("job","")}</div></div>'
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
            if any(x in ptype for x in ['חיים', 'ריסק', 'מוות', 'משכנתא']): checklist_data['risk'].add(ptype)
            if any(x in ptype for x in ['בריאות', 'ניתוח', 'השתל', 'תרופות', 'אמבולטורי', 'ליווי', 'שב"ן']): checklist_data['health'].add(ptype)
            if any(x in ptype for x in ['מחלות', 'סרטן', 'גילוי']): checklist_data['ci'].add(ptype)
            if any(x in ptype for x in ['כושר', 'נכות', 'א.כ.ע']): checklist_data['disability'].add(ptype)
            if any(x in ptype for x in ['תאונות', 'שברים', 'נכויות']): checklist_data['accidents'].add(ptype)
            if 'סיעוד' in ptype: checklist_data['nursing'].add(ptype)
            ins_rows += f"""<tr><td class="font-bold">{r['client']}</td><td>{r['company']}</td><td><strong>{ptype}</strong></td><td>{r['policy']}</td><td>{r['start_date']}</td><td class="money">{f"₪{cov:,.2f}" if cov else '-'}</td><td class="money">{f"₪{prem:,.2f}" if prem else '-'}</td><td class="text-start">{r['notes']}</td></tr>"""
        if total_prem > 0: ins_rows += f'<tr class="sum-row"><td colspan="6" class="text-start">סה"כ פרמיה חודשית:</td><td class="money">₪{total_prem:,.2f}</td><td></td></tr>'
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
            else:
                risk_distribution['לא ידוע'] = risk_distribution.get('לא ידוע', 0) + bal
            
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
            
            # איסוף סימולציה לפי לקוח
            if client not in simulation_by_client:
                simulation_by_client[client] = {'total_simulation': 0, 'product_count': 0}
            simulation_by_client[client]['product_count'] += 1
            if sim and sim > 0:
                simulation_by_client[client]['total_simulation'] += sim
            
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
                fin_checklist_data['gemel']['products'].add(prod_clean)
                fin_checklist_data['gemel']['total'] += bal
                fin_checklist_data['gemel']['count'] += 1
            elif ('מנהלים' in prod_clean and 'ביטוח' in prod_clean) or 'ב.מנהלים' in prod_clean:
                fin_checklist_data['managers']['products'].add(prod_clean)
                fin_checklist_data['managers']['total'] += bal
                fin_checklist_data['managers']['count'] += 1
            elif 'נאמנות' in prod_clean:
                fin_checklist_data['mutual']['products'].add(prod_clean)
                fin_checklist_data['mutual']['total'] += bal
                fin_checklist_data['mutual']['count'] += 1
            elif 'חסכון' in prod_clean or 'פיקדון' in prod_clean:
                fin_checklist_data['savings']['products'].add(prod_clean)
                fin_checklist_data['savings']['total'] += bal
                fin_checklist_data['savings']['count'] += 1
            
            # בניית השורה בטבלה
            status_class = 'style="opacity:0.6;"' if 'מסולק' in status else ''
            sim_display = f"₪{sim:,.2f}" if sim > 0 else "-"
            fin_rows += f"""<tr {status_class}>
                <td class="font-bold">{r['client']}</td>
                <td><strong>{r['product']}</strong></td>
                <td>{r['company']}</td>
                <td style="font-size:9pt;">{risk}</td>
                <td class="money" style="color:#166534;font-weight:bold;">{f"₪{bal:,.2f}" if bal else '-'}</td>
                <td class="money" style="color:#2563eb;">{sim_display}</td>
                <td>{r['fee']}</td>
                <td>{r['status']}</td>
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
        {'key': 'hishtalmut', 'label': 'קרן השתלמות', 'icon': 'fa-graduation-cap'},
        {'key': 'managers', 'label': 'ביטוח מנהלים', 'icon': 'fa-briefcase'},
        {'key': 'mutual', 'label': 'קרנות נאמנות', 'icon': 'fa-chart-pie'},
        {'key': 'savings', 'label': 'חסכונות', 'icon': 'fa-coins'},
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
            product_names = list(found_items)[:2]
            txt = ", ".join(product_names) + (f" +{len(found_items)-2}" if len(found_items)>2 else "")
            if total_amount > 0: txt += f"<br><strong style='font-size:9pt;'>₪{total_amount:,.2f}</strong>"
        else: txt = "חסר / לבדיקה"
        fin_checklist_html += f'<div class="check-card {css}"><i class="fas {item["icon"]} check-icon"></i><div class="check-label">{item["label"]}</div><div class="check-status">{txt}</div></div>'
    
    # סיכום לפי מבוטח
    client_summary_html = ""
    if client_summary:
        client_summary_html = '<div class="sec-title" style="margin-top:8px;"><span>סיכום לפי מבוטח</span> <i class="fas fa-user-chart"></i></div><div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:8px;">'
        for client, summary in sorted(client_summary.items()):
            active_pct = (summary['active'] / summary['count'] * 100) if summary['count'] > 0 else 0
            status_color = '#10b981' if active_pct >= 50 else '#f59e0b' if active_pct > 0 else '#ef4444'
            client_summary_html += f'''<div style="background:#f8fafc; padding:12px; border-radius:8px; border:1px solid #e2e8f0;">
                <strong class="clickable-client" style="color:#ec4899; display:block; margin-bottom:5px; cursor:pointer;" onclick="window.parent.postMessage({{type:'showClientProducts', clientName:'{client}'}}, '*');" title="לחץ לראות מוצרים">{client}</strong>
                <div style="font-size:9pt; color:#64748b;">סה"כ: <strong style="color:#166534;">₪{summary['total']:,}</strong></div>
                <div style="font-size:9pt; color:#64748b;">{summary['count']} מוצרים | <span style="color:{status_color};">{summary['active']} פעילים</span></div>
            </div>'''
        client_summary_html += '</div>'
    
    # בניית טבלת סיכום סימולציה לפי לקוח
    simulation_summary_html = ""
    if simulation_by_client:
        total_simulation_all = 0
        for client, sim_data in sorted(simulation_by_client.items()):
            total_sim = sim_data['total_simulation']
            product_count = sim_data['product_count']
            total_simulation_all += total_sim
            sim_display = f"₪{total_sim:,.2f}" if total_sim > 0 else "-"
            simulation_summary_html += f'<tr><td class="font-bold text-start">{client}</td><td>{product_count}</td><td class="money" style="color:#2563eb;font-weight:bold;">{sim_display}</td></tr>'
        
        # שורת סיכום
        if total_simulation_all > 0:
            simulation_summary_html += f'<tr class="sum-row"><td colspan="2" class="text-start">סה"כ סימולציה לפרישה:</td><td class="money" style="color:#2563eb;font-weight:bold;">₪{total_simulation_all:,.2f}</td></tr>'
    else:
        simulation_summary_html = '<tr><td colspan="3" style="padding:20px; color:#999;">אין נתוני סימולציה</td></tr>'
    
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
                          .replace('{{ product_chart_data | tojson }}', json.dumps(product_distribution))

def generate_recommendations_data(data):
    # פונקציה זו מחזירה נתונים גולמיים ל-Frontend אם צריך (לשימוש בדשבורד)
    # בקוד הזה אנחנו מתמקדים ב-HTML, אז נשאיר אותה בסיסית או נרחיב לפי הצורך
    return []

# --- נתיבי Flask ---
@app.route('/')
def index(): return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path): return send_from_directory('.', path)

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files: return jsonify({"error": "No files"}), 400
    files = request.files.getlist('files[]')
    grouped_reports = {} 
    
    print(f"\n{'='*60}")
    print(f"התחלת עיבוד {len(files)} קבצים")
    print(f"{'='*60}\n")

    for file_idx, file in enumerate(files, 1):
        try:
            filename = file.filename
            print(f"\n[{file_idx}/{len(files)}] מעבד קובץ: {filename}")
            
            clean_name = re.sub(r'\.(xlsx|xls|csv|dat)$', '', filename, flags=re.IGNORECASE)
            family_key = re.sub(r'(ניתוח תיק|ניהול סיכונים|פרטים אישיים|ביטוחים|פנסיה|\d+|עותק).*', '', clean_name).strip("- ").strip()
            if not family_key: family_key = "כללי"
            
            print(f"  → שם משפחה מזוהה: '{family_key}'")

            if family_key not in grouped_reports:
                grouped_reports[family_key] = { "family_name": family_key, "members": {}, "raw_ins": [], "raw_fin": [] }
                print(f"  → נוצר דוח חדש עבור '{family_key}'")
            
            current_report = grouped_reports[family_key]
            raw_ins_before = len(current_report["raw_ins"])
            raw_fin_before = len(current_report["raw_fin"])
            print(f"  → לפני עיבוד: {raw_ins_before} ביטוחים, {raw_fin_before} פיננסיים")
            
            dfs = []
            
            # בדיקה אם קובץ DAT מכיל XML (פורמט מסלקה)
            if filename.lower().endswith('.dat'):
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
                        
                        continue  # דילוג על עיבוד DataFrame
                    else:
                        print(f"✗ קובץ {filename} לא זוהה כ-XML")
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
            elif filename.endswith('.csv'):
                # טיפול בקבצי CSV - נסה מספר encodings ומופרדים
                try: 
                    dfs.append(pd.read_csv(file, encoding='utf-8', sep=None, engine='python'))
                except: 
                    try:
                        file.stream.seek(0)
                        dfs.append(pd.read_csv(file, encoding='cp1255', sep=None, engine='python'))
                    except:
                        file.stream.seek(0)
                        dfs.append(pd.read_csv(file, encoding='latin-1', sep=None, engine='python'))
            else:
                # קבצי אקסל
                print(f"  → קורא קובץ אקסל: {filename}")
                xls_dict = pd.read_excel(file, sheet_name=None)
                dfs = list(xls_dict.values())
                print(f"  → נמצאו {len(dfs)} גיליונות בקובץ אקסל")

            for df_raw in dfs:
                # טיפול מיוחד בקבצי CSV עם שני חלקים (ביטוח ופיננסי)
                if filename.lower().endswith('.csv'):
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
                print(f"  → מחפש כותרת בקובץ {filename}...")
                header_idx, ftype = find_header_and_type(df_raw)
                if header_idx == -1:
                    print(f"  ✗ לא נמצאה כותרת בקובץ {filename}")
                    continue
                
                print(f"  ✓ נמצאה כותרת בשורה {header_idx}, סוג: {ftype}")

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
                    print(f"  → מעבד חלק ביטוח (ins) מקובץ {filename}")
                    col_client = next((c for c in df.columns if 'מבוטח' in c), 'מבוטחים')
                    print(f"  → עמודת לקוח: '{col_client}'")
                    print(f"  → מספר שורות: {len(df)}")
                    last_valid_client = None
                    ins_count = 0
                    for _, row in df.iterrows():
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
                    print(f"  ✓ נוספו {ins_count} רשומות ביטוח מקובץ {filename}")

                elif ftype == 'fin':
                    # קבצי אקסל עם ftype='fin' - לא נטפל בהם, רק DAT נטפל בפיננסי
                    print(f"⚠ קובץ אקסל מזוהה כ-'fin' (פיננסי) - דילוג. רק קבצי DAT יעובדו לפיננסי.")
                    continue
            
            # סיכום עיבוד הקובץ
            raw_ins_after = len(current_report["raw_ins"])
            raw_fin_after = len(current_report["raw_fin"])
            ins_added = raw_ins_after - raw_ins_before
            fin_added = raw_fin_after - raw_fin_before
            print(f"  ✓ סיום עיבוד קובץ {filename}:")
            print(f"    - נוספו {ins_added} רשומות ביטוח (סה\"כ: {raw_ins_after})")
            print(f"    - נוספו {fin_added} רשומות פיננסיות (סה\"כ: {raw_fin_after})")

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

    results = []
    for fam_name, data in grouped_reports.items():
        print(f"\n=== יצירת דוח עבור {fam_name} ===")
        print(f"✓ יש {len(data.get('raw_fin', []))} רשומות ב-raw_fin לפני יצירת הדוח")
        if data.get('raw_fin'):
            print(f"✓ דוגמה לרשומה ראשונה: {data['raw_fin'][0]}")
        html_content = generate_single_html_report(data)
        results.append({ 
            "family": fam_name, 
            "html": html_content,
            "recommendations": [],
            "raw_data": {
                "raw_ins": data.get("raw_ins", []),
                "raw_fin": data.get("raw_fin", []),
                "members": data.get("members", {})
            }
        })

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)