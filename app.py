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
# ⚙ إعدادات التطبيق - يمكن تعديلها بسهولة
# ===============================
APP_CONFIG = {
    # إعدادات التطبيق العامة
    "APP_TITLE": "CMMS - Bail Yarn2",
    "APP_ICON": "🏭",
    
    # إعدادات GitHub
    "REPO_NAME": "mahmedabdallh123/belyarn2",  # غيّر هذا لريبو الجديد
    "BRANCH": "main",
    "FILE_PATH": "bel2.xlsx",  # غيّر هذا لملف Excel الجديد
    "LOCAL_FILE": "bel2.xlsx",  # غيّر هذا للملف المحلي الجديد
    
    # إعدادات الأمان
    "MAX_ACTIVE_USERS": 2,
    "SESSION_DURATION_MINUTES": 15,
    
    # إعدادات الواجهة
    "SHOW_TECH_SUPPORT_TO_ALL": False,  # True = الكل يشوف الدعم الفني, False = فقط admin
    "CUSTOM_TABS": ["📊 عرض وفحص الماكينات", "🛠 تعديل وإدارة البيانات", "👥 إدارة المستخدمين", "📞 الدعم الفني"]
}

# ===============================
# 🗂 إعدادات الملفات (لا تحتاج للتعديل)
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
        # انشئ ملف افتراضي اذا مش موجود (يوجد admin بكلمة مرور افتراضية "admin" — غيرها فورًا)
        default = {"admin": {"password": "admin", "role": "admin", "created_at": datetime.now().isoformat()}}
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
        return default
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"❌ خطأ في ملف users.json: {e}")
        return {"admin": {"password": "admin", "role": "admin", "created_at": datetime.now().isoformat()}}

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
    # احذف متغيرات الجلسة
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

    st.title(f"{APP_CONFIG['APP_ICON']} تسجيل الدخول - {APP_CONFIG['APP_TITLE']}")

    # اختيار المستخدم
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
                st.success(f"✅ تم تسجيل الدخول: {username_input}")
                st.rerun()
            else:
                st.error("❌ كلمة المرور غير صحيحة.")
        return False
    else:
        username = st.session_state.username
        st.success(f"✅ مسجل الدخول كـ: {username}")
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
        # امسح الكاش
        try:
            st.cache_data.clear()
        except:
            pass
        return True
    except Exception as e:
        st.error(f"⚠ فشل التحديث من GitHub: {e}")
        return False

def fetch_from_github_api():
    """تحميل عبر GitHub API (باستخدام PyGithub token في secrets)"""
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
# 📂 تحميل الشيتات (مخبأ) - معدل لقراءة جميع الشيتات
# -------------------------------
@st.cache_data(show_spinner=False)
def load_all_sheets():
    """تحميل جميع الشيتات من ملف Excel"""
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return None
    
    try:
        # قراءة جميع الشيتات
        sheets = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=None)
        
        if not sheets:
            return None
        
        # تنظيف أسماء الأعمدة لكل شيت
        for name, df in sheets.items():
            df.columns = df.columns.astype(str).str.strip()
        
        return sheets
    except Exception as e:
        return None

# نسخة مع dtype=object لواجهة التحرير
@st.cache_data(show_spinner=False)
def load_sheets_for_edit():
    """تحميل جميع الشيتات للتحرير"""
    if not os.path.exists(APP_CONFIG["LOCAL_FILE"]):
        return None
    
    try:
        # قراءة جميع الشيتات مع dtype=object للحفاظ على تنسيق البيانات
        sheets = pd.read_excel(APP_CONFIG["LOCAL_FILE"], sheet_name=None, dtype=object)
        
        if not sheets:
            return None
        
        # تنظيف أسماء الأعمدة لكل شيت
        for name, df in sheets.items():
            df.columns = df.columns.astype(str).str.strip()
        
        return sheets
    except Exception as e:
        return None

