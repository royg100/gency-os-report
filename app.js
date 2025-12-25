/**
 * AgencyOS Core System
 * מבוסס רכיבים (Component Based)
 */

// --- 1. מאגר הנתונים (State) ---
const State = {
    user: null,
    db: JSON.parse(localStorage.getItem('AgencyDB')) || {}, // לקוחות
    currentView: 'home'
};

// --- 2. ספריית הרכיבים (Templates) ---
const Components = {
    
    // כרטיס כניסה
    LoginCard: () => `
        <div class="login-overlay" id="login-screen">
            <div class="card-login">
                <img src="logo.png" style="height:60px; margin-bottom:20px;" onerror="this.style.display='none'">
                <h2 style="margin-bottom:10px;">AgencyOS</h2>
                <p style="color:#666; margin-bottom:30px;">מערכת ניהול מתקדמת</p>
                <input type="text" id="username" placeholder="שם משתמש (admin)">
                <input type="password" id="password" placeholder="סיסמה (123456)">
                <button class="btn-primary" onclick="App.login()">התחברות</button>
            </div>
        </div>
    `,

    // כרטיס פריט בתפריט צד
    SidebarItem: (icon, text, action, active = false) => `
        <div class="nav-item ${active ? 'active' : ''}" onclick="${action}">
            <i class="fas ${icon}"></i> <span>${text}</span>
        </div>
    `,

    // כרטיס מדד (KPI)
    KPICard: (title, value, icon, colorClass) => `
        <div class="card-kpi">
            <div class="kpi-icon" style="color: ${colorClass}; background: ${colorClass}20;">
                <i class="fas ${icon}"></i>
            </div>
            <div class="kpi-data">
                <p>${title}</p>
                <h3>${value}</h3>
            </div>
        </div>
    `,

    // כרטיס תפריט ראשי
    MenuCard: (title, desc, icon, action) => `
        <div class="card-menu" onclick="${action}">
            <i class="fas ${icon}"></i>
            <h3>${title}</h3>
            <p style="color:#666; font-size:0.9rem;">${desc}</p>
        </div>
    `,

    // כרטיס טבלה
    TableCard: (title, headers, rowsHTML) => `
        <div class="card-table">
            <div class="table-header">
                <span>${title}</span>
                <button class="btn-primary" style="width:auto; padding:5px 15px;" onclick="alert('ייצוא בקרוב')">Excel</button>
            </div>
            <table>
                <thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
                <tbody>${rowsHTML}</tbody>
            </table>
        </div>
    `
};

