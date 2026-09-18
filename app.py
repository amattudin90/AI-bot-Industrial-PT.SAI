import os
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.config import *
from core.data_engine import FactoryData
from core.ai_engine import AIEngine
from core.database import add_message, get_history, log_activity, recent_activity

st.set_page_config(page_title=f"{SYSTEM_NAME} {APP_VERSION}", page_icon="🏭", layout="wide")

# Custom Styling Dashboard Visual Management
st.markdown("""
<style>
section[data-testid="stSidebar"] {border-right:1px solid #232a3b;}
div[data-testid="stMetric"] {background:#141a26;border:1px solid #232a3b;border-radius:10px;padding:10px 14px;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_ai():
    return AIEngine()

ai = get_ai()

# ================= SIDEBAR =================
st.sidebar.title("🏭 Factory AI")
st.sidebar.caption(f"{SYSTEM_NAME} · {APP_VERSION}")
st.sidebar.divider()

st.sidebar.subheader("⚙️ Operational Parameters")
gross_hours = st.sidebar.number_input("Working hours/day", 1.0, 24.0, 10.0, .5)
working_days = st.sidebar.number_input("Working days/month", 1.0, 31.0, 22.5, .5)
downtime = st.sidebar.number_input("Downtime (%)", 0.0, 50.0, 15.0, .5)
allowance = st.sidebar.number_input("Allowance (%)", 0.0, 50.0, 15.0, .5)

st.sidebar.divider()
st.sidebar.subheader("🧠 Knowledge Base Uploader")

# HANYA SATU FILE UPLOADER TUNGGAL
uploaded_file = st.sidebar.file_uploader(
    "Upload Excel Kapasitas (.xlsx, .xls)", 
    type=["xlsx", "xls"], 
    key="unique_kb_uploader_key",
    help="File yang di-upload otomatis tersimpan permanen ke memori riwayat AI."
)

history_dir = Path(DATA_DIR) / "history"
history_dir.mkdir(parents=True, exist_ok=True)

# Simpan file ke folder history jika ada file baru di-upload
if uploaded_file is not None:
    saved_path = history_dir / uploaded_file.name
    with open(saved_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    st.sidebar.success(f"🧠 Data '{uploaded_file.name}' tersimpan ke memori AI!")

# MEMUAT SELURUH DATA SISTEM & KNOWLEDGE BASE HISTORY
v1_default = Path(DATA_DIR) / V1_FILE
v2_default = Path(DATA_DIR) / V2_FILE
v1_path = str(v1_default) if v1_default.exists() else None
v2_path = str(v2_default) if v2_default.exists() else None

factory = FactoryData()
factory.load(v1_path, v2_path)

# Baca seluruh file dari folder history (termasuk Summary Capacity 15.09)
if history_dir.exists():
    factory.load_all_history(str(history_dir))

# TOMBOL CLEAR CHAT HISTORY
st.sidebar.divider()
if st.sidebar.button("🗑️ Clear Chat History", key="btn_clear_chat_history", use_container_width=True):
    st.session_state.web_messages = []
    st.rerun()

# ================= TOP VISUAL MANAGEMENT HEADER =================
m = factory.metrics()
shortage_count = m["shortage_rows"]
shortage_sections = m["shortage_sections"]
custom_sheets = m.get("custom_sheets_count", 0)

c1, c2, c3 = st.columns([1, 1, 2])

with c1:
    if shortage_count > 0:
        st.error(f"🚨 **CAPACITY ALERT**\n### {shortage_count} Shortage Detected")
    else:
        st.success("🟢 **CAPACITY STATUS**\n### Normal / Balanced")

with c2:
    if custom_sheets > 0:
        st.info(f"📊 **KNOWLEDGE BASE ACTIVE**\n### {custom_sheets} Memory Sheets Loaded")
    else:
        st.info("📁 **DATA SOURCE ACTIVE**\n### System Default Loaded")

with c3:
    st.markdown("**🎯 Section Health Alert**")
    if shortage_sections:
        st.warning(f"**Attention Required:** {', '.join(shortage_sections)}")
    else:
        st.caption("Semua section beroperasi dalam batas kapasitas aman.")

st.divider()

# ================= TABS NAVIGATION =================
tab1, tab2, tab3 = st.tabs(["🤖 AI COPILOT", "📊 CONTROL TOWER", "🧾 ACTIVITY LOG"])

with tab1:
    st.subheader("AI Operations Copilot")
    st.caption("Same core AI engine used by the Telegram agent.")

    if "web_messages" not in st.session_state:
        st.session_state.web_messages = get_history("streamlit", "local", 20)

    for msg in st.session_state.web_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    q = st.chat_input("Ask about capacity, machine planning, Kaizen, risk, or action plan...")
    if q:
        add_message("streamlit", "local", "user", q)
        st.session_state.web_messages.append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        
        with st.chat_message("assistant"):
            if not ai.active:
                answer = "AI Offline: GEMINI_API_KEY belum tersedia."
                st.error(answer)
            else:
                with st.spinner("Factory AI sedang menganalisis..."):
                    try:
                        history = get_history("streamlit", "local", 8)
                        answer = ai.ask(
                            q, factory.compact_context(),
                            history,
                            {"gross_hours": gross_hours, "working_days": working_days,
                             "downtime": downtime, "allowance": allowance}
                        )
                        st.markdown(answer)
                    except Exception as exc:
                        answer = f"AI Error: {exc}"
                        st.error(answer)
            
            add_message("streamlit", "local", "assistant", answer)
            st.session_state.web_messages.append({"role": "assistant", "content": answer})
            log_activity("streamlit", "local", "AI_QUERY", "SUCCESS", q)

with tab2:
    if factory.custom_sheets:
        st.subheader("📑 Knowledge Base Sheets (History Memory)")
        for sheet_name, df in factory.custom_sheets.items():
            with st.expander(f"📄 Sheet: {sheet_name} ({len(df)} rows)", expanded=False):
                st.dataframe(df.head(50), use_container_width=True)

    st.subheader("V2 Control Tower Summary")
    if factory.v2_sum is not None:
        st.dataframe(factory.v2_sum, use_container_width=True, hide_index=True)
    else:
        st.info("Data Control Tower baku belum dimuat.")

    st.subheader("V1 Baseline Overview")
    if factory.v1:
        st.dataframe(
            [{"Process/Sheet": k, "Total Rows": len(v), "Total Cols": len(v.columns)} for k, v in factory.v1.items()],
            use_container_width=True, hide_index=True
        )

with tab3:
    st.subheader("System Activity Log")
    rows = recent_activity(50)
    if rows:
        st.dataframe(
            [{"Channel": r[0], "User": r[1], "Action": r[2], "Status": r[3], "Detail": r[4], "Time": r[5]} for r in rows],
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Belum ada catatan aktivitas.")