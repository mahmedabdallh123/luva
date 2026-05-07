import streamlit as st
import pandas as pd
import json
import os
import io
import requests
import shutil
import re
from datetime import datetime, timedelta
from base64 import b64decode

# محاولة استيراد PyGithub (لرفع التعديلات)
try:
    from github import Github
    GITHUB_AVAILABLE = True
except Exception:
    GITHUB_AVAILABLE = False

# ===============================
# ⚙ إعدادات التطبيق - نظام مكبس القطن
# ===============================
APP_CONFIG = {
    # إعدادات التطبيق العامة
    "APP_TITLE": "نظام إدارة مكبس القطن",
    "APP_ICON": "🏭",
    
    # إعدادات GitHub
    "REPO_NAME": "mahmedabdallh123/luva",  # غيّر هذا لريبو الجديد
    "BRANCH": "main",
    "FILE_PATH": "luva.xlsx",  # ملف البيانات الجديد
    "LOCAL_FILE": "luva.xlsx",
    
    # إعدادات الأمان
    "MAX_ACTIVE_USERS": 5,
    "SESSION_DURATION_MINUTES":11,
    
    # إعدادات الورديات
    "SHIFTS": {
        "الاولي": {"start": 8, "end": 16},
        "الثانيه": {"start": 16, "end": 24},
        "الثالثه": {"start": 0, "end": 8}
    },
    
    # إعدادات الواجهة (تم إزالة تبويبي الإدارة والدعم)
    "CUSTOM_TABS": ["📥 إدخال البيانات", "📊 عرض الإحصائيات"]
}

# ===============================
# 🗂 إعدادات الملفات
# ===============================
USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]

# إنشاء رابط GitHub تلقائياً من الإعدادات
GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME'].split('/')[0]}/{APP_CONFIG['REPO_NAME'].split('/')[1]}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"

# -------------------------------
# 🧩 دوال مساعدة للملفات والحالة
# -------------------------------
def load_users():
    """تحميل بيانات المستخدمين من ملف JSON"""
    if not os.path.exists(USERS_FILE):
        # إنشاء المستخدمين الافتراضيين مع الصلاحيات المطلوبة
        default_users = {
            "admin": {
                "password": "1111", 
                "role": "admin", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["all"]
            },
            "user1": {
                "password": "12345", 
                "role": "data_entry", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["data_entry"]
            },
            "user2": {
                "password": "99999", 
                "role": "viewer", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["view_stats"]
            }
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_users, f, indent=4, ensure_ascii=False)
        return default_users
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
            # التأكد من وجود جميع الحقول المطلوبة
            for username, user_data in users.items():
                if "role" not in user_data:
                    if username == "admin":
                        user_data["role"] = "admin"
                        user_data["permissions"] = ["all"]
                    elif username == "user1":
                        user_data["role"] = "data_entry"
                        user_data["permissions"] = ["data_entry"]
                    elif username == "user2":
                        user_data["role"] = "viewer"
                        user_data["permissions"] = ["view_stats"]
                    else:
                        user_data["role"] = "viewer"
                        user_data["permissions"] = ["view_stats"]
                
                if "permissions" not in user_data:
                    if user_data["role"] == "admin":
                        user_data["permissions"] = ["all"]
                    elif user_data["role"] == "data_entry":
                        user_data["permissions"] = ["data_entry"]
                    elif user_data["role"] == "viewer":
                        user_data["permissions"] = ["view_stats"]
                    else:
                        user_data["permissions"] = ["view_stats"]
                        
                if "created_at" not in user_data:
                    user_data["created_at"] = datetime.now().isoformat()
                    
            return users
    except Exception as e:
        st.error(f"❌ خطأ في ملف users.json: {e}")
        return {
            "admin": {
                "password": "1111", 
                "role": "admin", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["all"]
            },
            "user1": {
                "password": "12345", 
                "role": "data_entry", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["data_entry"]
            },
            "user2": {
                "password": "99999", 
                "role": "viewer", 
                "created_at": datetime.now().isoformat(),
                "permissions": ["view_stats"]
            }
        }

