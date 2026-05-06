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
import easyocr

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
# دوال OCR
# -------------------------------
@st.cache_resource
def init_ocr_reader():
    return easyocr.Reader(['ar', 'en'], gpu=False)

def extract_data_from_image(image_file):
    img = Image.open(image_file).convert('RGB')
    img_np = np.array(img)
    gray = np.dot(img_np[..., :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    binary = ((gray > 150) * 255).astype(np.uint8)
    binary_inv = 255 - binary
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        Image.fromarray(binary_inv).save(tmp.name)
        tmp_path = tmp.name
    reader = init_ocr_reader()
    results = reader.readtext(tmp_path, detail=0, paragraph=False)
    os.unlink(tmp_path)
    full_text = ' '.join(results)
    full_text = full_text.replace('|', 'I').replace('؟', '?')
    data = {'bale_type': None, 'weight': None, 'date': None, 'time': None, 'raw_text': full_text}
    bale_types = get_bale_types()
    for bt in bale_types:
        if bt in full_text:
            data['bale_type'] = bt
            break
    if not data['bale_type']:
        keywords = {'قطن خام': 'قطن خام', 'قماش': 'قماش', 'تراب': 'تراب'}
        for k, v in keywords.items():
            if k in full_text:
                data['bale_type'] = v
                break
    w_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:كجم|kg|كغ)', full_text, re.I)
    if w_match:
        data['weight'] = float(w_match.group(1))
    else:
        w_match2 = re.search(r'وزن[:\s]*(\d+(?:\.\d+)?)', full_text)
        if w_match2:
            data['weight'] = float(w_match2.group(1))
    # تاريخ
    for pattern in [r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})', r'(\d{8})']:
        m = re.search(pattern, full_text)
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
    t_match = re.search(r'(\d{1,2}:\d{2})', full_text)
    if t_match:
        try:
            data['time'] = datetime.strptime(t_match.group(1), '%H:%M').time()
        except:
            pass
    return data

# -------------------------------
# دوال المستخدمين والجلسات
# -------------------------------
def load_users():
    """تحميل المستخدمين مع التأكد من وجود جميع الحقول"""
    if not os.path.exists(USERS_FILE):
        default_users = {
            "admin": {"password": "1111", "role": "admin", "permissions": ["all"]},
            "user1": {"password": "12345", "role": "data_entry", "permissions": ["data_entry"]},
            "user2": {"password": "99999", "role": "viewer", "permissions": ["view_stats"]}
        }
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_users, f, indent=4)
        return default_users
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        # تأكد من أن كل مستخدم له role و permissions
        for username, data in users.items():
            if "role" not in data:
                if username == "admin":
                    data["role"] = "admin"
                    data["permissions"] = ["all"]
                elif username == "user1":
                    data["role"] = "data_entry"
                    data["permissions"] = ["data_entry"]
                else:
                    data["role"] = "viewer"
                    data["permissions"] = ["view_stats"]
            if "permissions" not in data:
                if data["role"] == "admin":
                    data["permissions"] = ["all"]
                elif data["role"] == "data_entry":
                    data["permissions"] = ["data_entry"]
                else:
                    data["permissions"] = ["view_stats"]
        return users
    except Exception as e:
        return {
            "admin": {"password": "1111", "role": "admin", "permissions": ["all"]},
            "user1": {"password": "12345", "role": "data_entry", "permissions": ["data_entry"]},
            "user2": {"password": "99999", "role": "viewer", "permissions": ["view_stats"]}
        }

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
            # استخدام .get مع قيمة افتراضية لتجنب KeyError
            st.session_state.user_role = users[username].get("role", "viewer")
            st.session_state.user_permissions = users[username].get("permissions", ["view_stats"])
            st.rerun()
        else:
            st.error("اسم المستخدم أو كلمة المرور غير صحيحة")
    return st.session_state.logged_in

# -------------------------------
# دوال البيانات والإحصائيات
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
        df = pd.DataFrame(columns=['التاريخ','الوقت','الوردية','المشرف','نوع البالة','وزن البالة','ملاحظات'])
        df.to_excel(APP_CONFIG["LOCAL_FILE"], index=False)
        return df
    return pd.read_excel(APP_CONFIG["LOCAL_FILE"])

def save_cotton_data(df, msg="update"):
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
                repo.update_file(APP_CONFIG["FILE_PATH"], msg, content, contents.sha, branch=APP_CONFIG["BRANCH"])
            except:
                repo.create_file(APP_CONFIG["FILE_PATH"], msg, content, branch=APP_CONFIG["BRANCH"])
            st.success("تم الحفظ والرفع إلى GitHub")
        except Exception as e:
            st.warning(f"حفظ محلي فقط: {e}")
    return True

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

def add_record(df, sup, btype, w, notes, mdate, mshift):
    now = datetime.now()
    date = mdate if mdate else now.date()
    shift = mshift if mshift else get_current_shift()
    rec = {'التاريخ':date, 'الوقت':now.time(), 'الوردية':shift, 'المشرف':sup, 'نوع البالة':btype, 'وزن البالة':w, 'ملاحظات':notes}
    return pd.concat([df, pd.DataFrame([rec])], ignore_index=True)

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

# تبويبات
if perms["can_input"] and perms["can_view_stats"]:
    tab1, tab2 = st.tabs(["📥 إدخال البيانات", "📊 الإحصائيات"])
elif perms["can_input"]:
    tab1 = st.tabs(["📥 إدخال البيانات"])[0]
else:
    tab1 = st.tabs(["📊 الإحصائيات"])[0]

