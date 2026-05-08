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
from difflib import get_close_matches

# GitHub
try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

# OCR باستخدام pytesseract مع opencv
try:
    import pytesseract
    from PIL import Image
    import cv2
    import numpy as np
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    st.warning("⚠ pytesseract أو opencv غير مثبت، ميزة مسح الصور معطلة")

# ===============================
# إعدادات التطبيق
# ===============================
APP_CONFIG = {
    "APP_TITLE": "نظام إدارة مكبس القطن",
    "APP_ICON": "🏭",
    "REPO_NAME": "mahmedabdallh123/luva",
    "BRANCH": "main",
    "FILE_PATH": "luva.xlsx",
    "LOCAL_FILE": "luva.xlsx",
    "MAX_ACTIVE_USERS": 5,
    "SESSION_DURATION_MINUTES": 11,
    "SHIFTS": {
        "الاولي": {"start": 8, "end": 16},
        "الثانيه": {"start": 16, "end": 24},
        "الثالثه": {"start": 0, "end": 8}
    }
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]
GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME'].split('/')[0]}/{APP_CONFIG['REPO_NAME'].split('/')[1]}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"

# -------------------------------
# دوال المستخدمين والجلسات (بدون تغيير)
# -------------------------------
def load_users():
    if not os.path.exists(USERS_FILE):
        default_users = {
            "admin": {"password": "1111", "role": "admin", "created_at": datetime.now().isoformat(), "permissions": ["all"]},
            "user1": {"password": "12345", "role": "data_entry", "created_at": datetime.now().isoformat(), "permissions": ["data_entry"]},
            "user2": {"password": "99999", "role": "viewer", "created_at": datetime.now().isoformat(), "permissions": ["view_stats"]}
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_users, f, indent=4, ensure_ascii=False)
        return default_users
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
            for uname, udata in users.items():
                if "role" not in udata:
                    if uname == "admin":
                        udata["role"] = "admin"
                        udata["permissions"] = ["all"]
                    elif uname == "user1":
                        udata["role"] = "data_entry"
                        udata["permissions"] = ["data_entry"]
                    else:
                        udata["role"] = "viewer"
                        udata["permissions"] = ["view_stats"]
                if "permissions" not in udata:
                    if udata["role"] == "admin":
                        udata["permissions"] = ["all"]
                    elif udata["role"] == "data_entry":
                        udata["permissions"] = ["data_entry"]
                    else:
                        udata["permissions"] = ["view_stats"]
                if "created_at" not in udata:
                    udata["created_at"] = datetime.now().isoformat()
            return users
    except Exception as e:
        st.error(f"خطأ في users.json: {e}")
        return {
            "admin": {"password": "1111", "role": "admin", "created_at": datetime.now().isoformat(), "permissions": ["all"]},
            "user1": {"password": "12345", "role": "data_entry", "created_at": datetime.now().isoformat(), "permissions": ["data_entry"]},
            "user2": {"password": "99999", "role": "viewer", "created_at": datetime.now().isoformat(), "permissions": ["view_stats"]}
        }

def save_users(users):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"خطأ في حفظ users.json: {e}")
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

def logout_action():
    state = load_state()
    username = st.session_state.get("username")
    if username and username in state:
        state[username]["active"] = False
        state[username].pop("login_time", None)
        save_state(state)
    for k in list(st.session_state.keys()):
        st.session_state.pop(k, None)
    st.rerun()