def save_users(users):
    """حفظ بيانات المستخدمين إلى ملف JSON"""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"❌ خطأ في حفظ ملف users.json: {e}")
        return False

def load_state():
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

def cleanup_sessions(state):
    now = datetime.now()
    changed = False
    for user, info in list(state.items()):
        if info.get("active") and "login_time" in info:
            try:
                login_time = datetime.fromisoformat(info["login_time"])
                if now - login_time > SESSION_DURATION:
                    info["active"] = False
                    info.pop("login_time", None)
                    changed = True
            except:
                info["active"] = False
                changed = True
    if changed:
        save_state(state)
    return state

def remaining_time(state, username):
    if not username or username not in state:
        return None
    info = state.get(username)
    if not info or not info.get("active"):
        return None
    try:
        lt = datetime.fromisoformat(info["login_time"])
        remaining = SESSION_DURATION - (datetime.now() - lt)
        if remaining.total_seconds() <= 0:
            return None
        return remaining
    except:
        return None

# -------------------------------
# 🔐 تسجيل الخروج
# -------------------------------
def logout_action():
    state = load_state()
    username = st.session_state.get("username")
    if username and username in state:
        state[username]["active"] = False
        state[username].pop("login_time", None)
        save_state(state)
    keys = list(st.session_state.keys())
    for k in keys:
        st.session_state.pop(k, None)
    st.rerun()

