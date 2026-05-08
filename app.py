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

# محاولة استيراد PyGithub
try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

# محاولة استيراد Pytesseract (بديل خفيف)
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    st.warning("⚠ ميزة مسح الصور غير متاحة. قم بتثبيت Pytesseract و Tesseract OCR.")

# بقية الإعدادات كما هي (بدون تغيير)
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

# ... (جميع دوال load_users, save_users, load_state, save_state, cleanup_sessions, remaining_time, logout_action, login_ui تبقى كما هي في كودك السابق، لم أقم بتغييرها) ...

# -------------------------------
# دوال OCR باستخدام Pytesseract
# -------------------------------
def extract_text_from_image(image_bytes):
    """استخراج النص من الصورة باستخدام Tesseract"""
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # تحسين الصورة: تحويل إلى تدرج رمادي
        if img.mode != 'L':
            img = img.convert('L')
        # زيادة الوضوح
        img = img.point(lambda x: 0 if x < 150 else 255, '1')
        text = pytesseract.image_to_string(img, lang='ara+eng')
        return text
    except Exception as e:
        st.error(f"⚠ خطأ في OCR: {e}")
        return ""

def parse_ocr_text(text):
    """تحليل النص المستخرج"""
    weight = None
    bale_type = ""
    notes_parts = []
    
    # البحث عن الوزن
    weight_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:kg|كجم|كغ)',
        r'(?:وزن|الوزن)[:\s]*(\d+(?:\.\d+)?)'
    ]
    for pattern in weight_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            weight = float(m.group(1))
            break
    if weight is None:
        numbers = re.findall(r'\b(\d+(?:\.\d+)?)\b', text)
        for n in numbers:
            val = float(n)
            if 1 <= val <= 5000:
                weight = val
                break
    
    # البحث عن كود T.A (C1-0-0)
    code_pattern = r'(T\.A\s*\([^)]+\))'
    codes = re.findall(code_pattern, text, re.IGNORECASE)
    if codes:
        bale_type = codes[0]
    
    # تجميع الملاحظات
    remaining = text
    if weight is not None:
        remaining = re.sub(r'\b' + re.escape(str(weight)) + r'\b', '', remaining)
    for code in codes:
        remaining = remaining.replace(code, '')
    remaining = re.sub(r'[^\w\s\(\)\-\.:]', ' ', remaining)
    remaining = re.sub(r'\s+', ' ', remaining).strip()
    if remaining:
        notes_parts.append(remaining)
    
    grade_match = re.search(r'(درجة|الدرجة)[:\s]*([^\n]+)', text, re.IGNORECASE)
    if grade_match:
        notes_parts.append(f"الدرجة: {grade_match.group(2).strip()}")
    
    notes = " | ".join(notes_parts) if notes_parts else ""
    return weight, bale_type, notes

# -------------------------------
# دوال النظام الأساسية (بدون تغيير)
# -------------------------------
def get_current_shift():
    now = datetime.now()
    current_hour = now.hour
    for shift_name, shift_times in APP_CONFIG["SHIFTS"].items():
        if shift_times["start"] <= current_hour < shift_times["end"]:
            return shift_name
    return "الثالثه"

def get_supervisors():
    return ["انسT.A", "عبدالحميدT.B", "محمود فتحيT.C", "احمد عبالعزيزT.D"]

def get_bale_types():
    return ["قماش", "تراب", "هبوه دست", "اسطبات تدویر", "برم", "برم انفاق", "بلاستيك",
            "هبوه تنظيف", "انفاق", "شرق الغزل", "تمشيط غير مغلف", "تمشيط مغلف", "مكس", "كرد", "قطن خام", "ملح"]

def add_new_record(df, supervisor, bale_type, weight, notes=""):
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
    if "all" in user_permissions:
        return {"can_input": True, "can_view_stats": True}
    elif "data_entry" in user_permissions:
        return {"can_input": True, "can_view_stats": False}
    elif "view_stats" in user_permissions:
        return {"can_input": False, "can_view_stats": True}
    else:
        return {"can_input": False, "can_view_stats": True}

# -------------------------------
# دوال تحميل وحفظ البيانات من GitHub (نفسها)
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
        st.error(f"⚠ فشل التحديث من GitHub: {e}")
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
        st.error(f"❌ خطأ في تحميل البيانات: {e}")
        return pd.DataFrame()

def create_new_cotton_file():
    try:
        columns = ['التاريخ', 'الوقت', 'الوردية', 'المشرف', 'نوع البالة', 'وزن البالة', 'ملاحظات']
        df = pd.DataFrame(columns=columns)
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        return True
    except Exception as e:
        st.error(f"❌ خطأ في إنشاء الملف: {e}")
        return False

