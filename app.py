import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import warnings

warnings.filterwarnings('ignore')

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Double Date MoM Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CUSTOM CSS ---
st.markdown("""
<style>
    .stApp { background-color: #F8FAFC !important; }
    .main-header {
        font-size: 2.2rem; font-weight: 900;
        background: linear-gradient(90deg, #E11D48 0%, #F59E0B 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0px; text-align: center;
    }
    .sub-header { text-align: center; color: #6B7280; font-size: 0.9rem; margin-bottom: 20px; }
    
    .kpi-card {
        border-radius: 12px; padding: 1.5rem; color: white;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05); transition: transform 0.3s;
        margin-bottom: 1rem; border-top: 4px solid; background: white;
    }
    .kpi-card:hover { transform: translateY(-3px); box-shadow: 0 8px 15px rgba(0,0,0,0.1); }
    .kpi-title { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; color: #6B7280; margin-bottom: 8px; }
    .kpi-val { font-size: 2rem; font-weight: 900; color: #111827; margin-bottom: 4px; }
    .kpi-sub { font-size: 0.85rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# --- 3. GOOGLE DRIVE LOADER ---
@st.cache_data(ttl=300)
def load_compiled_data():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly"
        ]
        
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Secrets 'gcp_service_account' belum di-set!")
            return pd.DataFrame()

        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        drive_service = build('drive', 'v3', credentials=creds)
        
        folder_id = "10N4ky9vKH4TVl0PprwfYQDCTeQvLTvXC"
        
        st.sidebar.info("🔍 Memindai folder Drive...")
        
        # Ambil file xls, xlsx, csv
        query = f"'{folder_id}' in parents and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=100).execute()
        files = results.get('files', [])
        
        if not files:
            st.sidebar.error("❌ Folder kosong!")
            return pd.DataFrame()
            
        all_dataframes = []
        progress_bar = st.sidebar.progress(0)
        
        for i, file in enumerate(files):
            file_id = file['id']
            file_name = file['name']
            mime_type = file['mimeType']
            
            try:
                request = drive_service.files().get_media(fileId=file_id)
                file_bytes = io.BytesIO()
                downloader = MediaIoBaseDownload(file_bytes, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                
                # --- PERBAIKAN: LOGIKA BACA FILE LEBIH PINTAR ---
                if file_name.endswith('.csv'):
                    file_bytes.seek(0)
                    df_temp = pd.read_csv(file_bytes, low_memory=False)
                else:
                    # Sistem sering 'bohong' (file aslinya xlsx tapi dinamai xls)
                    # Kita coba baca sebagai xlsx modern dulu
                    try:
                        file_bytes.seek(0)
                        df_temp = pd.read_excel(file_bytes, engine='openpyxl')
                    except Exception:
                        # Kalau gagal, berarti memang file xls jadul beneran
                        file_bytes.seek(0)
                        df_temp = pd.read_excel(file_bytes, engine='xlrd')
                        
                all_dataframes.append(df_temp)
            except Exception as e:
                st.sidebar.warning(f"Gagal baca {file_name}: {str(e)}")
                
            progress_bar.progress((i + 1) / len(files))
            
        if all_dataframes:
            df_master = pd.concat(all_dataframes, ignore_index=True)
            st.sidebar.success(f"✅ Sukses: {len(df_master):,} Baris Data Mentah")
            return df_master
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.sidebar.error(f"🔥 Error Drive: {str(e)}")
        return pd.DataFrame()

# --- 4. DATA PROCESSING ---
def process_oms_data(df):
    if df.empty: return df
    
    # Bersihkan nama kolom
    df.columns = [str(c).strip() for c in df.columns]
    
    # Filter kolom yang dibutuhkan saja untuk meringankan memori
    needed_cols = ['Marketplace', 'Order Date', 'Order Number', 'Paid Amount', 'Shipping Provider']
    existing_cols = [c for c in needed_cols if c in df.columns]
    df = df[existing_cols].copy()
    
    # 1. Cleaning Tanggal (Format: 03/03/2026, 00:00:38)
    if 'Order Date' in df.columns:
        # Hapus spasi berlebih
        df['Order Date'] = df['Order Date'].astype(str).str.strip()
        # Parse tanggal (dd/mm/yyyy, HH:MM:SS)
        df['Order Date'] = pd.to_datetime(df['Order Date'], format='%d/%m/%Y, %H:%M:%S', errors='coerce')
        
        # Ekstrak data untuk analisa
        df['Campaign_Month'] = df['Order Date'].dt.strftime('%b %Y') # Contoh: Mar 2026
        df['Order_Hour'] = df['Order Date'].dt.hour
        df['Month_Sort'] = df['Order Date'].dt.to_period('M')
        
    # 2. Cleaning Paid Amount
    if 'Paid Amount' in df.columns:
        df['Paid Amount'] = df['Paid Amount'].astype(str).str.replace(',', '').str.replace('Rp', '').str.strip()
        df['Paid Amount'] = pd.to_numeric(df['Paid Amount'], errors='coerce').fillna(0)
        
    return df

# --- 5. MAIN DASHBOARD ---
def main():
    st.markdown('<div class="main-header">🎯 Double Date MoM Battle</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Month-over-Month Campaign Performance (Unique Orders & Paid Amount)</div>', unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("### ⚙️ Controls")
        if st.button("🔄 Sync & Compile Data", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
            
    # Load & Process
    raw_df = load_compiled_data()
    df = process_oms_data(raw_df)
    
    if df.empty:
        st.info("👋 Menunggu data dari Google Drive.")
        return

    # --- MEMBUAT ORDER-LEVEL DATAFRAME (KUNCI AGAR TIDAK DOUBLE/DUPLIKAT) ---
    # Karena data mentah per item, kita ambil 1 baris saja per Order Number
    if 'Order Number' in df.columns:
        df_order_level = df.drop_duplicates(subset=['Order Number']).copy()
    else:
        df_order_level = df.copy()
        st.warning("Kolom 'Order Number' tidak ditemukan. Kalkulasi mungkin terduplikasi.")

    # --- GLOBAL FILTERS ---
    st.markdown("### 🔍 Filters")
    f1, f2 = st.columns(2)
    
    with f1:
        campaign_opts = sorted(df_order_level['Campaign_Month'].dropna().unique().tolist(), key=lambda x: datetime.strptime(x, '%b %Y'))
        sel_campaigns = st.multiselect("📅 Campaign Month (Double Date):", options=campaign_opts, default=campaign_opts)
            
    with f2:
        mp_options = ["All"] + sorted(df_order_level['Marketplace'].dropna().unique().tolist()) if 'Marketplace' in df_order_level.columns else ["All"]
        sel_mp = st.selectbox("🛒 Marketplace:", mp_options)

    # Apply Filter ke Data Level Order
    df_filtered = df_order_level.copy()
    if sel_campaigns:
        df_filtered = df_filtered[df_filtered['Campaign_Month'].isin(sel_campaigns)]
    if sel_mp != "All":
        df_filtered = df_filtered[df_filtered['Marketplace'] == sel_mp]

    if df_filtered.empty:
        st.warning("⚠️ Tidak ada data untuk filter tersebut.")
        return

    # --- KPI CARDS ---
    tot_orders = df_filtered['Order Number'].nunique()
    tot_paid = df_filtered['Paid Amount'].sum()
    avg_order_value = tot_paid / tot_orders if tot_orders > 0 else 0

    def render_card(title, val, sub, border_col, sub_col):
        return f'<div class="kpi-card" style="border-top-color: {border_col};"><div class="kpi-title">{title}</div><div class="kpi-val">{val}</div><div class="kpi-sub" style="color:{sub_col};">{sub}</div></div>'

    c1, c2, c3 = st.columns(3)
    with c1: st.markdown(render_card("🛒 Total Unique Orders", f"{tot_orders:,}", "Total Pesanan", "#3B82F6", "#3B82F6"), unsafe_allow_html=True)
    with c2: st.markdown(render_card("💰 Total Paid Amount", f"Rp {tot_paid/1e6:,.1f} Jt" if tot_paid >= 1e6 else f"Rp {tot_paid:,.0f}", "Total Pendapatan", "#10B981", "#10B981"), unsafe_allow_html=True)
    with c3: st.markdown(render_card("🛍️ Avg Order Value (AOV)", f"Rp {avg_order_value:,.0f}", "Rata-rata belanja per pesanan", "#F59E0B", "#F59E0B"), unsafe_allow_html=True)

    st.divider()

    # --- TABS ---
    t1, t2, t3 = st.tabs(["📊 MoM PERFORMANCE", "🚚 MARKETPLACE & LOGISTICS", "⏱️ HOURLY VELOCITY"])

    # === TAB 1: MoM PERFORMANCE ===
    with t1:
        st.subheader("📈 Double Date Battle: Month-over-Month")
        st.caption("Perbandingan performa antar bulan (contoh: 1.1 vs 2.2 vs 3.3). Data di bawah sudah berdasarkan Unique Order.")
        
        # Agregasi per bulan (Urut berdasarkan Waktu)
        mom_df = df_filtered.groupby('Month_Sort').agg(
            Orders=('Order Number', 'nunique'),
            Paid_Amount=('Paid Amount', 'sum')
        ).reset_index()
        
        mom_df['Month_Str'] = mom_df['Month_Sort'].dt.strftime('%b %Y')
        
        # Chart Combo (Bar Orders, Line Paid Amount)
        fig_mom = go.Figure()
        
        fig_mom.add_trace(go.Bar(
            x=mom_df['Month_Str'], y=mom_df['Orders'],
            name='Unique Orders',
            marker_color='#6366F1',
            text=[f"{x:,}" for x in mom_df['Orders']], textposition='auto'
        ))
        
        fig_mom.add_trace(go.Scatter(
            x=mom_df['Month_Str'], y=mom_df['Paid_Amount'],
            name='Paid Amount (Rp)',
            mode='lines+markers',
            line=dict(color='#10B981', width=3),
            yaxis='y2'
        ))
        
        fig_mom.update_layout(
            height=450, hovermode="x unified",
            yaxis=dict(title="Total Orders", showgrid=False),
            yaxis2=dict(title="Paid Amount (Rp)", overlaying='y', side='right', showgrid=True, gridcolor='rgba(0,0,0,0.05)'),
            legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            plot_bgcolor='white', margin=dict(t=10, b=10, l=10, r=10)
        )
        st.plotly_chart(fig_mom, use_container_width=True)

    # === TAB 2: MARKETPLACE & LOGISTICS ===
    with t2:
        col_mp, col_log = st.columns(2)
        
        with col_mp:
            st.subheader("🛒 Marketplace Share (by Orders)")
            if 'Marketplace' in df_filtered.columns:
                mp_df = df_filtered.groupby('Marketplace')['Order Number'].nunique().reset_index()
                fig_mp = px.pie(mp_df, values='Order Number', names='Marketplace', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_mp.update_traces(textinfo='percent+label', textposition='inside')
                fig_mp.update_layout(showlegend=False, margin=dict(t=30, b=0, l=0, r=0))
                st.plotly_chart(fig_mp, use_container_width=True)

        with col_log:
            st.subheader("🚚 Shipping Provider Load")
            if 'Shipping Provider' in df_filtered.columns:
                # Bersihkan nama kurir yang kosong
                log_df = df_filtered[df_filtered['Shipping Provider'].notna() & (df_filtered['Shipping Provider'] != '')]
                log_df = log_df.groupby('Shipping Provider')['Order Number'].nunique().reset_index().sort_values('Order Number', ascending=True)
                
                fig_log = px.bar(log_df, x='Order Number', y='Shipping Provider', orientation='h', color_discrete_sequence=['#F59E0B'])
                fig_log.update_traces(texttemplate='%{x:,}', textposition='outside')
                fig_log.update_layout(xaxis_title="Total Orders", yaxis_title="", plot_bgcolor='white', margin=dict(t=30, b=0, l=0, r=0))
                st.plotly_chart(fig_log, use_container_width=True)

    # === TAB 3: HOURLY VELOCITY ===
    with t3:
        st.subheader("⏱️ Hourly Traffic (Kapan Order Masuk Terbanyak?)")
        st.caption("Membantu operasional gudang menebak jam sibuk (peak hour) selama Double Date.")
        
        if 'Order_Hour' in df_filtered.columns:
            # Agregasi jam dari SEMUA campaign terpilih
            hour_df = df_filtered.groupby('Order_Hour')['Order Number'].nunique().reset_index()
            
            # Pastikan 24 jam lengkap (0 - 23)
            all_hours = pd.DataFrame({'Order_Hour': range(24)})
            hour_df = pd.merge(all_hours, hour_df, on='Order_Hour', how='left').fillna(0)
            
            # Format jam untuk X-axis
            hour_df['Hour_Label'] = hour_df['Order_Hour'].apply(lambda x: f"{int(x):02d}:00")
            
            fig_hour = go.Figure()
            fig_hour.add_trace(go.Bar(
                x=hour_df['Hour_Label'], y=hour_df['Order Number'],
                marker_color='#3B82F6',
                text=[f"{x:,.0f}" if x > 0 else "" for x in hour_df['Order Number']],
                textposition='outside'
            ))
            
            fig_hour.update_layout(
                height=400, xaxis_title="Jam (00:00 - 23:00)", yaxis_title="Total Orders",
                plot_bgcolor='white', hovermode="x unified",
                margin=dict(t=20, b=20, l=10, r=10)
            )
            fig_hour.update_yaxes(showgrid=True, gridcolor='rgba(0,0,0,0.05)')
            st.plotly_chart(fig_hour, use_container_width=True)
            
    # --- FOOTER ---
    st.divider()
    with st.expander("📋 Tampilkan Data Mentah (Unique Orders)"):
        st.dataframe(df_filtered.sort_values('Order Date', ascending=False), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