# -------------------------------
# 🧠 واجهة تسجيل الدخول
# -------------------------------
def login_ui():
    users = load_users()
    state = cleanup_sessions(load_state())
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_role = None
        st.session_state.user_permissions = []

    st.title(f"{APP_CONFIG['APP_ICON']} تسجيل الدخول - {APP_CONFIG['APP_TITLE']}")

    username_input = st.selectbox("👤 اختر المستخدم", list(users.keys()))
    password = st.text_input("🔑 كلمة المرور", type="password")

    active_users = [u for u, v in state.items() if v.get("active")]
    active_count = len(active_users)
    st.caption(f"🔒 المستخدمون النشطون الآن: {active_count} / {MAX_ACTIVE_USERS}")

    if not st.session_state.logged_in:
        if st.button("تسجيل الدخول"):
            if username_input in users and users[username_input]["password"] == password:
                if username_input == "admin":
                    pass
                elif username_input in active_users:
                    st.warning("⚠ هذا المستخدم مسجل دخول بالفعل.")
                    return False
                elif active_count >= MAX_ACTIVE_USERS:
                    st.error("🚫 الحد الأقصى للمستخدمين المتصلين حالياً.")
                    return False
                state[username_input] = {"active": True, "login_time": datetime.now().isoformat()}
                save_state(state)
                st.session_state.logged_in = True
                st.session_state.username = username_input
                st.session_state.user_role = users[username_input].get("role", "viewer")
                st.session_state.user_permissions = users[username_input].get("permissions", ["view_stats"])
                st.success(f"✅ تم تسجيل الدخول: {username_input} ({st.session_state.user_role})")
                st.rerun()
            else:
                st.error("❌ كلمة المرور غير صحيحة.")
        return False
    else:
        username = st.session_state.username
        user_role = st.session_state.user_role
        st.success(f"✅ مسجل الدخول كـ: {username} ({user_role})")
        rem = remaining_time(state, username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.info(f"⏳ الوقت المتبقي: {mins:02d}:{secs:02d}")
        else:
            st.warning("⏰ انتهت الجلسة، سيتم تسجيل الخروج.")
            logout_action()
        if st.button("🚪 تسجيل الخروج"):
            logout_action()
        return True

# -------------------------------
# 🔄 طرق جلب الملف من GitHub
# -------------------------------
def fetch_from_github_requests():
    """تحميل بإستخدام رابط RAW (requests)"""
    try:
        response = requests.get(GITHUB_EXCEL_URL, stream=True, timeout=15)
        response.raise_for_status()
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            shutil.copyfileobj(response.raw, f)
        try:
            st.cache_data.clear()
        except:
            pass
        return True
    except Exception as e:
        st.error(f"⚠ فشل التحديث من GitHub: {e}")
        return False

def fetch_from_github_api():
    """تحميل عبر GitHub API"""
    if not GITHUB_AVAILABLE:
        return fetch_from_github_requests()
    
    try:
        token = st.secrets.get("github", {}).get("token", None)
        if not token:
            return fetch_from_github_requests()
        
        g = Github(token)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        file_content = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
        content = b64decode(file_content.content)
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            f.write(content)
        try:
            st.cache_data.clear()
        except:
            pass
        return True
    except Exception as e:
        st.error(f"⚠ فشل تحميل الملف من GitHub: {e}")
        return False

# -------------------------------
# 📂 تحميل البيانات
# -------------------------------
@st.cache_data(show_spinner=False)
def load_cotton_data():
    """تحميل بيانات مكبس القطن"""
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        create_new_cotton_file()
        return pd.DataFrame()
    
    try:
        df = pd.read_excel(APP_CONFIG["LOCAL_FILE"])
        return df
    except Exception as e:
        st.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def create_new_cotton_file():
    """إنشاء ملف بيانات جديد"""
    try:
        columns = [
            'التاريخ', 'الوقت', 'الوردية', 'المشرف', 'نوع البالة', 
            'وزن البالة', 'ملاحظات'
        ]
        df = pd.DataFrame(columns=columns)
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        return True
    except Exception as e:
        st.error(f"❌ خطأ في إنشاء الملف: {e}")
        return False

# -------------------------------
# 🔁 حفظ البيانات
# -------------------------------
def save_cotton_data(df, commit_message="تحديث بيانات مكبس القطن"):
    """حفظ البيانات إلى ملف Excel والرفع إلى GitHub"""
    try:
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        
        try:
            st.cache_data.clear()
        except:
            pass

        token = st.secrets.get("github", {}).get("token", None)
        if token and GITHUB_AVAILABLE:
            try:
                g = Github(token)
                repo = g.get_repo(APP_CONFIG["REPO_NAME"])
                with open(APP_CONFIG["LOCAL_FILE"], "rb") as f:
                    content = f.read()

                try:
                    contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
                    result = repo.update_file(
                        path=APP_CONFIG["FILE_PATH"], 
                        message=commit_message, 
                        content=content, 
                        sha=contents.sha, 
                        branch=APP_CONFIG["BRANCH"]
                    )
                    st.success("✅ تم الحفظ والرفع إلى GitHub بنجاح")
                except:
                    result = repo.create_file(
                        path=APP_CONFIG["FILE_PATH"], 
                        message=commit_message, 
                        content=content, 
                        branch=APP_CONFIG["BRANCH"]
                    )
                    st.success("✅ تم إنشاء ملف جديد على GitHub")
            except Exception as e:
                st.warning(f"⚠ تم الحفظ محلياً فقط: {e}")
        
        return True
    except Exception as e:
        st.error(f"❌ خطأ في حفظ البيانات: {e}")
        return False

# -------------------------------
# 🧮 دوال مساعدة للنظام
# -------------------------------
def get_current_shift():
    """تحديد الوردية الحالية تلقائياً"""
    now = datetime.now()
    current_hour = now.hour
    
    for shift_name, shift_times in APP_CONFIG["SHIFTS"].items():
        if shift_times["start"] <= current_hour < shift_times["end"]:
            return shift_name
    return "الثالثه"  # الوردية الثالثة من منتصف الليل إلى 8 صباحاً

def get_supervisors():
    """قائمة المشرفين"""
    return ["انسT.A", "عبدالحميدT.B", "محمود فتحيT.C", "احمد عبالعزيزT.D"]

def get_bale_types():
    """أنواع البالات"""
    return ["قماش", "تراب", "هبوه دست", "اسطبات تدویر", "برم", "برم انفاق", "بلاستيك",
        "هبوه تنظيف", "انفاق", "شرق الغزل", "تمشيط غير مغلف", 
        "تمشيط مغلف", "مكس", "كرد", "قطن خام","ملح"
    ]

def add_new_record(df, supervisor, bale_type, weight, notes=""):
    """إضافة سجل جديد"""
    now = datetime.now()
    new_record = {
        'التاريخ': now.date(),
        'الوقت': now.time(),
        'الوردية': get_current_shift(),
        'المشرف': supervisor,
        'نوع البالة': bale_type,
        'وزن البالة': weight,
        'ملاحظات': notes
    }
    
    new_df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
    return new_record, new_df

def generate_statistics(df, start_date, end_date):
    """توليد إحصائيات الفترة المحددة"""
    if df.empty:
        return pd.DataFrame()
    
    df['التاريخ'] = pd.to_datetime(df['التاريخ']).dt.date
    
    mask = (df['التاريخ'] >= start_date) & (df['التاريخ'] <= end_date)
    filtered_df = df[mask]
    
    if filtered_df.empty:
        return pd.DataFrame()
    
    stats = filtered_df.groupby('نوع البالة').agg({
        'وزن البالة': ['count', 'sum', 'mean'],
        'المشرف': 'first'
    }).round(2)
    
    stats.columns = ['عدد البالات', 'إجمالي الوزن', 'متوسط الوزن', 'المشرف']
    stats = stats.reset_index()
    
    return stats

def get_user_permissions(user_role, user_permissions):
    """الحصول على صلاحيات المستخدم (بدون إدارة مستخدمين أو دعم فني)"""
    if "all" in user_permissions:
        return {
            "can_input": True,
            "can_view_stats": True
        }
    elif "data_entry" in user_permissions:
        return {
            "can_input": True,
            "can_view_stats": False
        }
    elif "view_stats" in user_permissions:
        return {
            "can_input": False,
            "can_view_stats": True
        }
    else:
        return {
            "can_input": False,
            "can_view_stats": True
        }

# -------------------------------
# 🖥 الواجهة الرئيسية
# -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

# شريط تسجيل الدخول
with st.sidebar:
    st.header("👤 الجلسة")
    if not st.session_state.get("logged_in"):
        if not login_ui():
            st.stop()
    else:
        state = cleanup_sessions(load_state())
        username = st.session_state.username
        user_role = st.session_state.user_role
        rem = remaining_time(state, username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.success(f"👋 {username} | الدور: {user_role} | ⏳ {mins:02d}:{secs:02d}")
        else:
            logout_action()

    st.markdown("---")
    st.write("🔧 أدوات:")
    if st.button("🔄 تحديث الملف من GitHub"):
        if fetch_from_github_requests():
            st.rerun()
    
    if st.button("🗑 مسح الكاش"):
        try:
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"❌ خطأ في مسح الكاش: {e}")
    
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج"):
        logout_action()

# تحميل البيانات
cotton_df = load_cotton_data()

# واجهة التبويبات الرئيسية
st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

# التحقق من الصلاحيات
username = st.session_state.get("username")
user_role = st.session_state.get("user_role", "viewer")
user_permissions = st.session_state.get("user_permissions", ["view_stats"])
permissions = get_user_permissions(user_role, user_permissions)

# بناء التبويبات بناءً على الصلاحيات (بدون إدارة مستخدمين أو دعم فني)
tab_titles = []
if permissions["can_input"]:
    tab_titles.append("📥 إدخال البيانات")
if permissions["can_view_stats"]:
    tab_titles.append("📊 عرض الإحصائيات")

if not tab_titles:
    tab_titles = ["📊 عرض الإحصائيات"]  # افتراضي

tabs = st.tabs(tab_titles)

# -------------------------------
# Tab 1: إدخال البيانات
# -------------------------------
if permissions["can_input"] and len(tabs) > 0:
    with tabs[0]:
        st.header("📥 إدخال بيانات البالات")
        
        current_shift = get_current_shift()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.info(f"الوردية الحالية: {current_shift} | الوقت: {current_time}")
        
        with st.form("data_entry_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                supervisor = st.selectbox("👨‍💼 اختر المشرف:", get_supervisors(), key="supervisor_select")
                bale_type = st.selectbox("📦 اختر نوع البالة:", get_bale_types(), key="bale_type_select")
            
            with col2:
                weight = st.number_input("⚖ وزن البالة (كجم):", min_value=0.0, step=0.1, key="weight_input")
                notes = st.text_input("📝 ملاحظات (اختياري):", key="notes_input")
            
            submitted = st.form_submit_button("💾 حفظ البيانات")
            
            if submitted:
                if weight <= 0:
                    st.error("❌ يرجى إدخال وزن صحيح للبالة")
                else:
                    new_record, updated_df = add_new_record(cotton_df, supervisor, bale_type, weight, notes)
                    
                    if save_cotton_data(updated_df, f"إضافة بالة {bale_type} بواسطة {supervisor}"):
                        st.success(f"✅ تم حفظ بيانات البالة بنجاح!")
                        st.json({
                            "نوع البالة": new_record['نوع البالة'],
                            "الوزن": f"{new_record['وزن البالة']} كجم",
                            "المشرف": new_record['المشرف'],
                            "الوردية": new_record['الوردية'],
                            "الوقت": str(new_record['الوقت'])
                        })
                        st.rerun()

# -------------------------------
# Tab 2: عرض الإحصائيات
# -------------------------------
if permissions["can_view_stats"]:
    # تحديد الفهرس الصحيح للتبويب (إذا كان هناك تبويب إدخال، فالإحصائيات في الفهرس 1)
    stats_tab_index = 1 if permissions["can_input"] else 0
    if stats_tab_index < len(tabs):
        with tabs[stats_tab_index]:
            st.header("📊 عرض الإحصائيات")
            
            if cotton_df.empty:
                st.warning("⚠ لا توجد بيانات لعرضها")
            else:
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("من تاريخ:", value=datetime.now().date() - timedelta(days=7))
                with col2:
                    end_date = st.date_input("إلى تاريخ:", value=datetime.now().date())
                
                if st.button("🔄 تحديث الإحصائيات"):
                    st.session_state["show_stats"] = True
                
                if st.session_state.get("show_stats", False):
                    stats_df = generate_statistics(cotton_df, start_date, end_date)
                    
                    if not stats_df.empty:
                        st.subheader(f"📈 إحصائيات الفترة من {start_date} إلى {end_date}")
                        st.dataframe(stats_df, use_container_width=True)
                        
                        total_bales = stats_df['عدد البالات'].sum()
                        total_weight = stats_df['إجمالي الوزن'].sum()
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("🔄 إجمالي عدد البالات", f"{total_bales:,}")
                        with col2:
                            st.metric("⚖ إجمالي الوزن", f"{total_weight:,.1f} كجم")
                        with col3:
                            avg_weight = total_weight / total_bales if total_bales > 0 else 0
                            st.metric("📊 متوسط الوزن للبالة", f"{avg_weight:.1f} كجم")
                        
                        st.subheader("📋 البيانات التفصيلية")
                        filtered_data = cotton_df[
                            (pd.to_datetime(cotton_df['التاريخ']).dt.date >= start_date) & 
                            (pd.to_datetime(cotton_df['التاريخ']).dt.date <= end_date)
                        ]
                        st.dataframe(filtered_data, use_container_width=True)
                        
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            stats_df.to_excel(writer, sheet_name='الإحصائيات', index=False)
                            filtered_data.to_excel(writer, sheet_name='البيانات_التفصيلية', index=False)
                        
                        st.download_button(
                            label="📥 تحميل التقرير كملف Excel",
                            data=buffer.getvalue(),
                            file_name=f"تقرير_مكبس_القطن_{start_date}إلى{end_date}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.warning("⚠ لا توجد بيانات في الفترة المحددة")
