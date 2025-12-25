import pandas as pd
import json
import os
import glob
import numpy as np

# --- הגדרות זיהוי (המילון החכם) ---
# מילים שבעזרתן נזהה איזה סוג מידע יש בטבלה
KEYWORDS = {
    'insurance': ['סכום פיצוי', 'פרמיה', 'עלות', 'סכום ביטוח', 'מ.פוליסה', 'תאריך תום'],
    'finance': ['צבירה', 'דמי ניהול', 'מסלול', 'יתרה', 'מספר קופה', 'תשואה'],
    'details': ['ת.ז', 'תעודת זהות', 'גיל', 'עיסוק', 'מצב משפחתי', 'עישון']
}

# מיפוי עמודות אחיד (מכל השמות האפשריים לשם אחד תקני)
COLUMN_MAPPING = {
    # שמות לקוח
    'שם': 'name', 'שם פרטי': 'name', 'שם משפחה': 'name', 'מבוטח': 'name', 'מבוטחים': 'name', 'לקוח': 'name', 'שם הלקוח': 'name',
    # עלויות
    'עלות': 'premium', 'פרמיה': 'premium', 'תשלום חודשי': 'premium', 'פרמיה חודשית': 'premium',
    # סכומים
    'סכום פיצוי': 'coverage', 'סכום ביטוח': 'coverage', 'צבירה': 'balance', 'יתרה': 'balance', 'סך נכסים': 'balance',
    # מזהים
    'ת.ז': 'id', 'תעודת זהות': 'id', 'מ.פוליסה': 'policy_id', 'מספר פוליסה': 'policy_id', 'מ.פוליסה36': 'policy_id',
    # כללי
    'חברה': 'company', 'גוף מוסדי': 'company', 'מבטחת': 'company',
    'סוג': 'product_type', 'ביטוח': 'product_type', 'מוצר': 'product_type', 'שם כיסוי': 'product_type',
    'דמי ניהול': 'fees', 'דמי ניהול מצבירה': 'fees',
    'הערות': 'notes', 'הערה': 'notes'
}

def detect_header_row(df):
    """
    פונקציה חכמה שסורקת את 50 השורות הראשונות ומחפשת את שורת הכותרת הכי סבירה
    """
    best_score = 0
    best_row_idx = -1
    detected_type = 'unknown'

    for i in range(min(len(df), 50)):
        row_values = df.iloc[i].astype(str).tolist()
        row_str = " ".join(row_values)
        
        # חישוב ציון לכל סוג
        scores = {k: 0 for k in KEYWORDS}
        for category, keywords in KEYWORDS.items():
            for kw in keywords:
                if kw in row_str:
                    scores[category] += 1
        
        # בדיקה אם זו השורה המנצחת
        current_max_type = max(scores, key=scores.get)
        current_score = scores[current_max_type]

        if current_score > best_score and current_score >= 2: # לפחות 2 התאמות
            best_score = current_score
            best_row_idx = i
            detected_type = current_max_type

    return best_row_idx, detected_type

def clean_value(val):
    """נרמול מספרים וטקסטים"""
    if pd.isna(val) or val == '':
        return None
    val_str = str(val).strip()
    # ניסיון להמיר למספר
    try:
        clean_num = val_str.replace('₪', '').replace(',', '').replace('%', '')
        if clean_num.replace('.', '', 1).isdigit():
            return float(clean_num)
    except:
        pass
    return val_str

def process_files():
    all_data = {} # המבנה: { "שם משפחה": { members: [...] } }
    
    # חיפוש כל קבצי האקסל/CSV בתיקייה
    files = glob.glob("*.xlsx") + glob.glob("*.xls") + glob.glob("*.csv")
    
    print(f"נמצאו {len(files)} קבצים לעיבוד...")

    for file_path in files:
        try:
            print(f"מעבד את: {file_path}")
            # שם המשפחה נגזר משם הקובץ (לוגיקה פשוטה)
            family_name = os.path.splitext(file_path)[0].split('-')[0].strip()
            
            if family_name not in all_data:
                all_data[family_name] = {"members": {}, "raw_files": []}
            all_data[family_name]["raw_files"].append(file_path)

            # קריאת הקובץ (טיפול שונה ל-CSV ואקסל)
            if file_path.endswith('.csv'):
                xls = {'Sheet1': pd.read_csv(file_path)}
            else:
                xls = pd.read_excel(file_path, sheet_name=None, header=None)

            # מעבר על כל גליון
            for sheet_name, df in xls.items():
                header_idx, table_type = detect_header_row(df)
                
                if header_idx == -1:
                    continue # לא נמצאה טבלה רלוונטית

                # יצירת דאטה-פריים נקי החל משורת הכותרת
                df.columns = df.iloc[header_idx]
                df = df.iloc[header_idx+1:].reset_index(drop=True)
                
                # נרמול שמות העמודות
                df.columns = [str(c).strip() for c in df.columns]
                normalized_cols = {c: COLUMN_MAPPING.get(c, c) for c in df.columns}
                df = df.rename(columns=normalized_cols)

                # איסוף הנתונים
                for _, row in df.iterrows():
                    # דילוג על שורות ריקות
                    if pd.isna(row.get('name')) and pd.isna(row.get('product_type')):
                        continue

                    # זיהוי שם הלקוח (או שימוש בברירת מחדל מהקובץ)
                    client_name = row.get('name')
                    if not client_name or str(client_name).lower() in ['nan', 'סה"כ', 'none']:
                        # אם אין שם בשורה, מנסים להסיק משם הקובץ או מדלגים
                        continue 
                    
                    client_name = str(client_name).strip()

                    # אתחול המבנה ללקוח
                    if client_name not in all_data[family_name]["members"]:
                        all_data[family_name]["members"][client_name] = {"ins": [], "fin": [], "details": {}}

                    # שמירת הנתונים לפי סוג
                    member_data = all_data[family_name]["members"][client_name]
                    
                    item = {k: clean_value(v) for k, v in row.items() if k in COLUMN_MAPPING.values()}
                    
                    if table_type == 'insurance':
                        member_data["ins"].append(item)
                    elif table_type == 'finance':
                        member_data["fin"].append(item)
                    elif table_type == 'details':
                        member_data["details"].update(item)

        except Exception as e:
            print(f"שגיאה בעיבוד הקובץ {file_path}: {e}")

    # שמירת התוצאה לקובץ JSON שה-HTML יקרא
    with open('db_data.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    
    print("--- הסתיים העיבוד! נוצר קובץ db_data.json ---")

if __name__ == "__main__":
    process_files()