def login_ui():
    users = load_users()
    state = cleanup_sessions(load_state())
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    st.title(f"{APP_CONFIG['APP_ICON']} تسجيل الدخول - {APP_CONFIG['APP_TITLE']}")
    username_input = st.selectbox("اختر المستخدم", list(users.keys()))
    password = st.text_input("كلمة المرور", type="password")
    active_users = [u for u, v in state.items() if v.get("active")]
    active_count = len(active_users)
    st.caption(f"المستخدمون النشطون: {active_count}/{MAX_ACTIVE_USERS}")

    if not st.session_state.logged_in:
        if st.button("تسجيل الدخول"):
            if username_input in users and users[username_input]["password"] == password:
                if username_input == "admin":
                    pass
                elif username_input in active_users:
                    st.warning("هذا المستخدم مسجل دخول بالفعل")
                    return False
                elif active_count >= MAX_ACTIVE_USERS:
                    st.error("الحد الأقصى للمستخدمين المتصلين")
                    return False
                state[username_input] = {"active": True, "login_time": datetime.now().isoformat()}
                save_state(state)
                st.session_state.logged_in = True
                st.session_state.username = username_input
                st.session_state.user_role = users[username_input].get("role", "viewer")
                st.session_state.user_permissions = users[username_input].get("permissions", ["view_stats"])
                st.success(f"مرحباً {username_input}")
                st.rerun()
            else:
                st.error("كلمة المرور غير صحيحة")
        return False
    else:
        username = st.session_state.username
        role = st.session_state.user_role
        st.success(f"مسجل كـ {username} ({role})")
        rem = remaining_time(state, username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.info(f"الوقت المتبقي: {mins:02d}:{secs:02d}")
        else:
            st.warning("انتهت الجلسة")
            logout_action()
        if st.button("تسجيل الخروج"):
            logout_action()
        return True

# -------------------------------
# دوال GitHub والبيانات
# -------------------------------
def fetch_from_github_requests():
    try:
        response = requests.get(GITHUB_EXCEL_URL, stream=True, timeout=15)
        response.raise_for_status()
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            shutil.copyfileobj(response.raw, f)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"فشل التحديث: {e}")
        return False

