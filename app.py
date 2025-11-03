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
    "REPO_NAME": "mahmedabdallh123/COTTON_PRESS",  # غيّر هذا لريبو الجديد
    "BRANCH": "main",
    "FILE_PATH": "Cotton_Press_Data.xlsx",  # ملف البيانات الجديد
    "LOCAL_FILE": "Cotton_Press_Data.xlsx",
    
    # إعدادات الأمان
    "MAX_ACTIVE_USERS": 5,
    "SESSION_DURATION_MINUTES": 30,
    
    # إعدادات الورديات
    "SHIFTS": {
        "أول": {"start": 8, "end": 16},
        "ثاني": {"start": 16, "end": 24},
        "ثالث": {"start": 0, "end": 8}
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
# 🧩 دوال مساعدة للملفات والحالة
# -------------------------------
def load_users():
    """تحميل بيانات المستخدمين من ملف JSON"""
    if not os.path.exists(USERS_FILE):
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
        # تعريف الأعمدة بناءً على الصورة المرفقة
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
        
        # امسح الكاش
        try:
            st.cache_data.clear()
        except:
            pass

        # حاول الرفع إلى GitHub
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
    return "ثالث"  # الوردية الثالثة من منتصف الليل إلى 8 صباحاً

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
    
    # تحويل التاريخ لسلسلة نصية للمقارنة
    df['التاريخ'] = pd.to_datetime(df['التاريخ']).dt.date
    
    # تصفية البيانات حسب الفترة
    mask = (df['التاريخ'] >= start_date) & (df['التاريخ'] <= end_date)
    filtered_df = df[mask]
    
    if filtered_df.empty:
        return pd.DataFrame()
    
    # إنشاء جدول إحصائي
    stats = filtered_df.groupby('نوع البالة').agg({
        'وزن البالة': ['count', 'sum', 'mean'],
        'المشرف': 'first'
    }).round(2)
    
    # إعادة تسمية الأعمدة
    stats.columns = ['عدد البالات', 'إجمالي الوزن', 'متوسط الوزن', 'المشرف']
    stats = stats.reset_index()
    
    return stats

# -------------------------------
# 🖥 الواجهة الرئيسية
# -------------------------------
# إعداد الصفحة
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
is_admin = username == "admin"

# تحديد التبويبات
if is_admin:
    tabs = st.tabs(APP_CONFIG["CUSTOM_TABS"])
else:
    tabs = st.tabs(["📥 إدخال البيانات", "📊 عرض الإحصائيات"])

# -------------------------------
# Tab 1: إدخال البيانات
# -------------------------------
with tabs[0]:
    st.header("📥 إدخال بيانات البالات")
    
    # معلومات الوردية الحالية
    current_shift = get_current_shift()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    st.info(f"*الوردية الحالية:* {current_shift} | *الوقت:* {current_time}")
    
    # نموذج إدخال البيانات
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
                
                # حفظ البيانات
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
with tabs[1]:
    st.header("📊 عرض الإحصائيات")
    
    if cotton_df.empty:
        st.warning("⚠ لا توجد بيانات لعرضها")
    else:
        # تحديد الفترة الزمنية
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("من تاريخ:", value=datetime.now().date() - timedelta(days=7))
        with col2:
            end_date = st.date_input("إلى تاريخ:", value=datetime.now().date())
        
        if st.button("🔄 تحديث الإحصائيات"):
            st.session_state["show_stats"] = True
        
        if st.session_state.get("show_stats", False):
            # توليد وعرض الإحصائيات
            stats_df = generate_statistics(cotton_df, start_date, end_date)
            
            if not stats_df.empty:
                st.subheader(f"📈 إحصائيات الفترة من {start_date} إلى {end_date}")
                
                # عرض جدول الإحصائيات
                st.dataframe(stats_df, use_container_width=True)
                
                # إجماليات عامة
                total_bales = stats_df['عدد البالات'].sum()
                total_weight = stats_df['إجمالي الوزن'].sum()
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("🔄 إجمالي عدد البالات", f"{total_bales:,}")
                with col2:
                    st.metric("⚖ إجمالي الوزن", f"{total_weight:,.1f} كجم")
                with col3:
                    st.metric("📊 متوسط الوزن للبالة", f"{(total_weight/total_bales):.1f} كجم")
                
                # عرض البيانات الخام
                st.subheader("📋 البيانات التفصيلية")
                filtered_data = cotton_df[
                    (pd.to_datetime(cotton_df['التاريخ']).dt.date >= start_date) & 
                    (pd.to_datetime(cotton_df['التاريخ']).dt.date <= end_date)
                ]
                st.dataframe(filtered_data, use_container_width=True)
                
                # خيارات التصدير
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

# -------------------------------
# Tab 3: إدارة المستخدمين (للمسؤول فقط)
# -------------------------------
if is_admin and len(tabs) > 2:
    with tabs[2]:
        st.header("👥 إدارة المستخدمين")
        
        users = load_users()
        
        # عرض المستخدمين الحاليين
        st.subheader("📋 المستخدمين الحاليين")
        
        if users:
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
# Tab 4: الدعم الفني
# -------------------------------
tech_support_tab_index = 3 if is_admin else 2
if len(tabs) > tech_support_tab_index:
    with tabs[tech_support_tab_index]:
        st.header("📞 الدعم الفني")
        
        st.markdown("## 🛠 معلومات التطوير والدعم")
        st.markdown("تم تطوير هذا التطبيق بواسطة:")
        st.markdown("### م. محمد عبدالله")
        st.markdown("### رئيس قسم الكرد والمحطات")
        st.markdown("### مصنع بيل يارن للغزل")
        st.markdown("---")
        st.markdown("### معلومات الاتصال:")
        st.markdown("- 📧 البريد الإلكتروني: m.abdallah@bailyarn.com")
        st.markdown("- 📞 هاتف المصنع: 01000000000")
        st.markdown("- 🏢 الموقع: مصنع بيل يارن للغزل")
        st.markdown("---")
        st.markdown("### خدمات الدعم الفني:")
        st.markdown("- 🔧 صيانة وتحديث النظام")
        st.markdown("- 📊 تطوير تقارير إضافية")
        st.markdown("- 🐛 إصلاح الأخطاء والمشكلات")
        st.markdown("- 💡 استشارات فنية وتقنية")
        st.markdown("---")
        st.markdown("### إصدار النظام:")
        st.markdown("- الإصدار: 1.0")
        st.markdown("- آخر تحديث: 2024")
        st.markdown("- النظام: نظام إدارة مكبس القطن")
        
        st.info("ملاحظة: في حالة مواجهة أي مشاكل تقنية أو تحتاج إلى إضافة ميزات جديدة، يرجى التواصل مع قسم الدعم الفني.")
