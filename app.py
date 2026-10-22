import os
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.config import *
from core.data_engine import FactoryData
from core.ai_engine import AIEngine
from core.database import add_message, clear_messages, get_history, log_activity, recent_activity

# ================= PAGE CONFIGURATION =================
st.set_page_config(
    page_title=f"{SYSTEM_NAME} - Control Tower & Copilot",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================= CUSTOM CSS (PROFESSIONAL INDUSTRIAL DARK UI) =================
st.markdown("""
<style>
    /* Global styles */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
    }
    
    /* Sidebar polish */
    section[data-testid="stSidebar"] {
        border-right: 1px solid #1e293b;
        background-color: #0b0f17;
    }
    
    /* Executive Metric Cards */
    .kpi-card {
        background: linear-gradient(135deg, #131b2e 0%, #0d1322 100%);
        border: 1px solid #22304d;
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
        margin-bottom: 10px;
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .kpi-card:hover {
        border-color: #38bdf8;
        transform: translateY(-2px);
    }
    .kpi-card-danger {
        border-left: 4px solid #ef4444;
    }
    .kpi-card-warning {
        border-left: 4px solid #f59e0b;
    }
    .kpi-card-success {
        border-left: 4px solid #10b981;
    }
    .kpi-card-info {
        border-left: 4px solid #38bdf8;
    }
    .kpi-card-purple {
        border-left: 4px solid #a855f7;
    }
    .kpi-title {
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-size: 1.55rem;
        font-weight: 800;
        color: #f8fafc;
        line-height: 1.2;
    }
    .kpi-caption {
        font-size: 0.78rem;
        color: #64748b;
        margin-top: 4px;
    }
    
    /* Alert Banner */
    .alert-banner {
        background: rgba(239, 68, 68, 0.12);
        border: 1px solid rgba(239, 68, 68, 0.4);
        border-radius: 8px;
        padding: 10px 16px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    /* Section Badge */
    .badge-chip {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 6px;
    }
    .badge-red {
        background-color: rgba(239, 68, 68, 0.2);
        color: #fca5a5;
        border: 1px solid rgba(239, 68, 68, 0.4);
    }
    .badge-green {
        background-color: rgba(16, 185, 129, 0.2);
        color: #6ee7b7;
        border: 1px solid rgba(16, 185, 129, 0.4);
    }
    .badge-blue {
        background-color: rgba(56, 189, 248, 0.2);
        color: #7dd3fc;
        border: 1px solid rgba(56, 189, 248, 0.4);
    }
    
    /* Tab formatting */
    button[data-baseweb="tab"] {
        font-weight: 600;
        font-size: 0.95rem;
        padding-top: 10px;
        padding-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ================= AI RESOURCE CACHE =================
@st.cache_resource
def get_ai():
    return AIEngine()

ai = get_ai()

# === Shared constants for Streamlit chat ===
CHAT_CHANNEL = "streamlit"
CHAT_USER = "local"

if "web_messages" not in st.session_state:
    st.session_state.web_messages = get_history(CHAT_CHANNEL, CHAT_USER, 20)

# ================= SIDEBAR =================
st.sidebar.markdown(f"## 🏭 {SYSTEM_NAME}")
st.sidebar.caption(f"🚀 Version: **{APP_VERSION}** · AI Operations Engine")
st.sidebar.divider()

st.sidebar.markdown("### ⚙️ Operational & IE Parameters")
gross_hours = st.sidebar.number_input("Working hours/day (Gross)", 1.0, 24.0, 10.0, 0.5,
                                      help="Total jam operasional harian sebelum pengurangan allowance dan downtime.")
working_days = st.sidebar.number_input("Working days/month", 1.0, 31.0, 22.5, 0.5,
                                       help="Jumlah hari kerja efektif per bulan.")
downtime = st.sidebar.number_input("Downtime (%)", 0.0, 50.0, 15.0, 0.5,
                                   help="Persentase estimasi kerugian waktu mesin/proses akibat downtime.")
allowance = st.sidebar.number_input("Allowance (%)", 0.0, 50.0, 15.0, 0.5,
                                    help="Persentase kelonggaran waktu pekerja (fatigue, personal needs, unavoidable delay).")

st.sidebar.divider()
st.sidebar.markdown("### 🧠 Knowledge Base Memory")

uploaded_file = st.sidebar.file_uploader(
    "Upload Excel Kapasitas (.xlsx, .xls)", 
    type=["xlsx", "xls"], 
    key="unique_kb_uploader_key",
    help="File yang di-upload otomatis tersimpan permanen ke memori riwayat AI."
)

history_dir = Path(DATA_DIR) / "history"
history_dir.mkdir(parents=True, exist_ok=True)

if uploaded_file is not None:
    upload_fingerprint = (uploaded_file.name, uploaded_file.size)
    if st.session_state.get("_last_kb_upload") != upload_fingerprint:
        saved_path = history_dir / uploaded_file.name
        with open(saved_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.session_state["_last_kb_upload"] = upload_fingerprint
        st.sidebar.success(f"🧠 Data '{uploaded_file.name}' tersimpan ke memori AI!")

# MEMUAT SELURUH DATA SISTEM & KNOWLEDGE BASE HISTORY
v1_default = Path(DATA_DIR) / V1_FILE
v2_default = Path(DATA_DIR) / V2_FILE
v1_path = str(v1_default) if v1_default.exists() else None
v2_path = str(v2_default) if v2_default.exists() else None

def _history_signature(directory: Path):
    if not directory.exists():
        return ()
    return tuple(
        (f.name, f.stat().st_mtime_ns)
        for f in sorted(directory.glob("*.xls*"))
    )

@st.cache_resource(show_spinner="📊 Memuat & parsing data Excel...")
def _load_factory_raw(v1_path, v2_path, history_sig):
    engine = FactoryData()
    engine.load(v1_path, v2_path)
    if history_dir.exists():
        engine.load_all_history(str(history_dir))
    return engine

history_sig = _history_signature(history_dir)
factory = _load_factory_raw(v1_path, v2_path, history_sig)

# Menghitung parameter perencanaan
factory.set_planning_parameters(
    gross_hours=gross_hours,
    working_days=working_days,
    downtime_pct=downtime,
    allowance_pct=allowance,
)
plan = factory.planning_capacity()

# Parameter calculation summary card in sidebar
eff_pct = (plan['net_hours_per_day'] / plan['gross_hours_per_day']) * 100 if plan['gross_hours_per_day'] > 0 else 0
st.sidebar.markdown(f"""
<div style="background:#131b2e; border:1px solid #1e293b; border-radius:8px; padding:10px 12px; margin-top:8px;">
    <div style="font-size:0.75rem; color:#94a3b8; font-weight:700;">IE NET CALCULATION</div>
    <div style="font-size:1.15rem; font-weight:800; color:#38bdf8;">{plan['net_hours_per_day']:.2f} hrs/day</div>
    <div style="font-size:0.75rem; color:#cbd5e1;">Available: <b>{plan['available_hours_per_month']:.1f} hrs/mo</b></div>
    <div style="font-size:0.72rem; color:#64748b; margin-top:4px;">Net Efficiency: <b>{eff_pct:.1f}%</b> of Gross</div>
</div>
""", unsafe_allow_html=True)

st.sidebar.divider()
if st.sidebar.button("🗑️ Clear Chat History", key="btn_clear_chat_history", use_container_width=True):
    try:
        clear_messages(CHAT_CHANNEL, CHAT_USER)
    except Exception:
        pass
    st.session_state.web_messages = []
    st.rerun()

# ================= TOP EXECUTIVE MANAGEMENT HEADER =================
m = factory.metrics()
shortage_count = m["shortage_rows"]
shortage_sections = m["shortage_sections"]
critical_min = m.get("critical_min")
custom_sheets = m.get("custom_sheets_count", 0)
v2_rows = m.get("v2_rows", 0)
week_cols = m.get("week_columns", [])

# Render 5 Professional KPI Cards
k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    if shortage_count > 0:
        st.markdown(f"""
        <div class="kpi-card kpi-card-danger">
            <div class="kpi-title">CAPACITY STATUS</div>
            <div class="kpi-value" style="color:#ef4444;">🚨 {shortage_count} DEFISIT</div>
            <div class="kpi-caption">Lini terdeteksi kekurangan kapasitas</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="kpi-card kpi-card-success">
            <div class="kpi-title">CAPACITY STATUS</div>
            <div class="kpi-value" style="color:#10b981;">🟢 BALANCED</div>
            <div class="kpi-caption">Semua lini dalam batas aman</div>
        </div>
        """, unsafe_allow_html=True)

with k2:
    if critical_min is not None and critical_min < 0:
        st.markdown(f"""
        <div class="kpi-card kpi-card-danger">
            <div class="kpi-title">PEAK DEFICIT</div>
            <div class="kpi-value" style="color:#f87171;">{critical_min:.2f}</div>
            <div class="kpi-caption">Defisit paling kritis dalam minggu kerja</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="kpi-card kpi-card-success">
            <div class="kpi-title">PEAK DEFICIT</div>
            <div class="kpi-value" style="color:#34d399;">0.00</div>
            <div class="kpi-caption">Tidak ada defisit beban kapasitas</div>
        </div>
        """, unsafe_allow_html=True)

with k3:
    sec_count = len(shortage_sections)
    if sec_count > 0:
        st.markdown(f"""
        <div class="kpi-card kpi-card-warning">
            <div class="kpi-title">SECTIONS AT RISK</div>
            <div class="kpi-value" style="color:#fbbf24;">{sec_count} Section</div>
            <div class="kpi-caption">{', '.join(shortage_sections[:3])}{'...' if sec_count > 3 else ''}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="kpi-card kpi-card-success">
            <div class="kpi-title">SECTIONS AT RISK</div>
            <div class="kpi-value" style="color:#34d399;">0 Section</div>
            <div class="kpi-caption">Semua area kerja beroperasi normal</div>
        </div>
        """, unsafe_allow_html=True)

with k4:
    st.markdown(f"""
    <div class="kpi-card kpi-card-info">
        <div class="kpi-title">NET CAPACITY (IE)</div>
        <div class="kpi-value" style="color:#38bdf8;">{plan['net_hours_per_day']:.2f} <span style="font-size:0.95rem;">h/hari</span></div>
        <div class="kpi-caption">Gross {gross_hours:.1f}h · DT {downtime:.0f}% · Allw {allowance:.0f}%</div>
    </div>
    """, unsafe_allow_html=True)

with k5:
    st.markdown(f"""
    <div class="kpi-card kpi-card-purple">
        <div class="kpi-title">KNOWLEDGE BASE</div>
        <div class="kpi-value" style="color:#c084fc;">{custom_sheets} <span style="font-size:0.95rem;">Sheets</span></div>
        <div class="kpi-caption">{v2_rows} baris Control Tower aktif</div>
    </div>
    """, unsafe_allow_html=True)

# Section Alert Banner if shortages exist
if shortage_sections:
    section_badges = " ".join([f"<span class='badge-chip badge-red'>⚠️ {sec}</span>" for sec in shortage_sections])
    st.markdown(f"""
    <div class="alert-banner">
        <div style="font-size:1.4rem;">🚨</div>
        <div>
            <div style="font-weight:700; color:#f87171; font-size:0.92rem;">PERHATIAN KAPASITAS: Terdeteksi defisit kapasitas pada section berikut:</div>
            <div style="margin-top:4px;">{section_badges}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ================= TABS NAVIGATION =================
tab1, tab2, tab3 = st.tabs(["🤖 AI OPERATIONS COPILOT", "📊 FACTORY CONTROL TOWER", "🧾 AUDIT & ACTIVITY LOG"])

# ================= TAB 1: AI COPILOT =================
with tab1:
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.subheader("🤖 AI Operations Copilot")
        st.caption("Asisten cerdas analisis kapasitas pabrik, bottleneck, Kaizen, simulasi alokasi jam kerja, dan action plan.")
    with header_col2:
        if ai.active:
            st.markdown(f"""
            <div style="text-align:right; padding-top:6px;">
                <span class="badge-chip badge-green">🟢 GEMINI AI ONLINE</span><br>
                <span style="font-size:0.75rem; color:#94a3b8;">Model: {GEMINI_MODEL}</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="text-align:right; padding-top:6px;">
                <span class="badge-chip badge-red">🔴 AI OFFLINE</span><br>
                <span style="font-size:0.75rem; color:#94a3b8;">API Key belum diisi</span>
            </div>
            """, unsafe_allow_html=True)

    # Quick Recommendation Action Buttons
    st.markdown("**💡 Rekomendasi Prompt Cepat (Klik untuk Analisis):**")
    q_col1, q_col2, q_col3, q_col4 = st.columns(4)
    quick_query = None
    with q_col1:
        if st.button("🚨 Analisis 5 Bottleneck Terkritis", use_container_width=True):
            quick_query = "Identifikasi dan analisis 5 bottleneck kapasitas teratas saat ini, jelaskan minggu terburuknya dan estimasi dampaknya."
    with q_col2:
        if st.button("🔧 Solusi Kaizen Sablon & Manpower", use_container_width=True):
            quick_query = "Berikan rekomendasi perbaikan Kaizen dan penyesuaian manpower khusus untuk section Sablon yang mengalami defisit."
    with q_col3:
        if st.button("⏱️ Evaluasi Alokasi Jam Kerja & Shift", use_container_width=True):
            quick_query = "Bandingkan jam kerja Excel dengan Net Available IE saat ini. Mengapa ada perbedaan jam kerja antar section dan apa saran shift-nya?"
    with q_col4:
        if st.button("📋 Rencana Tindakan (Action Plan) Pabrik", use_container_width=True):
            quick_query = "Buat ringkasan rencana tindakan terstruktur (Action Plan) untuk mengatasi seluruh section yang berada dalam status defisit."

    # Render Chat History
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.web_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Chat Input
    user_input = st.chat_input("Tanyakan tentang kapasitas mesin, bottleneck, Kaizen, simulasi jam kerja, atau action plan...")
    
    # Process user query (either from chat input or quick prompt button)
    query_to_process = user_input or quick_query
    
    if query_to_process:
        # Persist user message
        try:
            add_message(CHAT_CHANNEL, CHAT_USER, "user", query_to_process)
        except Exception:
            pass
        st.session_state.web_messages.append({"role": "user", "content": query_to_process})
        with st.chat_message("user"):
            st.markdown(query_to_process)

        with st.chat_message("assistant"):
            if not ai.active:
                answer = "AI Offline: GEMINI_API_KEY belum tersedia di konfigurasi (.env)."
                st.error(answer)
            else:
                with st.spinner("Factory AI sedang menganalisis kapasitas dan memori pabrik..."):
                    try:
                        history = get_history(CHAT_CHANNEL, CHAT_USER, 8)
                        answer = ai.ask(
                            query_to_process, 
                            factory.compact_context(),
                            history,
                            {
                                "gross_hours": gross_hours, 
                                "working_days": working_days,
                                "downtime": downtime, 
                                "allowance": allowance
                            }
                        )
                        st.markdown(answer)
                    except Exception as exc:
                        answer = f"AI Error: {exc}"
                        st.error(answer)

            # Persist assistant response
            try:
                add_message(CHAT_CHANNEL, CHAT_USER, "assistant", answer)
            except Exception:
                pass
            st.session_state.web_messages.append({"role": "assistant", "content": answer})
            try:
                log_activity(CHAT_CHANNEL, CHAT_USER, "AI_QUERY", "SUCCESS", query_to_process)
            except Exception:
                pass

# ================= TAB 2: CONTROL TOWER =================
with tab2:
    bottlenecks = m.get("bottlenecks") or []
    wh_vs_net = m.get("working_hour_vs_net") or []

    st.markdown("### 📊 Factory Capacity Visual Control Tower")
    st.caption("Pemantauan keseimbangan beban mesin, lini proses, tenaga kerja, dan perbandingan jam kerja IE.")

    # 1. VISUAL CHARTS SECTION
    st.markdown("#### 📈 Visual Analytics & Bottleneck Ranking")
    chart_col1, chart_col2 = st.columns([1, 1])

    with chart_col1:
        if bottlenecks:
            df_b = pd.DataFrame(bottlenecks)
            df_b["Label"] = df_b["section"] + " - " + df_b["item"]
            df_b["Status"] = df_b["is_shortage"].map({True: "Defisit / Shortage", False: "Surplus / Aman"})
            
            # Altair bar chart with deficit highlight
            bar_chart = alt.Chart(df_b.head(10)).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("Label:N", sort=alt.EncodingSortField(field="worst_value", order="ascending"), title="Section & Item"),
                x=alt.X("worst_value:Q", title="Nilai Kapasitas Terburuk (Defisit vs Surplus)"),
                color=alt.Color("Status:N", scale=alt.Scale(
                    domain=["Defisit / Shortage", "Surplus / Aman"],
                    range=["#ef4444", "#10b981"]
                ), legend=alt.Legend(title="Status")),
                tooltip=[
                    alt.Tooltip("section:N", title="Section"),
                    alt.Tooltip("item:N", title="Item"),
                    alt.Tooltip("worst_week:N", title="Minggu Terburuk"),
                    alt.Tooltip("worst_value:Q", format=".2f", title="Nilai"),
                    alt.Tooltip("avg:Q", format=".2f", title="Rata-rata")
                ]
            ).properties(
                title="Peringkat 10 Bottleneck Teratas (Nilai Terburuk)",
                height=320
            )
            st.altair_chart(bar_chart, use_container_width=True)
        else:
            st.info("Data bottleneck belum tersedia.")

    with chart_col2:
        if factory.v2_sum is not None and week_cols:
            df_v2 = factory.v2_sum.copy()
            # Select which section to view in trend
            all_sections = sorted([str(s) for s in df_v2["SECTION"].dropna().unique()])
            selected_section = st.selectbox(
                "Filter Tren Mingguan Berdasarkan Section:",
                options=["(Semua Section Defisit)"] + all_sections,
                key="trend_section_selector"
            )
            
            if selected_section == "(Semua Section Defisit)":
                if shortage_sections:
                    df_trend = df_v2[df_v2["SECTION"].isin(shortage_sections)].copy()
                else:
                    df_trend = df_v2.head(6).copy()
            else:
                df_trend = df_v2[df_v2["SECTION"] == selected_section].copy()

            if not df_trend.empty:
                df_melt = df_trend.melt(
                    id_vars=["SECTION", "Item"], 
                    value_vars=week_cols, 
                    var_name="Week", 
                    value_name="Balance"
                )
                df_melt["Line_Item"] = df_melt["SECTION"].astype(str) + " - " + df_melt["Item"].astype(str)

                # Line chart showing weekly trajectory
                line_chart = alt.Chart(df_melt).mark_line(point=True).encode(
                    x=alt.X("Week:N", title="Minggu Kerja"),
                    y=alt.Y("Balance:Q", title="Keseimbangan Kapasitas (+ Surplus / - Defisit)"),
                    color=alt.Color("Line_Item:N", legend=alt.Legend(title="Lini / Item")),
                    tooltip=["SECTION", "Item", "Week", alt.Tooltip("Balance:Q", format=".2f")]
                ).properties(
                    title="Tren Kapasitas Mingguan (WK 27 - WK 31)",
                    height=280
                )
                
                # Rule line at 0 (deficit boundary)
                zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                    color="#ef4444", 
                    strokeDash=[4, 4],
                    size=1.5
                ).encode(y="y:Q")

                st.altair_chart(line_chart + zero_rule, use_container_width=True)
            else:
                st.info("Tidak ada data untuk section yang dipilih.")
        else:
            st.info("Data mingguan V2 belum dimuat.")

    st.divider()

    # 2. BOTTLENECK DETAILED TABLE WITH INTERACTIVE FILTER
    st.markdown("#### 🚧 Detil Peringkat Bottleneck (Deterministic Matrix)")
    if bottlenecks:
        b_filter_col1, b_filter_col2 = st.columns([1, 1])
        with b_filter_col1:
            filter_shortage_only = st.checkbox("Tampilkan Hanya Item Defisit (Shortage)", value=True, key="chk_shortage_only")
        
        display_bottlenecks = []
        for b in bottlenecks:
            if filter_shortage_only and not b["is_shortage"]:
                continue
            display_bottlenecks.append({
                "Status": "🔴 DEFISIT" if b["is_shortage"] else "🟢 AMAN",
                "Section": b["section"],
                "Item": b["item"],
                "Worst Week": b["worst_week"],
                "Worst Capacity": b["worst_value"],
                "Average Capacity": b["avg"]
            })
        
        if display_bottlenecks:
            df_display_b = pd.DataFrame(display_bottlenecks)
            st.dataframe(
                df_display_b,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Section": st.column_config.TextColumn("Section", width="medium"),
                    "Item": st.column_config.TextColumn("Item / Mesin", width="medium"),
                    "Worst Week": st.column_config.TextColumn("Minggu Terkritis", width="small"),
                    "Worst Capacity": st.column_config.NumberColumn("Kapasitas Terburuk", format="%.2f"),
                    "Average Capacity": st.column_config.NumberColumn("Rata-rata", format="%.2f")
                }
            )
        else:
            st.success("Tidak ada item yang mengalami defisit berdasarkan filter yang dipilih.")

    st.divider()

    # 3. COMPLETE V2 CONTROL TOWER SUMMARY MATRIX
    st.markdown("#### 📋 Matriks Lengkap Kapasitas V2 Control Tower")
    if factory.v2_sum is not None:
        v2_filter_col1, v2_filter_col2 = st.columns([2, 1])
        with v2_filter_col1:
            section_options = ["(Semua Section)"] + sorted(factory.v2_sum["SECTION"].dropna().unique().tolist())
            selected_v2_sec = st.selectbox("Saring Matriks Berdasarkan Section:", section_options, key="v2_sec_filter")
        with v2_filter_col2:
            search_item = st.text_input("Cari Item / Mesin:", placeholder="Contoh: Manpower, Table, Machine...", key="v2_item_search")

        filtered_v2 = factory.v2_sum.copy()
        if selected_v2_sec != "(Semua Section)":
            filtered_v2 = filtered_v2[filtered_v2["SECTION"] == selected_v2_sec]
        if search_item:
            filtered_v2 = filtered_v2[filtered_v2["Item"].astype(str).str.contains(search_item, case=False, na=False)]

        col_configs = {
            "NO": st.column_config.NumberColumn("No", width="small"),
            "SECTION": st.column_config.TextColumn("Section", width="medium"),
            "Item": st.column_config.TextColumn("Item / Mesin", width="medium"),
            "Working Hour": st.column_config.NumberColumn("Working Hour (Excel)", format="%.1f jam"),
            "AVG": st.column_config.NumberColumn("AVG", format="%.2f"),
            "Action Plan": st.column_config.TextColumn("Action Plan", width="large")
        }
        for w in week_cols:
            col_configs[w] = st.column_config.NumberColumn(w, format="%.2f")

        st.dataframe(
            filtered_v2,
            use_container_width=True,
            hide_index=True,
            column_config=col_configs
        )
    else:
        st.info("Data Control Tower baku belum dimuat.")

    st.divider()

    # 4. WORKING HOUR EXCEL VS NET AVAILABLE IE
    st.markdown("#### ⏱️ Analisis Jam Kerja: Excel Input vs Net IE Available")
    if wh_vs_net:
        wh_col1, wh_col2 = st.columns([1, 1])
        with wh_col1:
            df_wh = pd.DataFrame(wh_vs_net)
            # Altair chart comparing Excel Working Hour and Net IE
            df_wh_chart = df_wh.copy()
            chart_wh = alt.Chart(df_wh_chart).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("section:N", sort=alt.EncodingSortField(field="excel_working_hour", order="descending"), title="Section"),
                x=alt.X("excel_working_hour:Q", title="Jam Kerja Harian (Jam)"),
                color=alt.condition(
                    alt.datum.excel_working_hour > plan["net_hours_per_day"],
                    alt.value("#f59e0b"),
                    alt.value("#38bdf8")
                ),
                tooltip=[
                    alt.Tooltip("section:N", title="Section"),
                    alt.Tooltip("excel_working_hour:Q", format=".1f", title="Jam Kerja Excel"),
                    alt.Tooltip("gap_hours_per_day:Q", format=".2f", title="Selisih vs Net IE")
                ]
            ).properties(
                title=f"Jam Kerja Excel per Section (Garis merah: Net IE {plan['net_hours_per_day']:.2f} h/hari)",
                height=260
            )
            # Rule for Net IE Hours
            net_rule = alt.Chart(pd.DataFrame({"x": [plan["net_hours_per_day"]]})).mark_rule(
                color="#ef4444", 
                strokeDash=[4, 4],
                size=2
            ).encode(x="x:Q")
            st.altair_chart(chart_wh + net_rule, use_container_width=True)

        with wh_col2:
            st.markdown(f"""
            <div style="background:#131b2e; border:1px solid #1e293b; border-radius:8px; padding:12px 16px; margin-bottom:12px;">
                <div style="font-weight:700; color:#38bdf8; font-size:0.9rem;">💡 Industrial Engineering Insight:</div>
                <div style="font-size:0.83rem; color:#cbd5e1; margin-top:4px; line-height:1.4;">
                    • <b>Net Available IE:</b> {plan['net_hours_per_day']:.2f} jam/hari (dihitung dari Gross {gross_hours:.1f} jam dikurangi DT {downtime:.0f}% dan Allowance {allowance:.0f}%).<br>
                    • Section seperti <b>SABLON ({df_wh[df_wh['section']=='SABLON']['excel_working_hour'].values[0] if 'SABLON' in df_wh['section'].values else 21}h)</b>, 
                    <b>EMBOSS ({df_wh[df_wh['section']=='EMBOSS']['excel_working_hour'].values[0] if 'EMBOSS' in df_wh['section'].values else 20}h)</b>, dan 
                    <b>EMBROIDERY ({df_wh[df_wh['section']=='EMBROIDERY']['excel_working_hour'].values[0] if 'EMBROIDERY' in df_wh['section'].values else 18}h)</b> 
                    menerapkan sistem multi-shift (2–3 shift).
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.dataframe(
                df_wh,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "section": st.column_config.TextColumn("Section", width="medium"),
                    "excel_working_hour": st.column_config.NumberColumn("Excel WH (h)", format="%.1f"),
                    "net_hours_per_day": st.column_config.NumberColumn("Net IE (h)", format="%.2f"),
                    "gap_hours_per_day": st.column_config.NumberColumn("Selisih Gap (h)", format="%.2f"),
                    "excel_above_net": st.column_config.CheckboxColumn("Multi-Shift (> Net)")
                }
            )

    st.divider()

    # 5. MODEL & CELL PRODUCTION ALLOCATION (IF AVAILABLE)
    if factory.model_cells is not None and not factory.model_cells.empty:
        st.markdown("#### 👟 Distribusi Model Sepatu & Alokasi Cell")
        df_mc = factory.model_cells.copy()
        df_mc["QTY"] = pd.to_numeric(df_mc["QTY"], errors="coerce").fillna(0)
        
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            total_qty = df_mc["QTY"].sum()
            st.metric("Total Planned Output (Pairs/Units)", f"{total_qty:,.0f}")
        with m_col2:
            unique_models = df_mc["Model"].nunique()
            st.metric("Total Model Diproduksi", f"{unique_models} Model")
        with m_col3:
            total_cells = df_mc["Cell"].nunique() if "Cell" in df_mc.columns else 0
            st.metric("Total Cell Terlibat", f"{total_cells} Cells")

        cell_tab1, cell_tab2 = st.columns([1, 1])
        with cell_tab1:
            top_models = df_mc.groupby("Model")["QTY"].sum().reset_index().sort_values("QTY", ascending=False).head(10)
            chart_top_m = alt.Chart(top_models).mark_bar(cornerRadiusEnd=4, color="#38bdf8").encode(
                y=alt.Y("Model:N", sort=alt.EncodingSortField(field="QTY", order="descending"), title="Model"),
                x=alt.X("QTY:Q", title="Total Output QTY"),
                tooltip=["Model", alt.Tooltip("QTY:Q", format=",.0f")]
            ).properties(
                title="Top 10 Model Berdasarkan Volume Produksi",
                height=280
            )
            st.altair_chart(chart_top_m, use_container_width=True)

        with cell_tab2:
            sec_qty = df_mc.groupby("Section")["QTY"].sum().reset_index().sort_values("QTY", ascending=False)
            chart_sec_qty = alt.Chart(sec_qty).mark_bar(cornerRadiusEnd=4, color="#a855f7").encode(
                y=alt.Y("Section:N", sort=alt.EncodingSortField(field="QTY", order="descending"), title="Section"),
                x=alt.X("QTY:Q", title="Total QTY per Section"),
                tooltip=["Section", alt.Tooltip("QTY:Q", format=",.0f")]
            ).properties(
                title="Volume Produksi per Section",
                height=280
            )
            st.altair_chart(chart_sec_qty, use_container_width=True)

        with st.expander("🔍 Lihat Detail Data Model & Cell Produksi", expanded=False):
            st.dataframe(df_mc.head(100), use_container_width=True, hide_index=True)

        st.divider()

    # 6. KNOWLEDGE BASE & BASELINE V1 REPOSITORY
    st.markdown("#### 📁 Knowledge Base & Baseline Repository")
    kb_col1, kb_col2 = st.columns(2)
    with kb_col1:
        if factory.custom_sheets:
            st.markdown(f"**📑 Dynamic Knowledge Base Sheets ({len(factory.custom_sheets)} Sheets):**")
            for sheet_name, df in list(factory.custom_sheets.items())[:10]:
                with st.expander(f"📄 {sheet_name} ({len(df)} baris, {len(df.columns)} kolom)", expanded=False):
                    st.dataframe(df.head(25), use_container_width=True)
            if len(factory.custom_sheets) > 10:
                st.caption(f"...dan {len(factory.custom_sheets) - 10} sheet lainnya tersimpan di memori AI.")
        else:
            st.info("Knowledge Base tambahan belum dimuat.")

    with kb_col2:
        if factory.v1:
            st.markdown(f"**📚 V1 Baseline Overview ({len(factory.v1)} Proses):**")
            v1_summary = [
                {"Process / Sheet": k, "Total Rows": len(v), "Total Cols": len(v.columns)}
                for k, v in factory.v1.items()
            ]
            st.dataframe(v1_summary, use_container_width=True, hide_index=True)
        else:
            st.info("V1 Baseline file baku belum dimuat.")

# ================= TAB 3: AUDIT & ACTIVITY LOG =================
with tab3:
    st.subheader("🧾 Audit & System Activity Log")
    st.caption("Catatan seluruh interaksi AI, audit query, dan status eksekusi sistem.")

    rows = recent_activity(50)
    
    # Activity metrics
    log_m1, log_m2, log_m3 = st.columns(3)
    with log_m1:
        st.metric("Total Aktivitas Tercatat", len(rows) if rows else 0)
    with log_m2:
        ai_query_count = sum(1 for r in rows if r[2] == "AI_QUERY") if rows else 0
        st.metric("Total AI Queries", ai_query_count)
    with log_m3:
        success_rate = (sum(1 for r in rows if r[3] == "SUCCESS") / len(rows) * 100) if rows else 100
        st.metric("Success Execution Rate", f"{success_rate:.0f}%")

    st.markdown("---")
    if rows:
        log_df = pd.DataFrame([
            {
                "Time": r[5],
                "Channel": r[0],
                "User": r[1],
                "Action": r[2],
                "Status": "🟢 " + str(r[3]) if r[3] == "SUCCESS" else "🔴 " + str(r[3]),
                "Detail": r[4]
            }
            for r in rows
        ])
        st.dataframe(
            log_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Time": st.column_config.TextColumn("Waktu", width="medium"),
                "Channel": st.column_config.TextColumn("Channel", width="small"),
                "User": st.column_config.TextColumn("User", width="small"),
                "Action": st.column_config.TextColumn("Aksi", width="medium"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Detail": st.column_config.TextColumn("Detail Query / Payload", width="large")
            }
        )
    else:
        st.info("Belum ada catatan aktivitas di database.")
