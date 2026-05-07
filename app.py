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
from PIL import Image
import numpy as np
import tempfile

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

try:
    from github import Github
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False

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
    },
}

USERS_FILE = "users.json"
STATE_FILE = "state.json"
SESSION_DURATION = timedelta(minutes=APP_CONFIG["SESSION_DURATION_MINUTES"])
MAX_ACTIVE_USERS = APP_CONFIG["MAX_ACTIVE_USERS"]
GITHUB_EXCEL_URL = f"https://github.com/{APP_CONFIG['REPO_NAME']}/raw/{APP_CONFIG['BRANCH']}/{APP_CONFIG['FILE_PATH']}"

# -------------------------------
# دوال OCR (بدون تغيير)
# -------------------------------
@st.cache_resource
def get_ocr_reader():
    if not EASYOCR_AVAILABLE:
        return None
    try:
        with st.spinner("جاري تحميل نموذج OCR (أول مرة فقط، قد يستغرق 30-60 ثانية)..."):
            reader = easyocr.Reader(['ar', 'en'], gpu=False, verbose=False, model_storage_directory='.easyocr')
        return reader
    except Exception as e:
        st.error(f"فشل تحميل OCR: {e}")
        return None

def extract_text_from_image(image_file):
    reader = get_ocr_reader()
    if reader is None:
        return "OCR غير متوفر"
    img = Image.open(image_file).convert('RGB')
    img_np = np.array(img)
    gray = np.dot(img_np[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    binary = ((gray > 150) * 255).astype(np.uint8)
    binary_inv = 255 - binary
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        Image.fromarray(binary_inv).save(tmp.name)
        tmp_path = tmp.name
    try:
        results = reader.readtext(tmp_path, detail=0, paragraph=False)
        text = ' '.join(results)
    except Exception as e:
        text = f"خطأ: {e}"
    finally:
        os.unlink(tmp_path)
    return text

def parse_ocr_text(text):
    data = {
        'bale_type': None,
        'weight': None,
        'degree': None,
        'production': None,
        'date': None,
        'time': None,
        'raw_text': text
    }
    if not text or "خطأ" in text:
        return data
    bale_types = get_bale_types()
    for bt in bale_types:
        if bt in text:
            data['bale_type'] = bt
            break
    weight_patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:كجم|kg|كغ)',
        r'وزن[:\s]*(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*كجم'
    ]
    for pat in weight_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data['weight'] = float(m.group(1))
            break
    degree_patterns = [
        r'(?:الدرجة[:\s]*)?([Cc]\d+[-]\d+[-]\d+)',
        r'(?:الدرجة[:\s]*)?(\d{1,2})',
        r'(?:درجة[:\s]*)([^\n]+)'
    ]
    for pat in degree_patterns:
        m = re.search(pat, text)
        if m:
            data['degree'] = m.group(1).strip()
            break
    if not data['degree']:
        m = re.search(r'([Cc]\d+[-]\d+[-]\d+)', text)
        if m:
            data['degree'] = m.group(1)
    prod_patterns = [
        r'(?:الإنتاج[:\s]*)(\d+(?:\.\d+)?)\s*(?:طن|كجم)?',
        r'(?:إنتاج[:\s]*)(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*طن'
    ]
    for pat in prod_patterns:
        m = re.search(pat, text)
        if m:
            data['production'] = m.group(1).strip()
            break
    # تاريخ
    date_patterns = [
        r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        r'(\d{8})'
    ]
    for pat in date_patterns:
        m = re.search(pat, text)
        if m:
            ds = m.group(1)
            try:
                if len(ds) == 8 and ds.isdigit():
                    data['date'] = datetime.strptime(ds, '%Y%m%d').date()
                else:
                    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
                        try:
                            data['date'] = datetime.strptime(ds, fmt).date()
                            break
                        except:
                            continue
                break
            except:
                pass
    # وقت
    time_match = re.search(r'(\d{1,2}:\d{2})', text)
    if time_match:
        try:
            data['time'] = datetime.strptime(time_match.group(1), '%H:%M').time()
        except:
            pass
    return data

