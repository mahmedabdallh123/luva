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

# مكتبات OCR
import cv2
import numpy as np
import easyocr
from PIL import Image

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
    "SESSION_DURATION_MINUTES": 11,
    
    # إعدادات الورديات
    "SHIFTS": {
        "الاولي": {"start": 8, "end": 16},
        "الثانيه": {"start": 16, "end": 24},
        "الثالثه": {"start": 0, "end": 8}
    },
    
    # إعدادات الواجهة
    "SHOW_TECH_SUPPORT_TO_ALL": False,
    "CUSTOM_TABS": ["📥 إدخال البيانات", "📊 عرض الإحصائيات", "👥 إدارة المستخدمين", "📞 الدعم الفني"]
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
# 🧠 OCR: تهيئة القارئ وتحليل الصورة
# -------------------------------
@st.cache_resource
def init_ocr_reader():
    """تهيئة قارئ EasyOCR (مرة واحدة فقط)"""
    return easyocr.Reader(['ar', 'en'], gpu=False)  # GPU=False للتوافق

def extract_data_from_image(image_file):
    """
    استخراج البيانات من الصورة: نوع البالة، الوزن، التاريخ، الوقت
    إرجاع قاموس بالقيم المستخرجة (قد تكون None)
    """
    # قراءة الصورة
    img = Image.open(image_file)
    img_np = np.array(img)
    
    # تحويل إلى RGB إذا كانت RGBA
    if img_np.shape[-1] == 4:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
    
    # معالجة مسبقة لتحسين OCR
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    # تطبيق عتبة ثنائية
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    # عكس للأبيض على أسود
    thresh = cv2.bitwise_not(thresh)
    
    # استخدام EasyOCR
    reader = init_ocr_reader()
    results = reader.readtext(thresh, detail=0, paragraph=False)
    full_text = ' '.join(results)
    
    # تنظيف النص
    full_text = full_text.replace('|', 'I').replace('؟', '?')
    
    # استخراج البيانات باستخدام regex
    data = {
        'bale_type': None,
        'weight': None,
        'date': None,
        'time': None,
        'raw_text': full_text
    }
    
    # 1. استخراج نوع البالة (قائمة الأنواع المعروفة)
    bale_types_list = get_bale_types()
    for btype in bale_types_list:
        if btype in full_text:
            data['bale_type'] = btype
            break
    # إذا لم يعثر، حاول البحث عن كلمات قريبة
    if not data['bale_type']:
        keywords = {
            'قطن خام': 'قطن خام',
            'قماش': 'قماش',
            'تراب': 'تراب',
            'هبوه دست': 'هبوه دست',
            'اسطبات تدویر': 'اسطبات تدویر',
            'برم': 'برم',
            'بلاستيك': 'بلاستيك'
        }
        for key, val in keywords.items():
            if key in full_text:
                data['bale_type'] = val
                break
    
    # 2. استخراج الوزن (رقم متبوع بـ كجم أو kg)
    weight_pattern = r'(\d+(?:\.\d+)?)\s*(?:كجم|kg|كغ)'
    weight_match = re.search(weight_pattern, full_text, re.IGNORECASE)
    if weight_match:
        data['weight'] = float(weight_match.group(1))
    else:
        # البحث عن أي رقم معزول قريب من كلمة وزن
        weight_match2 = re.search(r'وزن[:\s]*(\d+(?:\.\d+)?)', full_text)
        if weight_match2:
            data['weight'] = float(weight_match2.group(1))
    
    # 3. استخراج التاريخ (تنسيقات متعددة)
    date_patterns = [
        r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',  # 2024-12-31
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})',  # 31/12/2024
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2})',   # 31/12/24
        r'(\d{8})'                           # 20241231
    ]
    for pattern in date_patterns:
        match = re.search(pattern, full_text)
        if match:
            date_str = match.group(1)
            try:
                if len(date_str) == 8 and date_str.isdigit():
                    data['date'] = datetime.strptime(date_str, '%Y%m%d').date()
                elif '/' in date_str or '-' in date_str:
                    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y'):
                        try:
                            data['date'] = datetime.strptime(date_str, fmt).date()
                            break
                        except:
                            continue
                break
            except:
                pass
    
    # 4. استخراج الوقت (HH:MM)
    time_pattern = r'(\d{1,2}:\d{2})'
    time_match = re.search(time_pattern, full_text)
    if time_match:
        time_str = time_match.group(1)
        try:
            data['time'] = datetime.strptime(time_str, '%H:%M').time()
        except:
            pass
    
    return data

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
        # إنشاء ملف جديد إذا لم يكن موجوداً
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
    return "الثالثه"