def save_cotton_data(df, commit_message="تحديث بيانات مكبس القطن"):
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
                    repo.update_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, sha=contents.sha, branch=APP_CONFIG["BRANCH"])
                    st.success("✅ تم الحفظ والرفع إلى GitHub")
                except:
                    repo.create_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, branch=APP_CONFIG["BRANCH"])
                    st.success("✅ تم إنشاء ملف جديد على GitHub")
            except Exception as e:
                st.warning(f"⚠ تم الحفظ محلياً فقط: {e}")
        return True
    except Exception as e:
        st.error(f"❌ خطأ في حفظ البيانات: {e}")
        return False

# -------------------------------
# الواجهة الرئيسية
# -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

# شريط جانبي (نفسه)
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
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج"):
        logout_action()

cotton_df = load_cotton_data()
st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

permissions = get_user_permissions(st.session_state.get("user_role", "viewer"), st.session_state.get("user_permissions", ["view_stats"]))

tab_titles = []
if permissions["can_input"]:
    tab_titles.append("📥 إدخال البيانات")
    if OCR_AVAILABLE:
        tab_titles.append("📸 مسح ضوئي من صورة")
    else:
        st.sidebar.info("🔍 لتفعيل مسح الصور: ثبّت Tesseract و pytesseract")
if permissions["can_view_stats"]:
    tab_titles.append("📊 عرض الإحصائيات")

tabs = st.tabs(tab_titles)

# تبويب الإدخال اليدوي
if permissions["can_input"] and "📥 إدخال البيانات" in tab_titles:
    idx = tab_titles.index("📥 إدخال البيانات")
    with tabs[idx]:
        st.header("📥 إدخال بيانات البالات")
        current_shift = get_current_shift()
        st.info(f"الوردية الحالية: {current_shift} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        with st.form("manual_form"):
            col1, col2 = st.columns(2)
            with col1:
                supervisor = st.selectbox("المشرف", get_supervisors())
                bale_type = st.selectbox("نوع البالة", get_bale_types())
            with col2:
                weight = st.number_input("الوزن (كجم)", min_value=0.0, step=0.1)
                notes = st.text_input("ملاحظات")
            if st.form_submit_button("حفظ"):
                if weight > 0:
                    _, new_df = add_new_record(cotton_df, supervisor, bale_type, weight, notes)
                    if save_cotton_data(new_df):
                        st.success("تم الحفظ")
                        st.rerun()
                else:
                    st.error("الوزن غير صحيح")

# تبويب مسح الصور
if permissions["can_input"] and OCR_AVAILABLE and "📸 مسح ضوئي من صورة" in tab_titles:
    idx = tab_titles.index("📸 مسح ضوئي من صورة")
    with tabs[idx]:
        st.header("رفع صورة واستخراج البيانات")
        uploaded = st.file_uploader("اختر صورة", type=["jpg","jpeg","png"])
        if uploaded:
            st.image(uploaded, use_column_width=True)
            with st.spinner("تحليل الصورة..."):
                text = extract_text_from_image(uploaded.getvalue())
            if text.strip():
                st.success("تم الاستخراج")
                with st.expander("النص الخام"):
                    st.text(text)
                weight, bale_type, notes = parse_ocr_text(text)
                with st.form("ocr_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        supervisor = st.selectbox("المشرف", get_supervisors(), key="ocr_sup")
                        bale_options = get_bale_types()
                        default_idx = bale_options.index(bale_type) if bale_type in bale_options else 0
                        bale_final = st.selectbox("نوع البالة", bale_options, index=default_idx)
                    with col2:
                        weight_final = st.number_input("الوزن", value=float(weight) if weight else 0.0, step=0.1)
                        notes_final = st.text_area("ملاحظات", value=notes)
                    if st.form_submit_button("حفظ من الصورة"):
                        if weight_final > 0:
                            _, new_df = add_new_record(cotton_df, supervisor, bale_final, weight_final, notes_final)
                            if save_cotton_data(new_df):
                                st.success("تم الحفظ")
                                st.rerun()
                        else:
                            st.error("أدخل وزناً صحيحاً")
            else:
                st.error("لم يتم التعرف على نص")

# تبويب الإحصائيات
if permissions["can_view_stats"] and "📊 عرض الإحصائيات" in tab_titles:
    idx = tab_titles.index("📊 عرض الإحصائيات")
    with tabs[idx]:
        st.header("الإحصائيات")
        if cotton_df.empty:
            st.warning("لا توجد بيانات")
        else:
            col1, col2 = st.columns(2)
            with col1:
                start = st.date_input("من", datetime.now().date() - timedelta(days=7))
            with col2:
                end = st.date_input("إلى", datetime.now().date())
            if st.button("عرض"):
                stats = generate_statistics(cotton_df, start, end)
                if not stats.empty:
                    st.dataframe(stats)
                    total = stats['إجمالي الوزن'].sum()
                    st.metric("إجمالي الوزن", f"{total:,.1f} كجم")
                else:
                    st.warning("لا توجد بيانات في هذه الفترة")