# -------------------------------
# دوال المستخدمين والجلسات (نفس السابق)
# -------------------------------
def load_users():
    if not os.path.exists(USERS_FILE):
        default = {
            "admin": {"password": "1111", "role": "admin", "permissions": ["all"]},
            "user1": {"password": "12345", "role": "data_entry", "permissions": ["data_entry"]},
            "user2": {"password": "99999", "role": "viewer", "permissions": ["view_stats"]}
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    for uname, data in users.items():
        if "role" not in data:
            data["role"] = "viewer"
        if "permissions" not in data:
            if data["role"] == "admin":
                data["permissions"] = ["all"]
            elif data["role"] == "data_entry":
                data["permissions"] = ["data_entry"]
            else:
                data["permissions"] = ["view_stats"]
    return users

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def cleanup_sessions(state):
    now = datetime.now()
    changed = False
    for user, info in list(state.items()):
        if info.get("active") and "login_time" in info:
            try:
                lt = datetime.fromisoformat(info["login_time"])
                if now - lt > SESSION_DURATION:
                    info["active"] = False
                    info.pop("login_time")
                    changed = True
            except:
                info["active"] = False
                changed = True
    if changed:
        save_state(state)
    return state

def remaining_time(state, username):
    if username not in state:
        return None
    info = state[username]
    if not info.get("active"):
        return None
    try:
        lt = datetime.fromisoformat(info["login_time"])
        rem = SESSION_DURATION - (datetime.now() - lt)
        return rem if rem.total_seconds() > 0 else None
    except:
        return None

def logout_action():
    state = load_state()
    uname = st.session_state.get("username")
    if uname and uname in state:
        state[uname]["active"] = False
        state[uname].pop("login_time", None)
        save_state(state)
    for k in list(st.session_state.keys()):
        st.session_state.pop(k)
    st.rerun()

def login_ui():
    users = load_users()
    state = cleanup_sessions(load_state())
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_role = None
        st.session_state.user_permissions = []
    st.title(f"{APP_CONFIG['APP_ICON']} تسجيل الدخول")
    username = st.selectbox("المستخدم", list(users.keys()))
    password = st.text_input("كلمة المرور", type="password")
    active_count = len([u for u, v in state.items() if v.get("active")])
    st.caption(f"المستخدمون النشطون: {active_count}/{MAX_ACTIVE_USERS}")
    if st.button("تسجيل الدخول"):
        if username in users and users[username].get("password") == password:
            if username != "admin" and username in state and state[username].get("active"):
                st.warning("مسجل بالفعل")
                return False
            if active_count >= MAX_ACTIVE_USERS and username != "admin":
                st.error("الحد الأقصى للمستخدمين النشطين")
                return False
            state[username] = {"active": True, "login_time": datetime.now().isoformat()}
            save_state(state)
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.user_role = users[username].get("role", "viewer")
            st.session_state.user_permissions = users[username].get("permissions", ["view_stats"])
            st.rerun()
        else:
            st.error("اسم المستخدم أو كلمة المرور غير صحيحة")
    return st.session_state.logged_in

# -------------------------------
# دالة حفظ ملف Excel محلياً بأوراق متعددة
# -------------------------------
def save_excel_locally(sheets_dict, filename):
    """
    حفظ قاموس من DataFrames إلى ملف Excel متعدد الأوراق.
    sheets_dict: dict {sheet_name: DataFrame}
    filename: اسم الملف (مثل "report.xlsx")
    """
    try:
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            for sheet_name, df in sheets_dict.items():
                if not df.empty:
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                else:
                    # إنشاء ورقة فارغة مع رسالة
                    pd.DataFrame({'ملاحظة': ['لا توجد بيانات']}).to_excel(writer, sheet_name=sheet_name, index=False)
        st.success(f"✅ تم حفظ الملف {filename} محلياً بنجاح")
        return True
    except Exception as e:
        st.error(f"❌ خطأ في حفظ الملف محلياً: {e}")
        return False

# -------------------------------
# دالة رفع ملف إلى GitHub
# -------------------------------
def push_to_github(filename, commit_message="تحديث الملف"):
    """
    رفع ملف إلى GitHub باستخدام PyGithub أو API.
    filename: اسم الملف المحلي المراد رفعه.
    commit_message: رسالة التعديل.
    """
    token = st.secrets.get("github", {}).get("token", None)
    if not token or not GITHUB_AVAILABLE:
        st.warning("⚠ لم يتم إعداد توكن GitHub أو المكتبة غير متوفرة. سيتم الحفظ محلياً فقط.")
        return False

    try:
        g = Github(token)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        with open(filename, "rb") as f:
            content = f.read()

        try:
            # محاولة تحديث الملف الموجود
            contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
            repo.update_file(
                path=APP_CONFIG["FILE_PATH"],
                message=commit_message,
                content=content,
                sha=contents.sha,
                branch=APP_CONFIG["BRANCH"]
            )
            st.success(f"✅ تم رفع {filename} إلى GitHub (تحديث)")
        except Exception:
            # إنشاء ملف جديد
            repo.create_file(
                path=APP_CONFIG["FILE_PATH"],
                message=commit_message,
                content=content,
                branch=APP_CONFIG["BRANCH"]
            )
            st.success(f"✅ تم إنشاء ملف {filename} على GitHub")
        return True
    except Exception as e:
        st.error(f"❌ فشل الرفع إلى GitHub: {e}")
        return False

# -------------------------------
# دوال البيانات والإحصائيات (معدلة لاستخدام الدوال الجديدة)
# -------------------------------
def fetch_from_github():
    try:
        r = requests.get(GITHUB_EXCEL_URL, stream=True, timeout=10)
        r.raise_for_status()
        with open(APP_CONFIG["LOCAL_FILE"], "wb") as f:
            shutil.copyfileobj(r.raw, f)
        st.cache_data.clear()
        return True
    except:
        return False

@st.cache_data(show_spinner=False)
def load_cotton_data():
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        columns = ['التاريخ','الوقت','الوردية','المشرف','نوع البالة','وزن البالة','الدرجة','الإنتاج','ملاحظات']
        df = pd.DataFrame(columns=columns)
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        return df
    return pd.read_excel(APP_CONFIG["LOCAL_FILE"])

def save_cotton_data(df, commit_message="تحديث بيانات مكبس القطن"):
    """
    حفظ البيانات إلى ملف Excel محلياً ورفعها إلى GitHub.
    تستخدم الدوال الجديدة save_excel_locally و push_to_github.
    """
    # حفظ الملف محلياً
    success_local = save_excel_locally({APP_CONFIG["FILE_PATH"]: df}, APP_CONFIG["LOCAL_FILE"])
    if not success_local:
        return False

    # مسح الكاش
    st.cache_data.clear()

    # الرفع إلى GitHub
    success_github = push_to_github(APP_CONFIG["LOCAL_FILE"], commit_message)
    return success_local or success_github  # إذا نجح أحدهما على الأقل

def get_current_shift():
    hour = datetime.now().hour
    for name, times in APP_CONFIG["SHIFTS"].items():
        if times["start"] <= hour < times["end"]:
            return name
    return "الثالثه"

def get_supervisors():
    return ["T.A", "T.B", "T.C", "T.D"]

def get_bale_types():
    return ["قماش","تراب","هبوه دست","اسطبات تدویر","برم","برم انفاق","بلاستيك","هبوه تنظيف","انفاق","شرق الغزل","تمشيط غير مغلف","تمشيط مغلف","مكس","كرد","قطن خام","ملح"]

def add_record(df, sup, btype, weight, degree, production, notes, mdate, mshift):
    now = datetime.now()
    date = mdate if mdate else now.date()
    shift = mshift if mshift else get_current_shift()
    rec = {
        'التاريخ': date,
        'الوقت': now.time(),
        'الوردية': shift,
        'المشرف': sup,
        'نوع البالة': btype,
        'وزن البالة': weight,
        'الدرجة': degree,
        'الإنتاج': production,
        'ملاحظات': notes
    }
    return pd.concat([df, pd.DataFrame([rec])], ignore_index=True)

def generate_statistics(df, start_date, end_date, selected_shifts, selected_bale_types):
    if df.empty:
        return pd.DataFrame()
    cot_df = df.copy()
    cot_df['التاريخ'] = pd.to_datetime(cot_df['التاريخ']).dt.date
    mask = (cot_df['التاريخ'] >= start_date) & (cot_df['التاريخ'] <= end_date)
    if selected_shifts:
        mask &= cot_df['الوردية'].isin(selected_shifts)
    if selected_bale_types:
        mask &= cot_df['نوع البالة'].isin(selected_bale_types)
    filtered = cot_df[mask]
    if filtered.empty:
        return pd.DataFrame()
    stats = filtered.groupby('نوع البالة').agg({
        'وزن البالة': ['count', 'sum', 'mean'],
        'الدرجة': 'first',
        'الإنتاج': 'first'
    }).round(2)
    stats.columns = ['عدد البالات', 'إجمالي الوزن', 'متوسط الوزن', 'الدرجة', 'الإنتاج']
    return stats.reset_index()

def get_permissions(role, perms):
    if "all" in perms or role == "admin":
        return {"can_input": True, "can_view_stats": True}
    if "data_entry" in perms:
        return {"can_input": True, "can_view_stats": False}
    return {"can_input": False, "can_view_stats": True}

# -------------------------------
# الواجهة الرئيسية
# -------------------------------
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

with st.sidebar:
    if not st.session_state.get("logged_in"):
        if not login_ui():
            st.stop()
    else:
        state = load_state()
        rem = remaining_time(state, st.session_state.username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.success(f"{st.session_state.username} | {st.session_state.user_role} | {mins:02d}:{secs:02d}")
        else:
            logout_action()
        if st.button("تسجيل الخروج"):
            logout_action()
        st.markdown("---")
        if st.button("تحديث من GitHub"):
            if fetch_from_github():
                st.rerun()
        if st.button("مسح الكاش"):
            st.cache_data.clear()
            st.rerun()

if not st.session_state.get("logged_in"):
    st.stop()

cotton_df = load_cotton_data()
perms = get_permissions(st.session_state.user_role, st.session_state.user_permissions)

if perms["can_input"] and perms["can_view_stats"]:
    tab1, tab2 = st.tabs(["📥 إدخال البيانات", "📊 الإحصائيات"])
    input_tab = tab1
    stats_tab = tab2
elif perms["can_input"]:
    input_tab = st.tabs(["📥 إدخال البيانات"])[0]
else:
    stats_tab = st.tabs(["📊 الإحصائيات"])[0]

# ========== تبويب إدخال البيانات ==========
if perms["can_input"]:
    with input_tab:
        st.header("📥 إدخال بيانات البالات")
        use_ocr = st.checkbox("🔍 تمكين الاستخراج التلقائي من الصور (OCR)", value=False)
        with st.expander("📸 رفع صورة واستخراج البيانات", expanded=use_ocr):
            if use_ocr:
                if not EASYOCR_AVAILABLE:
                    st.error("مكتبة easyocr غير مثبتة. قم بتثبيتها: pip install easyocr")
                else:
                    img_file = st.file_uploader("اختر صورة", type=["png","jpg","jpeg"], key="ocr_input")
                    if img_file:
                        with st.spinner("تحليل الصورة..."):
                            raw_text = extract_text_from_image(img_file)
                            parsed = parse_ocr_text(raw_text)
                        st.write("**النص المستخرج:**", raw_text[:400])
                        if parsed['weight'] or parsed['degree'] or parsed['production']:
                            st.success("تم استخراج البيانات:")
                            col1, col2, col3 = st.columns(3)
                            col1.metric("الوزن", parsed['weight'] if parsed['weight'] else "؟")
                            col2.metric("الدرجة", parsed['degree'] if parsed['degree'] else "؟")
                            col3.metric("الإنتاج", parsed['production'] if parsed['production'] else "؟")
                            if st.button("✍️ استخدام هذه البيانات"):
                                st.session_state.ocr_bale_type = parsed['bale_type']
                                st.session_state.ocr_weight = parsed['weight']
                                st.session_state.ocr_degree = parsed['degree']
                                st.session_state.ocr_production = parsed['production']
                                st.session_state.ocr_date = parsed['date']
                                st.rerun()
                        else:
                            st.warning("لم يتم استخراج بيانات. حاول رفع صورة أوضح.")
            else:
                st.info("فعّل خيار OCR أعلاه")
        with st.form(key="data_form"):
            col1, col2 = st.columns(2)
            with col1:
                supervisor = st.selectbox("المشرف", get_supervisors())
                default_type = st.session_state.get("ocr_bale_type", get_bale_types()[0])
                type_idx = get_bale_types().index(default_type) if default_type in get_bale_types() else 0
                bale_type = st.selectbox("نوع البالة", get_bale_types(), index=type_idx)
                default_degree = st.session_state.get("ocr_degree", "")
                degree = st.text_input("الدرجة", value=default_degree)
                auto_date = st.checkbox("تاريخ تلقائي", value=True)
                if not auto_date:
                    manual_date = st.date_input("التاريخ", value=st.session_state.get("ocr_date", datetime.now().date()))
                else:
                    manual_date = None
            with col2:
                default_weight = st.session_state.get("ocr_weight", 0.0)
                weight = st.number_input("الوزن (كجم)", min_value=0.0, step=0.1, value=default_weight)
                default_prod = st.session_state.get("ocr_production", "")
                production = st.text_input("الإنتاج (طن/كجم)", value=default_prod)
                notes = st.text_input("ملاحظات")
                auto_shift = st.checkbox("وردية تلقائية", value=True)
                if not auto_shift:
                    manual_shift = st.selectbox("الوردية", list(APP_CONFIG["SHIFTS"].keys()))
                else:
                    manual_shift = None
            submitted = st.form_submit_button("💾 حفظ البيانات")
            if submitted:
                if weight <= 0:
                    st.error("الوزن يجب أن يكون أكبر من صفر")
                else:
                    new_df = add_record(cotton_df, supervisor, bale_type, weight, degree, production, notes, manual_date, manual_shift)
                    if save_cotton_data(new_df, f"إضافة بالة {bale_type} وزن {weight}"):
                        st.success("تم الحفظ والرفع بنجاح")
                        for k in ["ocr_bale_type","ocr_weight","ocr_degree","ocr_production","ocr_date"]:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

# ========== تبويب الإحصائيات ==========
if perms["can_view_stats"]:
    with stats_tab:
        st.header("📊 الإحصائيات")
        if cotton_df.empty:
            st.warning("لا توجد بيانات")
        else:
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("من تاريخ", datetime.now().date() - timedelta(days=7))
                end_date = st.date_input("إلى تاريخ", datetime.now().date())
            with col2:
                shifts = st.multiselect("الورديات", list(APP_CONFIG["SHIFTS"].keys()), default=list(APP_CONFIG["SHIFTS"].keys()))
                bale_types = st.multiselect("أنواع البالات", get_bale_types(), default=get_bale_types())
            if st.button("عرض الإحصائيات"):
                stats_df = generate_statistics(cotton_df, start_date, end_date, shifts, bale_types)
                if stats_df.empty:
                    st.warning("لا توجد بيانات")
                else:
                    st.dataframe(stats_df, use_container_width=True)
                    total_weight = stats_df['إجمالي الوزن'].sum()
                    total_count = stats_df['عدد البالات'].sum()
                    col1, col2, col3 = st.columns(3)
                    col1.metric("إجمالي البالات", f"{total_count}")
                    col2.metric("إجمالي الوزن", f"{total_weight:.1f} كجم")
                    col3.metric("متوسط الوزن", f"{total_weight/total_count:.1f}" if total_count else "0")
                    # تصدير تقرير متعدد الأوراق باستخدام الدالة الجديدة
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        stats_df.to_excel(writer, sheet_name='الإحصائيات', index=False)
                        cot_df = cotton_df.copy()
                        cot_df['التاريخ'] = pd.to_datetime(cot_df['التاريخ']).dt.date
                        mask = (cot_df['التاريخ'] >= start_date) & (cot_df['التاريخ'] <= end_date)
                        if shifts:
                            mask &= cot_df['الوردية'].isin(shifts)
                        if bale_types:
                            mask &= cot_df['نوع البالة'].isin(bale_types)
                        detailed = cot_df[mask]
                        detailed.to_excel(writer, sheet_name='التفاصيل', index=False)
                    st.download_button("تحميل تقرير Excel", data=buffer.getvalue(),
                                       file_name=f"تقرير_{start_date}_{end_date}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
