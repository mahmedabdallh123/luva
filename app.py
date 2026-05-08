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

# GitHub
try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

# OCR باستخدام pytesseract (أخف)
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    st.warning("⚠ pytesseract غير مثبت، ميزة مسح الصور معطلة")

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
# دوال المستخدمين والجلسات
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
            # التأكد من الحقول
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
# دوال النظام
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
# OCR دوال
# -------------------------------
def extract_text_from_image(image_bytes):
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'L':
            img = img.convert('L')
        img = img.point(lambda x: 0 if x < 150 else 255, '1')
        text = pytesseract.image_to_string(img, lang='ara+eng')
        return text
    except Exception as e:
        st.error(f"OCR خطأ: {e}")
        return ""

def parse_ocr_text(text):
    weight = None
    bale_type = ""
    notes_parts = []
    # وزن
    patterns = [r'(\d+(?:\.\d+)?)\s*(?:kg|كجم|كغ)', r'(?:وزن|الوزن)[:\s]*(\d+(?:\.\d+)?)']
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            weight = float(m.group(1))
            break
    if weight is None:
        nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', text)
        for n in nums:
            v = float(n)
            if 1 <= v <= 5000:
                weight = v
                break
    # كود T.A
    codes = re.findall(r'(T\.A\s*\([^)]+\))', text, re.I)
    if codes:
        bale_type = codes[0]
    # ملاحظات
    remaining = text
    if weight is not None:
        remaining = re.sub(r'\b' + re.escape(str(weight)) + r'\b', '', remaining)
    for c in codes:
        remaining = remaining.replace(c, '')
    remaining = re.sub(r'[^\w\s\(\)\-\.:]', ' ', remaining)
    remaining = re.sub(r'\s+', ' ', remaining).strip()
    if remaining:
        notes_parts.append(remaining)
    grade = re.search(r'(درجة|الدرجة)[:\s]*([^\n]+)', text, re.I)
    if grade:
        notes_parts.append(f"الدرجة: {grade.group(2).strip()}")
    notes = " | ".join(notes_parts) if notes_parts else ""
    return weight, bale_type, notes

# -------------------------------
# الواجهة الرئيسية
# -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

# السايدبار
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

# بناء التبويبات
tabs_list = []
if perms["can_input"]:
    tabs_list.append("📥 إدخال البيانات")
    if OCR_AVAILABLE:
        tabs_list.append("📸 مسح ضوئي من صورة")
    else:
        st.sidebar.info("🔍 لتفعيل المسح: ثبّت pytesseract و Tesseract OCR")
if perms["can_view_stats"]:
    tabs_list.append("📊 عرض الإحصائيات")

if not tabs_list:
    tabs_list = ["📊 عرض الإحصائيات"]

tabs = st.tabs(tabs_list)

# تبويب الإدخال اليدوي
if perms["can_input"] and "📥 إدخال البيانات" in tabs_list:
    idx = tabs_list.index("📥 إدخال البيانات")
    with tabs[idx]:
        st.header("إدخال بيانات البالات")
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

# تبويب OCR
if perms["can_input"] and OCR_AVAILABLE and "📸 مسح ضوئي من صورة" in tabs_list:
    idx = tabs_list.index("📸 مسح ضوئي من صورة")
    with tabs[idx]:
        st.header("رفع صورة واستخراج البيانات")
        uploaded = st.file_uploader("اختر صورة", type=["jpg","jpeg","png"])
        if uploaded:
            st.image(uploaded, use_column_width=True)
            with st.spinner("تحليل الصورة..."):
                extracted = extract_text_from_image(uploaded.getvalue())
            if extracted.strip():
                st.success("تم الاستخراج")
                with st.expander("النص الخام"):
                    st.text(extracted)
                w, bt, nt = parse_ocr_text(extracted)
                with st.form("ocr"):
                    col1, col2 = st.columns(2)
                    with col1:
                        sup2 = st.selectbox("المشرف", get_supervisors(), key="ocr_sup")
                        btypes = get_bale_types()
                        def_idx = btypes.index(bt) if bt in btypes else 0
                        bt2 = st.selectbox("نوع البالة", btypes, index=def_idx)
                    with col2:
                        w2 = st.number_input("الوزن", value=float(w) if w else 0.0, step=0.1)
                        nt2 = st.text_area("ملاحظات", value=nt)
                    if st.form_submit_button("حفظ من الصورة"):
                        if w2 > 0:
                            _, new_df = add_new_record(cotton_df, sup2, bt2, w2, nt2)
                            if save_cotton_data(new_df):
                                st.success("تم الحفظ")
                                st.rerun()
                        else:
                            st.error("أدخل وزناً صحيحاً")
            else:
                st.error("لم يتم التعرف على نص في الصورة")

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