def get_supervisors():
    """قائمة المشرفين"""
    return ["T.A", "T.B", "T.C", "T.D"]

def get_bale_types():
    """أنواع البالات"""
    return ["قماش", "تراب", "هبوه دست", "اسطبات تدویر", "برم", "برم انفاق", "بلاستيك",
        "هبوه تنظيف", "انفاق", "شرق الغزل", "تمشيط غير مغلف", 
        "تمشيط مغلف", "مكس", "كرد", "قطن خام","ملح"
    ]

def add_new_record(df, supervisor, bale_type, weight, notes="", manual_date=None, manual_shift=None):
    """إضافة سجل جديد"""
    now = datetime.now()
    
    if manual_date:
        record_date = manual_date
    else:
        record_date = now.date()
    
    if manual_shift:
        record_shift = manual_shift
    else:
        record_shift = get_current_shift()
    
    new_record = {
        'التاريخ': record_date,
        'الوقت': now.time(),
        'الوردية': record_shift,
        'المشرف': supervisor,
        'نوع البالة': bale_type,
        'وزن البالة': weight,
        'ملاحظات': notes
    }
    
    new_df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
    return new_record, new_df

def generate_advanced_statistics(df, start_date, end_date, selected_shifts, selected_bale_types, calculate_percentage=False):
    """توليد إحصائيات متقدمة مع خيارات تصفية متعددة"""
    if df.empty:
        return pd.DataFrame()
    
    df['التاريخ'] = pd.to_datetime(df['التاريخ']).dt.date
    
    mask = (df['التاريخ'] >= start_date) & (df['التاريخ'] <= end_date)
    filtered_df = df[mask]
    
    if selected_shifts:
        filtered_df = filtered_df[filtered_df['الوردية'].isin(selected_shifts)]
    
    if selected_bale_types:
        filtered_df = filtered_df[filtered_df['نوع البالة'].isin(selected_bale_types)]
    
    if filtered_df.empty:
        return pd.DataFrame()
    
    stats = filtered_df.groupby('نوع البالة').agg({
        'وزن البالة': ['count', 'sum', 'mean'],
        'المشرف': 'first'
    }).round(2)
    
    stats.columns = ['عدد البالات', 'إجمالي الوزن', 'متوسط الوزن', 'المشرف']
    stats = stats.reset_index()
    
    if calculate_percentage:
        cotton_weight = 0
        cotton_mask = (df['التاريخ'] >= start_date) & (df['التاريخ'] <= end_date)
        if selected_shifts:
            cotton_mask = cotton_mask & (df['الوردية'].isin(selected_shifts))
        cotton_data = df[cotton_mask & (df['نوع البالة'] == 'قطن خام')]
        
        if not cotton_data.empty:
            cotton_weight = cotton_data['وزن البالة'].sum()
        
        if cotton_weight > 0:
            stats['النسبة المئوية %'] = ((stats['إجمالي الوزن'] / cotton_weight) * 100).round(2)
        else:
            stats['النسبة المئوية %'] = 0
    
    return stats