// --- 3. לוגיקת המערכת (Controller) ---
const App = {
    
    init: () => {
        // רינדור מסך כניסה בהתחלה
        document.getElementById('mount-login').innerHTML = Components.LoginCard();
        
        // האזנה ל-Enter
        document.addEventListener('keypress', (e) => {
            if(e.key === 'Enter' && !State.user) App.login();
        });
    },

    login: () => {
        const u = document.getElementById('username').value;
        const p = document.getElementById('password').value;
        
        if (u === 'admin' && p === '123456') {
            State.user = u;
            document.getElementById('login-screen').remove(); // מחיקת מסך כניסה
            document.getElementById('app-layout').style.display = 'flex';
            App.renderLayout();
            App.router('home');
            
            Swal.fire({
                icon: 'success', title: `שלום ${u}`, 
                toast: true, position: 'top-end', showConfirmButton: false, timer: 2000 
            });
        } else {
            Swal.fire('שגיאה', 'פרטי התחברות שגויים', 'error');
        }
    },

    // בניית השלד הקבוע (סרגל צד ועליון)
    renderLayout: () => {
        const sidebar = document.getElementById('mount-sidebar');
        sidebar.innerHTML = `
            <div style="text-align:center; margin-bottom:40px;">
                <img src="logo.png" style="height:40px;" onerror="this.style.display='none'">
                <h3 style="margin:10px 0 0 0;">AgencyOS</h3>
            </div>
            ${Components.SidebarItem('fa-home', 'מרכז שליטה', "App.router('home')", true)}
            ${Components.SidebarItem('fa-users', 'לקוחות', "App.router('clients')")}
            ${Components.SidebarItem('fa-cloud-upload-alt', 'טעינה', "App.triggerUpload()")}
            <div style="margin-top:auto;">
                ${Components.SidebarItem('fa-sign-out-alt', 'יציאה', "location.reload()")}
            </div>
        `;

        document.getElementById('mount-topbar').innerHTML = `
            <h2 id="page-title" style="margin:0;">סקירה</h2>
            <div style="display:flex; gap:10px; align-items:center;">
                <span>מחובר: <strong>${State.user}</strong></span>
                <div style="width:35px; height:35px; background:#4f46e5; color:white; border-radius:50%; display:flex; align-items:center; justify-content:center;">A</div>
            </div>
        `;
    },

    // מנוע הניווט (Router) - מזריק כרטיסים לפי המסך
    router: (view) => {
        const content = document.getElementById('mount-content');
        content.innerHTML = ''; // ניקוי מסך
        
        // עדכון כותרת וסרגל צד
        document.getElementById('page-title').innerText = view === 'home' ? 'מרכז שליטה' : 'ניהול לקוחות';
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        
        if (view === 'home') {
            // הזרקת כרטיסי KPI
            const kpiRow = document.createElement('div');
            kpiRow.style.display = 'grid';
            kpiRow.style.gridTemplateColumns = 'repeat(auto-fit, minmax(200px, 1fr))';
            kpiRow.style.gap = '20px';
            
            // חישוב נתונים (דמו)
            const clientCount = Object.keys(State.db).length;
            
            kpiRow.innerHTML = `
                ${Components.KPICard('לקוחות פעילים', clientCount, 'fa-users', '#4f46e5')}
                ${Components.KPICard('פרמיה חודשית', '₪0', 'fa-file-invoice-dollar', '#ec4899')}
                ${Components.KPICard('צבירה כוללת', '₪0', 'fa-chart-line', '#10b981')}
            `;
            content.appendChild(kpiRow);

            // הזרקת תפריט מהיר
            const menuGrid = document.createElement('div');
            menuGrid.className = 'grid-menu';
            menuGrid.innerHTML = `
                ${Components.MenuCard('איתור לקוח', 'חיפוש וניהול תיק', 'fa-search', "App.router('clients')")}
                ${Components.MenuCard('טעינת מסלקה', 'ייבוא קבצי אקסל', 'fa-database', "App.triggerUpload()")}
                ${Components.MenuCard('דוחות', 'הפקת דוחות PDF', 'fa-print', "alert('בקרוב')")}
            `;
            content.appendChild(menuGrid);

        } else if (view === 'clients') {
            // הזרקת טבלת לקוחות
            const clients = Object.keys(State.db);
            let rows = '';
            
            if(clients.length === 0) {
                rows = `<tr><td colspan="4" style="text-align:center;">אין נתונים. טען קובץ אקסל.</td></tr>`;
            } else {
                rows = clients.map(c => `
                    <tr onclick="alert('פתיחת תיק: ${c}')">
                        <td>${c}</td>
                        <td><span style="background:#dcfce7; color:#166534; padding:2px 8px; border-radius:10px; font-size:0.8em;">פעיל</span></td>
                        <td>₪0</td>
                        <td><button class="btn-primary" style="padding:5px 10px; width:auto;">צפה</button></td>
                    </tr>
                `).join('');
            }

            content.innerHTML = Components.TableCard('רשימת לקוחות', ['שם', 'סטטוס', 'שווי תיק', 'פעולות'], rows);
        }
    },

    // --- טעינת קבצים (סימולציה) ---
    triggerUpload: () => {
        // יצירת אלמנט קלט נסתר
        const input = document.createElement('input');
        input.type = 'file';
        input.webkitdirectory = true; // בחירת תיקייה
        input.onchange = (e) => {
            Swal.fire({ title: 'טוען...', didOpen: () => Swal.showLoading() });
            setTimeout(() => {
                // דמו טעינה
                State.db['ישראל ישראלי'] = { data: 'test' };
                State.db['משה כהן'] = { data: 'test' };
                localStorage.setItem('AgencyDB', JSON.stringify(State.db));
                Swal.fire('הצלחה', 'נתונים נטענו', 'success');
                App.router('clients');
            }, 1000);
        };
        input.click();
    }
};

// הפעלת המערכת
App.init();