if perms["can_input"] and perms["can_view_stats"]:
    input_tab = tab1
    stats_tab = tab2
elif perms["can_input"]:
    input_tab = tab1
else:
    stats_tab = tab1

# ========== تبويب الإدخال ==========
if perms["can_input"]:
    with input_tab:
        st.header("إدخال بيانات البالات")
        with st.expander("رفع صورة واستخراج البيانات"):
            img_file = st.file_uploader("اختر صورة", type=["png","jpg","jpeg"], key="ocr_img")
            if img_file:
                with st.spinner("تحليل الصورة..."):
                    ex = extract_data_from_image(img_file)
                st.write("**النص المستخرج:**", ex['raw_text'][:300])
                if ex['bale_type'] and ex['weight']:
                    st.success(f"تم التعرف على: {ex['bale_type']} وزن {ex['weight']} كجم")
                    if st.button("استخدام هذه البيانات"):
                        st.session_state.ocr_type = ex['bale_type']
                        st.session_state.ocr_weight = ex['weight']
                        st.session_state.ocr_date = ex['date']
                        st.rerun()
                else:
                    st.warning("لم يتم التعرف على النوع أو الوزن")
        with st.form(key="data_form"):
            col1, col2 = st.columns(2)
            with col1:
                sup = st.selectbox("المشرف", get_supervisors())
                default_type = st.session_state.get("ocr_type", get_bale_types()[0])
                type_index = get_bale_types().index(default_type) if default_type in get_bale_types() else 0
                btype = st.selectbox("نوع البالة", get_bale_types(), index=type_index)
                auto_date = st.checkbox("تاريخ تلقائي", value=True)
                if not auto_date:
                    default_date = st.session_state.get("ocr_date", datetime.now().date())
                    mdate = st.date_input("التاريخ", value=default_date)
                else:
                    mdate = None
            with col2:
                default_weight = st.session_state.get("ocr_weight", 0.0)
                weight = st.number_input("الوزن (كجم)", min_value=0.0, step=0.1, value=default_weight)
                notes = st.text_input("ملاحظات")
                auto_shift = st.checkbox("وردية تلقائية", value=True)
                if not auto_shift:
                    mshift = st.selectbox("الوردية", list(APP_CONFIG["SHIFTS"].keys()))
                else:
                    mshift = None
            submit = st.form_submit_button("💾 حفظ البيانات")
            if submit:
                if weight <= 0:
                    st.error("الوزن يجب أن يكون أكبر من صفر")
                else:
                    new_df = add_record(cotton_df, sup, btype, weight, notes, mdate, mshift)
                    if save_cotton_data(new_df, f"إضافة بالة {btype} وزن {weight}"):
                        st.success("تم الحفظ بنجاح")
                        for k in ["ocr_type","ocr_weight","ocr_date"]:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

# ========== تبويب الإحصائيات ==========
if perms["can_view_stats"]:
    with stats_tab:
        st.header("الإحصائيات")
        if cotton_df.empty:
            st.warning("لا توجد بيانات")
        else:
            cot_df = cotton_df.copy()
            cot_df['التاريخ'] = pd.to_datetime(cot_df['التاريخ']).dt.date
            col1, col2 = st.columns(2)
            with col1:
                sd = st.date_input("من تاريخ", datetime.now().date() - timedelta(days=7))
                ed = st.date_input("إلى تاريخ", datetime.now().date())
            with col2:
                shifts = st.multiselect("الورديات", list(APP_CONFIG["SHIFTS"].keys()), default=list(APP_CONFIG["SHIFTS"].keys()))
                btypes = st.multiselect("أنواع البالات", get_bale_types(), default=get_bale_types())
                perc = st.checkbox("حساب النسبة مقابل قطن خام", True)
            if st.button("عرض الإحصائيات"):
                mask = (cot_df['التاريخ'] >= sd) & (cot_df['التاريخ'] <= ed)
                if shifts:
                    mask &= cot_df['الوردية'].isin(shifts)
                if btypes:
                    mask &= cot_df['نوع البالة'].isin(btypes)
                filtered = cot_df[mask]
                if filtered.empty:
                    st.warning("لا توجد بيانات للفترة المحددة")
                else:
                    stats = filtered.groupby('نوع البالة').agg({'وزن البالة': ['count','sum','mean'], 'المشرف': 'first'}).round(2)
                    stats.columns = ['عدد','إجمالي الوزن','متوسط الوزن','المشرف']
                    stats = stats.reset_index()
                    if perc:
                        cotton_weight = cot_df[(cot_df['التاريخ']>=sd)&(cot_df['التاريخ']<=ed) & (cot_df['نوع البالة']=='قطن خام')]['وزن البالة'].sum()
                        if cotton_weight > 0:
                            stats['النسبة %'] = ((stats['إجمالي الوزن']/cotton_weight)*100).round(2)
                    st.dataframe(stats, use_container_width=True)
                    tot_count = stats['عدد'].sum()
                    tot_weight = stats['إجمالي الوزن'].sum()
                    c1,c2,c3 = st.columns(3)
                    c1.metric("إجمالي البالات", f"{tot_count}")
                    c2.metric("إجمالي الوزن", f"{tot_weight:.1f} كجم")
                    c3.metric("متوسط الوزن", f"{tot_weight/tot_count:.1f}" if tot_count else "0")
                    # تصدير
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        stats.to_excel(writer, sheet_name='الإحصائيات', index=False)
                        filtered.to_excel(writer, sheet_name='التفاصيل', index=False)
                    st.download_button("تحميل Excel", data=buffer.getvalue(),
                                       file_name=f"تقرير_{sd}_{ed}.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