# -------------------------------
# 🔁 حفظ محلي + رفع على GitHub + مسح الكاش + إعادة تحميل
# -------------------------------
def save_local_excel_and_push(sheets_dict, commit_message="Update from Streamlit"):
    """دالة محسنة للحفظ التلقائي المحلي والرفع إلى GitHub"""
    # احفظ محلياً
    try:
        with pd.ExcelWriter(APP_CONFIG["LOCAL_FILE"], engine="openpyxl") as writer:
            for name, sh in sheets_dict.items():
                try:
                    sh.to_excel(writer, sheet_name=name, index=False)
                except Exception:
                    sh.astype(object).to_excel(writer, sheet_name=name, index=False)
    except Exception as e:
        st.error(f"⚠ خطأ أثناء الحفظ المحلي: {e}")
        return None

    # امسح الكاش
    try:
        st.cache_data.clear()
    except:
        pass

    # حاول الرفع عبر PyGithub token في secrets
    token = st.secrets.get("github", {}).get("token", None)
    if not token:
        st.warning("⚠ لم يتم العثور على GitHub token. سيتم الحفظ محلياً فقط.")
        return load_sheets_for_edit()

    if not GITHUB_AVAILABLE:
        st.warning("⚠ PyGithub غير متوفر. سيتم الحفظ محلياً فقط.")
        return load_sheets_for_edit()

    try:
        g = Github(token)
        repo = g.get_repo(APP_CONFIG["REPO_NAME"])
        with open(APP_CONFIG["LOCAL_FILE"], "rb") as f:
            content = f.read()

        try:
            contents = repo.get_contents(APP_CONFIG["FILE_PATH"], ref=APP_CONFIG["BRANCH"])
            result = repo.update_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, sha=contents.sha, branch=APP_CONFIG["BRANCH"])
            st.success(f"✅ تم الحفظ والرفع إلى GitHub بنجاح: {commit_message}")
            return load_sheets_for_edit()
        except Exception as e:
            # حاول رفع كملف جديد أو إنشاء
            try:
                result = repo.create_file(path=APP_CONFIG["FILE_PATH"], message=commit_message, content=content, branch=APP_CONFIG["BRANCH"])
                st.success(f"✅ تم إنشاء ملف جديد على GitHub: {commit_message}")
                return load_sheets_for_edit()
            except Exception as create_error:
                st.error(f"❌ فشل إنشاء ملف جديد على GitHub: {create_error}")
                return None

    except Exception as e:
        st.error(f"❌ فشل الرفع إلى GitHub: {e}")
        return None

def auto_save_to_github(sheets_dict, operation_description):
    """دالة الحفظ التلقائي المحسنة"""
    username = st.session_state.get("username", "unknown")
    commit_message = f"{operation_description} by {username} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    result = save_local_excel_and_push(sheets_dict, commit_message)
    if result is not None:
        st.success("✅ تم حفظ التغييرات تلقائياً في GitHub")
        return result
    else:
        st.error("❌ فشل الحفظ التلقائي")
        return sheets_dict