@st.cache_data(show_spinner=False)
def load_cotton_data():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        create_new_cotton_file()
        return pd.DataFrame()
    try:
        df = pd.read_excel(APP_CONFIG["LOCAL_FILE"])
        required_cols = ['التاريخ', 'الوقت', 'الوردية', 'المشرف', 'نوع البالة', 'وزن البالة', 'ملاحظات']
        for col in required_cols:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception as e:
        st.error(f"خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def create_new_cotton_file():
    try:
        cols = ['التاريخ', 'الوقت', 'الوردية', 'المشرف', 'نوع البالة', 'وزن البالة', 'ملاحظات']
        df = pd.DataFrame(columns=cols)
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        return True
    except Exception as e:
        st.error(f"خطأ في إنشاء الملف: {e}")
        return False

def save_cotton_data(df, commit_message="تحديث"):
    try:
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        st.cache_data.clear()
        token = st.secrets.get("github", {}).get("token", None)
        if token and GITHUB_AVAILABLE:
            try:
                g = Github(token)
                repo = g.get_repo(APP_CONFIG["REPO_NAME"])
                with open(APP_CONFIG["LOCAL_FILE"], "rb") as f:
                    content = f.read()
                try:
                    contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
                    repo.update_file(APP_CONFIG["FILE_PATH"], commit_message, content, contents.sha, branch=APP_CONFIG["BRANCH"])
                    st.success("تم الحفظ والرفع إلى GitHub")
                except:
                    repo.create_file(APP_CONFIG["FILE_PATH"], commit_message, content, branch=APP_CONFIG["BRANCH"])
                    st.success("تم إنشاء الملف على GitHub")
            except Exception as e:
                st.warning(f"تم الحفظ محلياً فقط: {e}")
        return True
    except Exception as e:
        st.error(f"خطأ في الحفظ: {e}")
        return False

# -------------------------------
# دوال النظام الأساسية
# -------------------------------
def get_current_shift():
    now = datetime.now()
    h = now.hour
    for name, times in APP_CONFIG["SHIFTS"].items():
        if times["start"] <= h < times["end"]:
            return name
    return "الثالثه"

def get_supervisors():
    return ["انسT.A", "عبدالحميدT.B", "محمود فتحيT.C", "احمد عبالعزيزT.D"]

def get_bale_types():
    return ["قماش", "تراب", "هبوه دست", "اسطبات تدویر", "برم", "برم انفاق", "بلاستيك",
            "هبوه تنظيف", "انفاق", "شرق الغزل", "تمشيط غير مغلف", "تمشيط مغلف", "مكس", "كرد", "قطن خام", "ملح"]

def add_new_record(df, supervisor, bale_type, weight, notes=""):
    now = datetime.now()
    new = {
        'التاريخ': now.date(),
        'الوقت': now.time(),
        'الوردية': get_current_shift(),
        'المشرف': supervisor,
        'نوع البالة': bale_type,
        'وزن البالة': weight,
        'ملاحظات': notes
    }
    return new, pd.concat([df, pd.DataFrame([new])], ignore_index=True)

def generate_statistics(df, start_date, end_date):
    if df.empty:
        return pd.DataFrame()
    df['التاريخ'] = pd.to_datetime(df['التاريخ']).dt.date
    mask = (df['التاريخ'] >= start_date) & (df['التاريخ'] <= end_date)
    fdf = df[mask]
    if fdf.empty:
        return pd.DataFrame()
    stats = fdf.groupby('نوع البالة').agg({
        'وزن البالة': ['count', 'sum', 'mean'],
        'المشرف': 'first'
    }).round(2)
    stats.columns = ['عدد البالات', 'إجمالي الوزن', 'متوسط الوزن', 'المشرف']
    return stats.reset_index()

def get_user_permissions(role, perms):
    if "all" in perms:
        return {"can_input": True, "can_view_stats": True}
    elif "data_entry" in perms:
        return {"can_input": True, "can_view_stats": False}
    elif "view_stats" in perms:
        return {"can_input": False, "can_view_stats": True}
    else:
        return {"can_input": False, "can_view_stats": True}

# -------------------------------
# دوال OCR المحسنة مع الربط بقاموس الأنواع والتيمات
# -------------------------------
def preprocess_image_for_ocr(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    (h,w) = gray.shape
    scaled = cv2.resize(gray, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(scaled, (3,3), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    return thresh

def extract_raw_text_from_image(image_bytes):
    processed = preprocess_image_for_ocr(image_bytes)
    if processed is None:
        return ""
    config = '--psm 6 -c preserve_interword_spaces=1'
    text = pytesseract.image_to_string(processed, lang='ara+eng', config=config)
    return text

def match_bale_type(word, bale_types, cutoff=0.6):
    """محاولة مطابقة كلمة مع أقرب نوع بالة من القاموس"""
    # تطابق تام أولاً
    if word in bale_types:
        return word
    # استخدام close matches
    matches = get_close_matches(word, bale_types, n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    # البحث عن كلمات مفتاحية داخل النص
    for bt in bale_types:
        if bt in word or word in bt:
            return bt
    return None

def extract_time_from_text(text):
    """استخراج الوقت بصيغة HH:MM أو HH:MM:SS"""
    patterns = [
        r'\b([01]?[0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?\b',  # HH:MM or HH:MM:SS
        r'\b(\d{1,2}:\d{2})\b'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            time_str = match.group(0)
            # إذا كان الساعة مكونة من رقمين فقط نكمل بصفر
            if len(time_str.split(':')[0]) == 1:
                time_str = '0' + time_str
            return time_str
    return None

def parse_image_to_table(image_bytes):
    """
    استخراج النص ثم تحويله إلى جدول مع مطابقة الأنواع والاوزان والتيمات
    """
    raw_text = extract_raw_text_from_image(image_bytes)
    if not raw_text.strip():
        return [], raw_text
    
    # تقسيم إلى سطور
    lines = raw_text.split('\n')
    bale_types_list = get_bale_types()
    rows = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # استخراج الأرقام (الوزن)
        numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', line)
        weight = None
        for num in numbers:
            val = float(num)
            if 0.5 <= val <= 5000:
                weight = val
                break
        
        if weight is None:
            continue  # سطر بدون وزن نتخطاه
        
        # استخراج الوقت من السطر إن وجد
        extracted_time = extract_time_from_text(line)
        if extracted_time:
            # إزالة الوقت من السطر ليبقى النص المتبقي (الذي قد يحتوي على النوع)
            line_without_time = re.sub(r'\b' + re.escape(extracted_time) + r'\b', '', line)
        else:
            line_without_time = line
        
        # إزالة الوزن من السطر
        line_without_weight = re.sub(r'\b' + re.escape(str(weight)) + r'\b', '', line_without_time)
        line_without_weight = re.sub(r'\s*(?:kg|كجم|كغ)\s*', ' ', line_without_weight, flags=re.I)
        
        # تجزئة الكلمات المتبقية
        words = re.findall(r'[\u0600-\u06FFa-zA-Z0-9\(\)\-]+', line_without_weight)
        # محاولة مطابقة نوع البالة
        bale_type = None
        for word in words:
            matched = match_bale_type(word, bale_types_list)
            if matched:
                bale_type = matched
                break
        if not bale_type:
            # إذا لم نجد مطابقة، نأخذ أول كلمة ذات معنى
            meaningful_words = [w for w in words if len(w) > 1 and not w.isdigit()]
            if meaningful_words:
                bale_type = meaningful_words[0]
            else:
                bale_type = "غير محدد"
        
        # التاريخ: نستخدم تاريخ اليوم
        record_date = datetime.now().date()
        # الوقت: إذا استخرجنا من الصورة نستخدمه، وإلا نستخدم الوقت الحالي
        if extracted_time:
            try:
                record_time = datetime.strptime(extracted_time, '%H:%M').time()
            except:
                record_time = datetime.now().time()
        else:
            record_time = datetime.now().time()
        
        rows.append({
            'نوع البالة': bale_type,
            'وزن البالة': weight,
            'التاريخ': record_date,
            'الوقت': record_time
        })
    
    return rows, raw_text

# -------------------------------
# الواجهة الرئيسية
# -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

with st.sidebar:
    st.header("الجلسة")
    if not st.session_state.get("logged_in"):
        if not login_ui():
            st.stop()
    else:
        state = cleanup_sessions(load_state())
        user = st.session_state.username
        role = st.session_state.user_role
        rem = remaining_time(state, user)
        if rem:
            m, s = divmod(int(rem.total_seconds()), 60)
            st.success(f"👋 {user} | {role} | ⏳ {m:02d}:{s:02d}")
        else:
            logout_action()
    st.markdown("---")
    if st.button("🔄 تحديث من GitHub"):
        if fetch_from_github_requests():
            st.rerun()
    if st.button("🗑 مسح الكاش"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج"):
        logout_action()

cotton_df = load_cotton_data()
st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

perms = get_user_permissions(
    st.session_state.get("user_role", "viewer"),
    st.session_state.get("user_permissions", ["view_stats"])
)

tabs_list = []
if perms["can_input"]:
    tabs_list.append("📥 إدخال البيانات")
    if OCR_AVAILABLE:
        tabs_list.append("📸 استخراج جدول من صورة")
    else:
        st.sidebar.info("🔍 لتفعيل مسح الجدول: ثبّت pytesseract و opencv")
if perms["can_view_stats"]:
    tabs_list.append("📊 عرض الإحصائيات")

if not tabs_list:
    tabs_list = ["📊 عرض الإحصائيات"]

tabs = st.tabs(tabs_list)

# تبويب الإدخال اليدوي
if perms["can_input"] and "📥 إدخال البيانات" in tabs_list:
    idx = tabs_list.index("📥 إدخال البيانات")
    with tabs[idx]:
        st.header("إدخال بيانات البالات يدوياً")
        st.info(f"الوردية الحالية: {get_current_shift()} - {datetime.now()}")
        with st.form("manual"):
            col1, col2 = st.columns(2)
            with col1:
                sup = st.selectbox("المشرف", get_supervisors())
                btype = st.selectbox("نوع البالة", get_bale_types())
            with col2:
                w = st.number_input("الوزن (كجم)", min_value=0.0, step=0.1)
                note = st.text_input("ملاحظات")
            if st.form_submit_button("حفظ"):
                if w > 0:
                    _, new_df = add_new_record(cotton_df, sup, btype, w, note)
                    if save_cotton_data(new_df):
                        st.success("تم الحفظ")
                        st.rerun()
                else:
                    st.error("أدخل وزناً صحيحاً")

# تبويب استخراج الجدول من الصورة (مع الربط بقاموس الأنواع والتيمات)
if perms["can_input"] and OCR_AVAILABLE and "📸 استخراج جدول من صورة" in tabs_list:
    idx = tabs_list.index("📸 استخراج جدول من صورة")
    with tabs[idx]:
        st.header("رفع صورة واستخراج الجدول")
        st.markdown("""
        **كيف يعمل؟**
        - يستخرج النص من الصورة.
        - يبحث عن الأوزان (الأرقام).
        - يطابق الكلمات مع **قاموس أنواع البالات** الموجود في النظام (قماش، كرد، ... إلخ).
        - يبحث عن الوقت بصيغة HH:MM.
        - الناتج جدول قابل للتعديل، ثم يمكنك حفظه.
        """)
        uploaded = st.file_uploader("اختر صورة", type=["jpg","jpeg","png"])
        if uploaded:
            st.image(uploaded, use_column_width=True)
            with st.spinner("جاري تحليل الصورة..."):
                extracted_rows, raw_text = parse_image_to_table(uploaded.getvalue())
            if extracted_rows:
                st.success(f"تم استخراج {len(extracted_rows)} صف بنجاح")
                # عرض النص الخام للمستخدم (للتأكد)
                with st.expander("النص الخام المستخرج"):
                    st.text(raw_text)
                
                df_extracted = pd.DataFrame(extracted_rows)
                df_extracted['المشرف'] = get_supervisors()[0]  # قيمة افتراضية
                df_extracted['ملاحظات'] = ""
                df_extracted = df_extracted[['نوع البالة', 'وزن البالة', 'التاريخ', 'الوقت', 'المشرف', 'ملاحظات']]
                
                st.subheader("البيانات المستخرجة (قابل للتعديل)")
                edited_df = st.data_editor(
                    df_extracted,
                    num_rows="dynamic",
                    column_config={
                        "نوع البالة": st.column_config.SelectboxColumn(
                            "نوع البالة",
                            options=get_bale_types(),
                            required=True
                        ),
                        "وزن البالة": st.column_config.NumberColumn("الوزن (كجم)", min_value=0.0, step=0.1, required=True),
                        "التاريخ": st.column_config.DateColumn("التاريخ", required=True),
                        "الوقت": st.column_config.TimeColumn("الوقت", required=True),
                        "المشرف": st.column_config.SelectboxColumn(
                            "المشرف",
                            options=get_supervisors(),
                            required=True
                        ),
                        "ملاحظات": st.column_config.TextColumn("ملاحظات"),
                    },
                    use_container_width=True
                )
                
                if st.button("💾 حفظ البيانات المستخرجة في النظام"):
                    if edited_df.empty:
                        st.warning("لا توجد بيانات للحفظ")
                    else:
                        invalid = edited_df[edited_df['وزن البالة'] <= 0]
                        if not invalid.empty:
                            st.error(f"يوجد {len(invalid)} صفاً وزنها غير صحيح (يجب أن يكون أكبر من 0)")
                        else:
                            new_records_count = 0
                            for _, row in edited_df.iterrows():
                                new_record = {
                                    'التاريخ': row['التاريخ'],
                                    'الوقت': row['الوقت'],
                                    'الوردية': get_current_shift(),
                                    'المشرف': row['المشرف'],
                                    'نوع البالة': row['نوع البالة'],
                                    'وزن البالة': row['وزن البالة'],
                                    'ملاحظات': row.get('ملاحظات', '')
                                }
                                cotton_df = pd.concat([cotton_df, pd.DataFrame([new_record])], ignore_index=True)
                                new_records_count += 1
                            if save_cotton_data(cotton_df, f"إضافة {new_records_count} سجل من الصورة"):
                                st.success(f"تم حفظ {new_records_count} سجل بنجاح")
                                st.rerun()
            else:
                st.error("لم يتم التعرف على أي بيانات (نوع ووزن) في الصورة. حاول رفع صورة أوضح أو استخدم الإدخال اليدوي.")
                with st.expander("النص الخام المستخرج (للتشخيص)"):
                    st.text(raw_text if raw_text else "(فارغ)")

# تبويب الإحصائيات
if perms["can_view_stats"] and "📊 عرض الإحصائيات" in tabs_list:
    idx = tabs_list.index("📊 عرض الإحصائيات")
    with tabs[idx]:
        st.header("الإحصائيات")
        if cotton_df.empty:
            st.warning("لا توجد بيانات")
        else:
            col1, col2 = st.columns(2)
            with col1:
                sd = st.date_input("من", datetime.now().date() - timedelta(days=7))
            with col2:
                ed = st.date_input("إلى", datetime.now().date())
            if st.button("عرض الإحصائيات"):
                stats = generate_statistics(cotton_df, sd, ed)
                if not stats.empty:
                    st.dataframe(stats)
                    total_w = stats['إجمالي الوزن'].sum()
                    st.metric("إجمالي الوزن", f"{total_w:,.1f} كجم")
                else:
                    st.warning("لا توجد بيانات في هذه الفترة")