def get_user_permissions(user_role, user_permissions):
    """الحصول على صلاحيات المستخدم بناءً على الدور والصلاحيات"""
    if "all" in user_permissions:
        return {
            "can_input": True,
            "can_view_stats": True,
            "can_manage_users": True,
            "can_see_tech_support": True
        }
    elif "data_entry" in user_permissions:
        return {
            "can_input": True,
            "can_view_stats": False,
            "can_manage_users": False,
            "can_see_tech_support": False
        }
    elif "view_stats" in user_permissions:
        return {
            "can_input": False,
            "can_view_stats": True,
            "can_manage_users": False,
            "can_see_tech_support": False
        }
    else:
        return {
            "can_input": False,
            "can_view_stats": True,
            "can_manage_users": False,
            "can_see_tech_support": False
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

# تحديد التبويبات بناءً على الصلاحيات
if permissions["can_manage_users"]:  # admin
    tabs = st.tabs(APP_CONFIG["CUSTOM_TABS"])
elif permissions["can_input"]:  # data_entry user
    tabs = st.tabs(["📥 إدخال البيانات"])
elif permissions["can_view_stats"]:  # viewer user
    tabs = st.tabs(["📊 عرض الإحصائيات"])
else:
    tabs = st.tabs(["📊 عرض الإحصائيات"])

# -------------------------------
# Tab 1: إدخال البيانات (للمستخدمين الذين لديهم صلاحية data_entry أو admin)
# -------------------------------
if permissions["can_input"] and len(tabs) > 0:
    with tabs[0]:
        st.header("📥 إدخال بيانات البالات")
        
        # قسم رفع الصورة واستخراج البيانات
        with st.expander("📸 رفع صورة واستخراج البيانات تلقائياً", expanded=False):
            st.write("ارفع صورة تحتوي على بيانات البالة (نوع، وزن، تاريخ، وقت)")
            uploaded_image = st.file_uploader("اختر صورة", type=['png', 'jpg', 'jpeg'], key="ocr_uploader")
            
            if uploaded_image is not None:
                with st.spinner("جاري تحليل الصورة ..."):
                    extracted = extract_data_from_image(uploaded_image)
                
                st.subheader("📝 البيانات المستخرجة")
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**النص الخام:**")
                    st.text(extracted['raw_text'][:500])
                
                with col2:
                    st.write("**البيانات المقترحة:**")
                    st.json({
                        "نوع البالة": extracted['bale_type'],
                        "الوزن (كجم)": extracted['weight'],
                        "التاريخ": str(extracted['date']) if extracted['date'] else None,
                        "الوقت": str(extracted['time']) if extracted['time'] else None
                    })
                
                if extracted['bale_type'] and extracted['weight']:
                    st.success("✅ تم استخراج نوع البالة والوزن بنجاح")
                    if st.button("✍️ استخدام هذه البيانات لملء النموذج"):
                        st.session_state['ocr_bale_type'] = extracted['bale_type']
                        st.session_state['ocr_weight'] = extracted['weight']
                        st.session_state['ocr_date'] = extracted['date']
                        st.session_state['ocr_time'] = extracted['time']
                        st.rerun()
                else:
                    st.warning("⚠ لم يتم التعرف على نوع البالة أو الوزن بوضوح. حاول رفع صورة أوضح.")
        
        # معلومات الوردية الحالية
        current_shift = get_current_shift()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.info(f"الوردية الحالية: {current_shift} | الوقت: {current_time}")
        
        # إعدادات التاريخ والوردية (يدوي أو تلقائي)
        st.subheader("⚙ إعدادات التاريخ والوردية")
        
        col_set1, col_set2 = st.columns(2)
        with col_set1:
            use_auto_date = st.checkbox("استخدام التاريخ التلقائي", value=True)
        with col_set2:
            use_auto_shift = st.checkbox("استخدام الوردية التلقائية", value=True)
        
        # نموذج إدخال البيانات
        with st.form("data_entry_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            
            with col1:
                supervisor = st.selectbox("👨‍💼 اختر المشرف:", get_supervisors(), key="supervisor_select")
                # تعيين القيمة الافتراضية لنوع البالة من OCR إذا وجدت
                bale_type_default = st.session_state.get('ocr_bale_type', get_bale_types()[0])
                bale_type_index = get_bale_types().index(bale_type_default) if bale_type_default in get_bale_types() else 0
                bale_type = st.selectbox("📦 اختر نوع البالة:", get_bale_types(), index=bale_type_index, key="bale_type_select")
                
                if not use_auto_date:
                    # إذا كان هناك تاريخ مستخرج، استخدمه كقيمة افتراضية
                    default_date = st.session_state.get('ocr_date', datetime.now().date())
                    manual_date = st.date_input("📅 اختر التاريخ:", value=default_date)
                else:
                    manual_date = None
            
            with col2:
                # الوزن الافتراضي من OCR
                weight_default = st.session_state.get('ocr_weight', 0.0)
                weight = st.number_input("⚖ وزن البالة (كجم):", min_value=0.0, step=0.1, value=weight_default, key="weight_input")
                notes = st.text_input("📝 ملاحظات (اختياري):", key="notes_input")
                
                if not use_auto_shift:
                    manual_shift = st.selectbox("🕐 اختر الوردية:", list(APP_CONFIG["SHIFTS"].keys()))
                else:
                    manual_shift = None
            
            submitted = st.form_submit_button("💾 حفظ البيانات")
            
            if submitted:
                if weight <= 0:
                    st.error("❌ يرجى إدخال وزن صحيح للبالة")
                else:
                    new_record, updated_df = add_new_record(
                        cotton_df, supervisor, bale_type, weight, notes, 
                        manual_date, manual_shift
                    )
                    
                    commit_msg = f"إضافة بالة {bale_type} وزن {weight} كجم بواسطة {supervisor}"
                    if save_cotton_data(updated_df, commit_msg):
                        st.success(f"✅ تم حفظ بيانات البالة بنجاح!")
                        st.json({
                            "نوع البالة": new_record['نوع البالة'],
                            "الوزن": f"{new_record['وزن البالة']} كجم",
                            "المشرف": new_record['المشرف'],
                            "الوردية": new_record['الوردية'],
                            "التاريخ": str(new_record['التاريخ']),
                            "الوقت": str(new_record['الوقت'])
                        })
                        # مسح بيانات OCR المؤقتة بعد الحفظ
                        for key in ['ocr_bale_type', 'ocr_weight', 'ocr_date', 'ocr_time']:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.rerun()

# -------------------------------
# Tab 2: عرض الإحصائيات (للمستخدمين الذين لديهم صلاحية view_stats أو admin)
# -------------------------------
if permissions["can_view_stats"] and len(tabs) > (0 if permissions["can_input"] else 0):
    stats_tab_index = 1 if permissions["can_input"] and permissions["can_manage_users"] else (
        0 if not permissions["can_input"] else 1
    )
    
    if stats_tab_index < len(tabs):
        with tabs[stats_tab_index]:
            st.header("📊 عرض الإحصائيات المتقدمة")
            
            if cotton_df.empty:
                st.warning("⚠ لا توجد بيانات لعرضها")
            else:
                st.subheader("🔍 تصفية البيانات")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    start_date = st.date_input("من تاريخ:", value=datetime.now().date() - timedelta(days=7))
                    end_date = st.date_input("إلى تاريخ:", value=datetime.now().date())
                    
                    st.write("### 🕐 اختيار الورديات:")
                    all_shifts = st.checkbox("جميع الورديات", value=True, key="all_shifts")
                    if all_shifts:
                        selected_shifts = list(APP_CONFIG["SHIFTS"].keys())
                    else:
                        selected_shifts = st.multiselect(
                            "اختر الورديات:",
                            list(APP_CONFIG["SHIFTS"].keys()),
                            default=list(APP_CONFIG["SHIFTS"].keys())
                        )
                
                with col2:
                    st.write("### 📦 اختيار أنواع البالات:")
                    all_bales = st.checkbox("جميع أنواع البالات", value=True, key="all_bales")
                    if all_bales:
                        selected_bale_types = get_bale_types()
                    else:
                        selected_bale_types = st.multiselect(
                            "اختر أنواع البالات:",
                            get_bale_types(),
                            default=get_bale_types()
                        )
                    
                    st.write("### ⚙ خيارات إضافية:")
                    calculate_percentage = st.checkbox(
                        "حساب النسبة المئوية مقابل قطن خام", 
                        value=True
                    )
                
                if st.button("🔄 توليد الإحصائيات", type="primary"):
                    stats_df = generate_advanced_statistics(
                        cotton_df, start_date, end_date, 
                        selected_shifts, selected_bale_types, 
                        calculate_percentage
                    )
                    
                    if not stats_df.empty:
                        st.subheader(f"📈 الإحصائيات للفترة من {start_date} إلى {end_date}")
                        st.info(f"""
                        *معلومات التصفية:*
                        - الورديات: {', '.join(selected_shifts) if selected_shifts else 'جميع الورديات'}
                        - أنواع البالات: {len(selected_bale_types)} نوع
                        - حساب النسبة المئوية: {'نعم' if calculate_percentage else 'لا'}
                        """)
                        
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
                        
                        if calculate_percentage and 'النسبة المئوية %' in stats_df.columns:
                            st.subheader("📊 النسب المئوية مقابل قطن خام")
                            chart_data = stats_df[stats_df['نوع البالة'] != 'قطن خام']
                            if not chart_data.empty:
                                st.bar_chart(chart_data.set_index('نوع البالة')['النسبة المئوية %'])
                            
                            percentage_df = stats_df[['نوع البالة', 'إجمالي الوزن', 'النسبة المئوية %']].copy()
                            st.dataframe(percentage_df, use_container_width=True)
                        
                        st.subheader("📋 البيانات التفصيلية المصفاة")
                        filtered_data = cotton_df.copy()
                        filtered_data['التاريخ'] = pd.to_datetime(filtered_data['التاريخ']).dt.date
                        mask = (filtered_data['التاريخ'] >= start_date) & (filtered_data['التاريخ'] <= end_date)
                        if selected_shifts:
                            mask = mask & (filtered_data['الوردية'].isin(selected_shifts))
                        if selected_bale_types:
                            mask = mask & (filtered_data['نوع البالة'].isin(selected_bale_types))
                        detailed_data = filtered_data[mask]
                        st.dataframe(detailed_data, use_container_width=True)
                        
                        st.subheader("📥 تصدير البيانات")
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            stats_df.to_excel(writer, sheet_name='الإحصائيات', index=False)
                            detailed_data.to_excel(writer, sheet_name='البيانات_التفصيلية', index=False)
                            if calculate_percentage and 'النسبة المئوية %' in stats_df.columns:
                                percentage_df.to_excel(writer, sheet_name='النسب_المئوية', index=False)
                        
                        st.download_button(
                            label="📥 تحميل التقرير كملف Excel",
                            data=buffer.getvalue(),
                            file_name=f"تقرير_مكبس_القطن_{start_date}إلى{end_date}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.warning("⚠ لا توجد بيانات تطابق معايير التصفية المحددة")

# -------------------------------
# Tab 3: إدارة المستخدمين (للمسؤول فقط)
# -------------------------------
if permissions["can_manage_users"] and len(tabs) > 2:
    with tabs[2]:
        st.header("👥 إدارة المستخدمين")
        users = load_users()
        
        st.subheader("📋 المستخدمين الحاليين")
        if users:
            user_data = []
            for username, info in users.items():
                user_data.append({
                    "اسم المستخدم": username,
                    "الدور": info.get("role", "user"),
                    "الصلاحيات": ", ".join(info.get("permissions", [])),
                    "تاريخ الإنشاء": info.get("created_at", "غير معروف")
                })
            users_df = pd.DataFrame(user_data)
            st.dataframe(users_df, use_container_width=True)
        else:
            st.info("لا يوجد مستخدمين مسجلين بعد.")
        
        st.subheader("➕ إضافة مستخدم جديد")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_username = st.text_input("اسم المستخدم الجديد:")
        with col2:
            new_password = st.text_input("كلمة المرور:", type="password")
        with col3:
            user_role = st.selectbox("الدور:", ["admin", "data_entry", "viewer"])
        
        if st.button("إضافة مستخدم", key="add_user"):
            if not new_username.strip() or not new_password.strip():
                st.warning("⚠ الرجاء إدخال اسم المستخدم وكلمة المرور.")
            elif new_username in users:
                st.warning("⚠ هذا المستخدم موجود بالفعل.")
            else:
                if user_role == "admin":
                    permissions_list = ["all"]
                elif user_role == "data_entry":
                    permissions_list = ["data_entry"]
                else:
                    permissions_list = ["view_stats"]
                
                users[new_username] = {
                    "password": new_password,
                    "role": user_role,
                    "permissions": permissions_list,
                    "created_at": datetime.now().isoformat()
                }
                if save_users(users):
                    st.success(f"✅ تم إضافة المستخدم '{new_username}' بنجاح.")
                    st.rerun()
                else:
                    st.error("❌ حدث خطأ أثناء حفظ بيانات المستخدم.")
        
        st.subheader("🗑 حذف مستخدم")
        if len(users) > 1:
            user_to_delete = st.selectbox(
                "اختر مستخدم للحذف:",
                [u for u in users.keys() if u != "admin"],
                key="delete_user_select"
            )
            col1, col2 = st.columns(2)
            with col1:
                confirm_delete = st.checkbox("✅ تأكيد الحذف", key="confirm_user_delete")
            with col2:
                if st.button("حذف المستخدم", key="delete_user_btn"):
                    if not confirm_delete:
                        st.warning("⚠ يرجى تأكيد الحذف أولاً.")
                    elif user_to_delete == "admin":
                        st.error("❌ لا يمكن حذف المستخدم admin.")
                    elif user_to_delete == st.session_state.get("username"):
                        st.error("❌ لا يمكن حذف حسابك أثناء تسجيل الدخول.")
                    else:
                        if user_to_delete in users:
                            del users[user_to_delete]
                            if save_users(users):
                                st.success(f"✅ تم حذف المستخدم '{user_to_delete}' بنجاح.")
                                st.rerun()
                            else:
                                st.error("❌ حدث خطأ أثناء حفظ التغييرات.")

# -------------------------------
# Tab 4: الدعم الفني (للمسؤول فقط أو إذا كان مسموحاً للجميع)
# -------------------------------
tech_support_tab_index = 3 if permissions["can_manage_users"] else (
    1 if permissions["can_input"] and not permissions["can_manage_users"] else 1
)

if ((permissions["can_manage_users"] and len(tabs) > 3) or 
    (permissions["can_see_tech_support"] and len(tabs) > tech_support_tab_index)):
    
    with tabs[tech_support_tab_index]:
        st.header("📞 الدعم الفني")
        st.markdown("## 🛠 معلومات التطوير والدعم")
        st.markdown("تم تطوير هذا التطبيق بواسطة:")
        st.markdown("### م. محمد عبدالله")
        st.markdown("### رئيس قسم الكرد والمحطات")
        st.markdown("### مصنع بيل يارن للغزل")
        st.markdown("---")
        st.markdown("### معلومات الاتصال:")
        st.markdown("- 📧 البريد الإلكتروني: medotatch124@gmail.com")
        st.markdown("- 📞 هاتف :01274424062")
        st.markdown("- 🏢 الموقع: مصنع بيل يارن للغزل")
        st.markdown("---")
        st.markdown("### خدمات الدعم الفني:")
        st.markdown("- 🔧 صيانة وتحديث النظام")
        st.markdown("- 📊 تطوير تقارير إضافية")
        st.markdown("- 🐛 إصلاح الأخطاء والمشكلات")
        st.markdown("- 💡 استشارات فنية وتقنية")
        st.markdown("---")
        st.markdown("### إصدار النظام:")
        st.markdown("- الإصدار: 2.0 (مع OCR)")
        st.markdown("- آخر تحديث: 2025")
        st.markdown("- النظام: نظام إدارة مكبس القطن")
        
        st.info("ملاحظة: في حالة مواجهة أي مشاكل تقنية أو تحتاج إلى إضافة ميزات جديدة، يرجى التواصل مع قسم الدعم الفني. تأكد من تثبيت easyocr و opencv-python-headless للاستفادة من ميزة رفع الصور.")