# -------------------------------
# 🧰 دوال مساعدة للمعالجة والنصوص
# -------------------------------
def normalize_name(s):
    if s is None: return ""
    s = str(s).replace("\n", "+")
    s = re.sub(r"[^0-9a-zA-Z\u0600-\u06FF\+\s_/.-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def split_needed_services(needed_service_str):
    if not isinstance(needed_service_str, str) or needed_service_str.strip() == "":
        return []
    parts = re.split(r"\+|,|\n|;", needed_service_str)
    return [p.strip() for p in parts if p.strip() != ""]

def highlight_cell(val, col_name):
    color_map = {
        "Service Needed": "background-color: #fff3cd; color:#856404; font-weight:bold;",
        "Service Done": "background-color: #d4edda; color:#155724; font-weight:bold;",
        "Service Didn't Done": "background-color: #f8d7da; color:#721c24; font-weight:bold;",
        "Date": "background-color: #e7f1ff; color:#004085; font-weight:bold;",
        "Tones": "background-color: #e8f8f5; color:#0d5c4a; font-weight:bold;",
        "Min_Tons": "background-color: #ebf5fb; color:#154360; font-weight:bold;",
        "Max_Tons": "background-color: #f9ebea; color:#641e16; font-weight:bold;",
        "Event": "background-color: #e2f0d9; color:#2e6f32; font-weight:bold;",
        "Correction": "background-color: #fdebd0; color:#7d6608; font-weight:bold;",
        "Servised by": "background-color: #f0f0f0; color:#333; font-weight:bold;",
        "Card Number": "background-color: #ebdef0; color:#4a235a; font-weight:bold;"
    }
    return color_map.get(col_name, "")

def style_table(row):
    return [highlight_cell(row[col], col) for col in row.index]

# -------------------------------
# 🖥 دالة فحص الماكينة
# -------------------------------
def check_machine_status(card_num, current_tons, all_sheets):
    if not all_sheets:
        st.error("❌ لم يتم تحميل أي شيتات.")
        return
    
    if "ServicePlan" not in all_sheets:
        st.error("❌ الملف لا يحتوي على شيت ServicePlan.")
        return
    
    service_plan_df = all_sheets["ServicePlan"]
    card_sheet_name = f"Card{card_num}"
    
    if card_sheet_name not in all_sheets:
        st.warning(f"⚠ لا يوجد شيت باسم {card_sheet_name}")
        return
    
    card_df = all_sheets[card_sheet_name]

    # نطاق العرض
    if "view_option" not in st.session_state:
        st.session_state.view_option = "الشريحة الحالية فقط"

    st.subheader("⚙ نطاق العرض")
    view_option = st.radio(
        "اختر نطاق العرض:",
        ("الشريحة الحالية فقط", "كل الشرائح الأقل", "كل الشرائح الأعلى", "نطاق مخصص", "كل الشرائح"),
        horizontal=True,
        key="view_option"
    )

    min_range = st.session_state.get("min_range", max(0, current_tons - 500))
    max_range = st.session_state.get("max_range", current_tons + 500)
    if view_option == "نطاق مخصص":
        col1, col2 = st.columns(2)
        with col1:
            min_range = st.number_input("من (طن):", min_value=0, step=100, value=min_range, key="min_range")
        with col2:
            max_range = st.number_input("إلى (طن):", min_value=min_range, step=100, value=max_range, key="max_range")

    # اختيار الشرائح
    if view_option == "الشريحة الحالية فقط":
        selected_slices = service_plan_df[(service_plan_df["Min_Tones"] <= current_tons) & (service_plan_df["Max_Tones"] >= current_tons)]
    elif view_option == "كل الشرائح الأقل":
        selected_slices = service_plan_df[service_plan_df["Max_Tones"] <= current_tons]
    elif view_option == "كل الشرائح الأعلى":
        selected_slices = service_plan_df[service_plan_df["Min_Tones"] >= current_tons]
    elif view_option == "نطاق مخصص":
        selected_slices = service_plan_df[(service_plan_df["Min_Tones"] >= min_range) & (service_plan_df["Max_Tones"] <= max_range)]
    else:
        selected_slices = service_plan_df.copy()

    if selected_slices.empty:
        st.warning("⚠ لا توجد شرائح مطابقة حسب النطاق المحدد.")
        return

    all_results = []
    for _, current_slice in selected_slices.iterrows():
        slice_min = current_slice["Min_Tones"]
        slice_max = current_slice["Max_Tones"]
        needed_service_raw = current_slice.get("Service", "")
        needed_parts = split_needed_services(needed_service_raw)
        needed_norm = [normalize_name(p) for p in needed_parts]

        mask = (card_df.get("Min_Tones", 0).fillna(0) <= slice_max) & (card_df.get("Max_Tones", 0).fillna(0) >= slice_min)
        matching_rows = card_df[mask]

        if not matching_rows.empty:
            for _, row in matching_rows.iterrows():
                done_services_set = set()
                
                # تحديد الأعمدة التي تحتوي على خدمات منجزة
                metadata_columns = {
                    "card", "Tones", "Min_Tones", "Max_Tones", "Date", 
                    "Other", "Servised by", "Event", "Correction",
                    "Card", "TONES", "MIN_TONES", "MAX_TONES", "DATE",
                    "OTHER", "EVENT", "CORRECTION", "SERVISED BY",
                    "servised by", "Servised By", 
                    "Serviced by", "Service by", "Serviced By", "Service By",
                    "خدم بواسطة", "تم الخدمة بواسطة", "فني الخدمة"
                }
                
                all_columns = set(card_df.columns)
                service_columns = all_columns - metadata_columns
                
                final_service_columns = set()
                for col in service_columns:
                    col_normalized = normalize_name(col)
                    metadata_normalized = {normalize_name(mc) for mc in metadata_columns}
                    if col_normalized not in metadata_normalized:
                        final_service_columns.add(col)
                
                for col in final_service_columns:
                    val = str(row.get(col, "")).strip()
                    if val and val.lower() not in ["nan", "none", "", "null", "0"]:
                        if val.lower() not in ["no", "false", "not done", "لم تتم", "x", "-"]:
                            done_services_set.add(col)

                # جمع بيانات الحدث
                current_date = str(row.get("Date", "")).strip() if pd.notna(row.get("Date")) else "-"
                current_tones = str(row.get("Tones", "")).strip() if pd.notna(row.get("Tones")) else "-"
                current_other = str(row.get("Other", "")).strip() if pd.notna(row.get("Other")) else "-"
                
                # البحث عن عمود "Servised by"
                servised_by_value = "-"
                servised_by_columns = [
                    "Servised by", "SERVISED BY", "servised by", "Servised By",
                    "Serviced by", "Service by", "Serviced By", "Service By",
                    "خدم بواسطة", "تم الخدمة بواسطة", "فني الخدمة"
                ]
                
                for potential_col in servised_by_columns:
                    if potential_col in card_df.columns:
                        value = row.get(potential_col)
                        if pd.notna(value) and str(value).strip() != "":
                            servised_by_value = str(value).strip()
                            break
                
                if servised_by_value == "-":
                    for col in card_df.columns:
                        col_normalized = normalize_name(col)
                        if col_normalized in ["servisedby", "servicedby", "serviceby", "خدمبواسطة"]:
                            value = row.get(col)
                            if pd.notna(value) and str(value).strip() != "":
                                servised_by_value = str(value).strip()
                                break

                current_event = str(row.get("Event", "")).strip() if pd.notna(row.get("Event")) else "-"
                current_correction = str(row.get("Correction", "")).strip() if pd.notna(row.get("Correction")) else "-"

                done_services = sorted(list(done_services_set))
                done_norm = [normalize_name(c) for c in done_services]
                
                # مقارنة الخدمات المنجزة مع المطلوبة
                not_done = []
                for needed_part, needed_norm_part in zip(needed_parts, needed_norm):
                    if needed_norm_part not in done_norm:
                        not_done.append(needed_part)

                all_results.append({
                    "Card Number": card_num,
                    "Min_Tons": slice_min,
                    "Max_Tons": slice_max,
                    "Service Needed": " + ".join(needed_parts) if needed_parts else "-",
                    "Service Done": ", ".join(done_services) if done_services else "-",
                    "Service Didn't Done": ", ".join(not_done) if not_done else "-",
                    "Tones": current_tones,
                    "Event": current_event,
                    "Correction": current_correction,
                    "Servised by": servised_by_value,
                    "Date": current_date
                })
        else:
            # إذا لم توجد أحداث، نضيف سجل للشريحة بدون خدمات منجزة
            all_results.append({
                "Card Number": card_num,
                "Min_Tons": slice_min,
                "Max_Tons": slice_max,
                "Service Needed": " + ".join(needed_parts) if needed_parts else "-",
                "Service Done": "-",
                "Service Didn't Done": ", ".join(needed_parts) if needed_parts else "-",
                "Tones": "-",
                "Event": "-",
                "Correction": "-",
                "Servised by": "-",
                "Date": "-"
            })

    result_df = pd.DataFrame(all_results).dropna(how="all").reset_index(drop=True)

    st.markdown("### 📋 نتائج الفحص - جميع الأحداث")
    st.dataframe(result_df.style.apply(style_table, axis=1), use_container_width=True)

    # تنزيل النتائج
    buffer = io.BytesIO()
    result_df.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(
        label="💾 حفظ النتائج كـ Excel",
        data=buffer.getvalue(),
        file_name=f"Service_Report_Card{card_num}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# -------------------------------
# 🖥 الواجهة الرئيسية المدمجة
# -------------------------------
# إعداد الصفحة
st.set_page_config(page_title=APP_CONFIG["APP_TITLE"], layout="wide")

# شريط تسجيل الدخول / معلومات الجلسة في الشريط الجانبي
with st.sidebar:
    st.header("👤 الجلسة")
    if not st.session_state.get("logged_in"):
        if not login_ui():
            st.stop()
    else:
        state = cleanup_sessions(load_state())
        username = st.session_state.username
        rem = remaining_time(state, username)
        if rem:
            mins, secs = divmod(int(rem.total_seconds()), 60)
            st.success(f"👋 {username} | ⏳ {mins:02d}:{secs:02d}")
        else:
            logout_action()

    st.markdown("---")
    st.write("🔧 أدوات:")
    if st.button("🔄 تحديث الملف من GitHub"):
        if fetch_from_github_requests():
            st.rerun()
    
    # زر مسح الكاش
    if st.button("🗑 مسح الكاش"):
        try:
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"❌ خطأ في مسح الكاش: {e}")
    
    st.markdown("---")
    # زر لإعادة تسجيل الخروج
    if st.button("🚪 تسجيل الخروج"):
        logout_action()

# تحميل الشيتات (عرض وتحليل)
all_sheets = load_all_sheets()

# تحميل الشيتات للتحرير (dtype=object)
sheets_edit = load_sheets_for_edit()

# واجهة التبويبات الرئيسية
st.title(f"{APP_CONFIG['APP_ICON']} {APP_CONFIG['APP_TITLE']}")

# التحقق من الصلاحيات لعرض التبويبات المناسبة
username = st.session_state.get("username")
is_admin = username == "admin"

# تحديد التبويبات بناءً على نوع المستخدم والإعدادات
if is_admin:
    tabs = st.tabs(APP_CONFIG["CUSTOM_TABS"])
else:
    # للمستخدمين العاديين: نعرض تبويب العرض فقط، وإضافة الدعم الفني إذا كان مسموحاً
    regular_tabs = ["📊 عرض وفحص الماكينات"]
    if APP_CONFIG["SHOW_TECH_SUPPORT_TO_ALL"]:
        regular_tabs.append("📞 الدعم الفني")
    tabs = st.tabs(regular_tabs)

# -------------------------------
# Tab: عرض وفحص الماكينات
# -------------------------------
with tabs[0]:
    st.header("📊 عرض وفحص الماكينات")
    
    if all_sheets is None:
        st.warning("❗ الملف المحلي غير موجود. استخدم زر التحديث في الشريط الجانبي لتحميل الملف من GitHub.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            card_num = st.number_input("رقم الماكينة:", min_value=1, step=1, key="card_num_main")
        with col2:
            current_tons = st.number_input("عدد الأطنان الحالية:", min_value=0, step=100, key="current_tons_main")

        if st.button("عرض الحالة"):
            st.session_state["show_results"] = True

        if st.session_state.get("show_results", False):
            check_machine_status(card_num, current_tons, all_sheets)

# -------------------------------
# Tab: تعديل وإدارة البيانات - للمسؤول فقط
# -------------------------------
if is_admin and len(tabs) > 1:
    with tabs[1]:
        st.header("🛠 تعديل وإدارة البيانات")

        # تحقق صلاحية الرفع
        token_exists = bool(st.secrets.get("github", {}).get("token", None))
        can_push = token_exists and GITHUB_AVAILABLE

        if sheets_edit is None:
            st.warning("❗ الملف المحلي غير موجود. اضغط تحديث من GitHub في الشريط الجانبي أولًا.")
        else:
            tab1, tab2, tab3, tab4 = st.tabs([
                "عرض وتعديل شيت",
                "إضافة صف جديد", 
                "إضافة عمود جديد",
                "🗑 حذف صف"
            ])

            # -------------------------------
            # Tab 1: تعديل بيانات وعرض - معدل للحفظ التلقائي
            # -------------------------------
            with tab1:
                st.subheader("✏ تعديل البيانات")
                sheet_name = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="edit_sheet")
                df = sheets_edit[sheet_name].astype(str)

                # استخدام data_editor مع التعديل التلقائي
                edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, 
                                         key=f"editor_{sheet_name}")
                
                # حفظ تلقائي عند التعديل
                if not edited_df.equals(df):
                    st.info("🔄 يتم حفظ التغييرات تلقائياً...")
                    sheets_edit[sheet_name] = edited_df.astype(object)
                    new_sheets = auto_save_to_github(
                        sheets_edit, 
                        f"تعديل تلقائي في شيت {sheet_name}"
                    )
                    if new_sheets is not None:
                        sheets_edit = new_sheets
                        st.rerun()

            # -------------------------------
            # Tab 2: إضافة صف جديد - معدل للحفظ التلقائي
            # -------------------------------
            with tab2:
                st.subheader("➕ إضافة صف جديد")
                sheet_name_add = st.selectbox("اختر الشيت لإضافة صف:", list(sheets_edit.keys()), key="add_sheet")
                df_add = sheets_edit[sheet_name_add].astype(str).reset_index(drop=True)
                
                st.markdown("أدخل بيانات الحدث:")

                new_data = {}
                cols = st.columns(3)
                for i, col in enumerate(df_add.columns):
                    with cols[i % 3]:
                        new_data[col] = st.text_input(f"{col}", key=f"add_{sheet_name_add}_{col}")

                if st.button("💾 إضافة الصف الجديد", key=f"add_row_{sheet_name_add}"):
                    new_row_df = pd.DataFrame([new_data]).astype(str)

                    # البحث عن أعمدة الرينج
                    min_col, max_col, card_col = None, None, None
                    for c in df_add.columns:
                        c_low = c.strip().lower()
                        if c_low in ("min_tones", "min_tone", "min tones", "min"):
                            min_col = c
                        if c_low in ("max_tones", "max_tone", "max tones", "max"):
                            max_col = c
                        if c_low in ("card", "machine", "machine_no", "machine id"):
                            card_col = c

                    if not min_col or not max_col:
                        st.error("⚠ لم يتم العثور على أعمدة Min_Tones و/أو Max_Tones في الشيت.")
                    else:
                        def to_num_or_none(x):
                            try:
                                return float(x)
                            except:
                                return None

                        new_min_raw = str(new_data.get(min_col, "")).strip()
                        new_max_raw = str(new_data.get(max_col, "")).strip()
                        new_min_num = to_num_or_none(new_min_raw)
                        new_max_num = to_num_or_none(new_max_raw)

                        # البحث عن موضع الإدراج
                        insert_pos = len(df_add)
                        mask = pd.Series([False] * len(df_add))

                        if card_col:
                            new_card = str(new_data.get(card_col, "")).strip()
                            if new_card != "":
                                if new_min_num is not None and new_max_num is not None:
                                    mask = (
                                        (df_add[card_col].astype(str).str.strip() == new_card) &
                                        (pd.to_numeric(df_add[min_col], errors='coerce') == new_min_num) &
                                        (pd.to_numeric(df_add[max_col], errors='coerce') == new_max_num)
                                    )
                                else:
                                    mask = (
                                        (df_add[card_col].astype(str).str.strip() == new_card) &
                                        (df_add[min_col].astype(str).str.strip() == new_min_raw) &
                                        (df_add[max_col].astype(str).str.strip() == new_max_raw)
                                    )
                        else:
                            if new_min_num is not None and new_max_num is not None:
                                mask = (
                                    (pd.to_numeric(df_add[min_col], errors='coerce') == new_min_num) &
                                    (pd.to_numeric(df_add[max_col], errors='coerce') == new_max_num)
                                )
                            else:
                                mask = (
                                    (df_add[min_col].astype(str).str.strip() == new_min_raw) &
                                    (df_add[max_col].astype(str).str.strip() == new_max_raw)
                                )

                        if mask.any():
                            insert_pos = mask[mask].index[-1] + 1
                        else:
                            try:
                                df_add["_min_num"] = pd.to_numeric(df_add[min_col], errors='coerce').fillna(-1)
                                if new_min_num is not None:
                                    insert_pos = int((df_add["_min_num"] < new_min_num).sum())
                                else:
                                    insert_pos = len(df_add)
                                df_add = df_add.drop(columns=["_min_num"])
                            except Exception:
                                insert_pos = len(df_add)

                        df_top = df_add.iloc[:insert_pos].reset_index(drop=True)
                        df_bottom = df_add.iloc[insert_pos:].reset_index(drop=True)
                        df_new = pd.concat(
                            [df_top, new_row_df.reset_index(drop=True), df_bottom],
                            ignore_index=True
                        )

                        sheets_edit[sheet_name_add] = df_new.astype(object)

                        # حفظ تلقائي في GitHub
                        new_sheets = auto_save_to_github(
                            sheets_edit,
                            f"إضافة صف جديد في {sheet_name_add} بالرينج {new_min_raw}-{new_max_raw}"
                        )
                        if new_sheets is not None:
                            sheets_edit = new_sheets
                            st.rerun()

            # -------------------------------
            # Tab 3: إضافة عمود جديد - معدل للحفظ التلقائي
            # -------------------------------
            with tab3:
                st.subheader("🆕 إضافة عمود جديد")
                sheet_name_col = st.selectbox("اختر الشيت لإضافة عمود:", list(sheets_edit.keys()), key="add_col_sheet")
                df_col = sheets_edit[sheet_name_col].astype(str)
                
                new_col_name = st.text_input("اسم العمود الجديد:")
                default_value = st.text_input("القيمة الافتراضية لكل الصفوف (اختياري):", "")

                if st.button("💾 إضافة العمود الجديد", key=f"add_col_{sheet_name_col}"):
                    if new_col_name:
                        df_col[new_col_name] = default_value
                        sheets_edit[sheet_name_col] = df_col.astype(object)
                        
                        # حفظ تلقائي في GitHub
                        new_sheets = auto_save_to_github(
                            sheets_edit,
                            f"إضافة عمود جديد '{new_col_name}' إلى {sheet_name_col}"
                        )
                        if new_sheets is not None:
                            sheets_edit = new_sheets
                            st.rerun()
                    else:
                        st.warning("⚠ الرجاء إدخال اسم العمود الجديد.")

            # -------------------------------
            # Tab 4: حذف صف - معدل للحفظ التلقائي
            # -------------------------------
            with tab4:
                st.subheader("🗑 حذف صف من الشيت")
                sheet_name_del = st.selectbox("اختر الشيت:", list(sheets_edit.keys()), key="delete_sheet")
                df_del = sheets_edit[sheet_name_del].astype(str).reset_index(drop=True)

                st.markdown("### 📋 بيانات الشيت الحالية")
                st.dataframe(df_del, use_container_width=True)

                st.markdown("### ✏ اختر الصفوف التي تريد حذفها")
                rows_to_delete = st.text_input("أدخل أرقام الصفوف مفصولة بفاصلة (مثلاً: 0,2,5):")
                confirm_delete = st.checkbox("✅ أؤكد أني أريد حذف هذه الصفوف بشكل نهائي")

                if st.button("🗑 تنفيذ الحذف", key=f"delete_rows_{sheet_name_del}"):
                    if not rows_to_delete.strip():
                        st.warning("⚠ الرجاء إدخال رقم الصف أو أكثر.")
                    elif not confirm_delete:
                        st.warning("⚠ برجاء تأكيد الحذف أولاً.")
                    else:
                        try:
                            rows_list = [int(x.strip()) for x in rows_to_delete.split(",") if x.strip().isdigit()]
                            rows_list = [r for r in rows_list if 0 <= r < len(df_del)]

                            if not rows_list:
                                st.warning("⚠ لم يتم العثور على صفوف صحيحة.")
                            else:
                                df_new = df_del.drop(rows_list).reset_index(drop=True)
                                sheets_edit[sheet_name_del] = df_new.astype(object)

                                # حفظ تلقائي في GitHub
                                new_sheets = auto_save_to_github(
                                    sheets_edit, 
                                    f"حذف الصفوف {rows_list} من {sheet_name_del}"
                                )
                                if new_sheets is not None:
                                    sheets_edit = new_sheets
                                    st.rerun()
                        except Exception as e:
                            st.error(f"حدث خطأ أثناء الحذف: {e}")

# -------------------------------
# Tab: إدارة المستخدمين - للمسؤول فقط
# -------------------------------
if is_admin and len(tabs) > 2:
    with tabs[2]:
        st.header("👥 إدارة المستخدمين")
        
        users = load_users()
        
        # عرض المستخدمين الحاليين
        st.subheader("📋 المستخدمين الحاليين")
        
        if users:
            # تحويل بيانات المستخدمين إلى DataFrame لعرضها
            user_data = []
            for username, info in users.items():
                user_data.append({
                    "اسم المستخدم": username,
                    "الدور": info.get("role", "user"),
                    "تاريخ الإنشاء": info.get("created_at", "غير معروف")
                })
            
            users_df = pd.DataFrame(user_data)
            st.dataframe(users_df, use_container_width=True)
        else:
            st.info("لا يوجد مستخدمين مسجلين بعد.")
        
        # إضافة مستخدم جديد
        st.subheader("➕ إضافة مستخدم جديد")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            new_username = st.text_input("اسم المستخدم الجديد:")
        with col2:
            new_password = st.text_input("كلمة المرور:", type="password")
        with col3:
            user_role = st.selectbox("الدور:", ["user", "admin"])
        
        if st.button("إضافة مستخدم", key="add_user"):
            if not new_username.strip() or not new_password.strip():
                st.warning("⚠ الرجاء إدخال اسم المستخدم وكلمة المرور.")
            elif new_username in users:
                st.warning("⚠ هذا المستخدم موجود بالفعل.")
            else:
                users[new_username] = {
                    "password": new_password,
                    "role": user_role,
                    "created_at": datetime.now().isoformat()
                }
                if save_users(users):
                    st.success(f"✅ تم إضافة المستخدم '{new_username}' بنجاح.")
                    st.rerun()
                else:
                    st.error("❌ حدث خطأ أثناء حفظ بيانات المستخدم.")
        
        # حذف مستخدم
        st.subheader("🗑 حذف مستخدم")
        
        if len(users) > 1:  # لا يمكن حذف جميع المستخدمين
            user_to_delete = st.selectbox(
                "اختر مستخدم للحذف:",
                [u for u in users.keys() if u != "admin"],  # لا يمكن حذف admin
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
        else:
            st.info("لا يمكن حذف جميع المستخدمين. يجب أن يبقى مستخدم واحد على الأقل.")
        
        # إعادة تعيين كلمة المرور
        st.subheader("🔑 إعادة تعيين كلمة المرور")
        
        if len(users) > 0:
            user_to_reset = st.selectbox(
                "اختر مستخدم لإعادة تعيين كلمة المرور:",
                list(users.keys()),
                key="reset_user_select"
            )
            
            new_password_reset = st.text_input("كلمة المرور الجديدة:", type="password", key="new_password_reset")
            
            if st.button("إعادة تعيين كلمة المرور", key="reset_password_btn"):
                if not new_password_reset.strip():
                    st.warning("⚠ الرجاء إدخال كلمة المرور الجديدة.")
                else:
                    users[user_to_reset]["password"] = new_password_reset
                    if save_users(users):
                        st.success(f"✅ تم إعادة تعيين كلمة المرور للمستخدم '{user_to_reset}' بنجاح.")
                        st.rerun()
                    else:
                        st.error("❌ حدث خطأ أثناء حفظ التغييرات.")



