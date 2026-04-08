import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import io
import warnings

warnings.filterwarnings('ignore')

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Double Date Order Tracker Pro",
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
    .kpi-card {
        border-radius: 12px; padding: 1.2rem; background: white;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-top: 4px solid;
        margin-bottom: 1rem;
    }
    .kpi-title { font-size: 0.8rem; font-weight: 700; color: #6B7280; text-transform: uppercase; }
    .kpi-val { font-size: 1.8rem; font-weight: 800; color: #111827; }
</style>
""", unsafe_allow_html=True)

# --- 3. SMART GOOGLE DRIVE LOADER (MASTER FILE LOGIC) ---
@st.cache_data(ttl=3600) 
def load_smart_compiled_data():
    try:
        scope = ["https://www.googleapis.com/auth/drive"]
        
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Secrets 'gcp_service_account' belum di-set!")
            return pd.DataFrame()

        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        drive_service = build('drive', 'v3', credentials=creds)
        folder_id = "10N4ky9vKH4TVl0PprwfYQDCTeQvLTvXC"
        
        # --- PERBAIKAN: Gunakan format CSV agar RAM tidak jebol ---
        master_file_name = "MASTER_COMPILED_DATA.csv"

        query_master = f"'{folder_id}' in parents and name = '{master_file_name}' and trashed = false"
        master_results = drive_service.files().list(q=query_master, fields="files(id, name)").execute()
        master_files = master_results.get('files', [])

        if master_files:
            st.sidebar.success("🚀 Membaca dari Master Database (GDrive)")
            request = drive_service.files().get_media(fileId=master_files[0]['id'])
            file_bytes = io.BytesIO()
            downloader = MediaIoBaseDownload(file_bytes, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            file_bytes.seek(0)
            
            # BACA SEBAGAI CSV (Sangat Ringan)
            return pd.read_csv(file_bytes, low_memory=False)

        else:
            st.sidebar.warning("⚠️ Master Database belum ada. Melakukan kompilasi awal...")
            return pd.DataFrame()

    except Exception as e:
        st.error(f"🔥 Error Drive: {str(e)}")
        return pd.DataFrame()

def force_recompile_and_upload():
    """Fungsi untuk menggabungkan semua file dan menyimpan balik ke Drive sebagai CSV"""
    try:
        scope = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        drive_service = build('drive', 'v3', credentials=creds)
        folder_id = "10N4ky9vKH4TVl0PprwfYQDCTeQvLTvXC"
        
        master_file_name = "MASTER_COMPILED_DATA.csv"

        # Tarik semua file kecuali Master
        query = f"'{folder_id}' in parents and name != '{master_file_name}' and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        files = results.get('files', [])

        all_dfs = []
        pbar = st.sidebar.progress(0)
        for i, f in enumerate(files):
            request = drive_service.files().get_media(fileId=f['id'])
            fb = io.BytesIO()
            downloader = MediaIoBaseDownload(fb, request)
            done = False
            while not done: status, done = downloader.next_chunk()
            fb.seek(0)
            
            try:
                if f['name'].endswith('.csv'): 
                    df_t = pd.read_csv(fb, low_memory=False)
                else:
                    try: df_t = pd.read_excel(fb, engine='openpyxl')
                    except: df_t = pd.read_excel(fb, engine='xlrd')
                all_dfs.append(df_t)
            except: pass
            pbar.progress((i+1)/len(files))

        if all_dfs:
            final_df = pd.concat(all_dfs, ignore_index=True)
            
            # Tulis ke memori (BytesIO)
            output = io.BytesIO()
            final_df.to_csv(output, index=False)
            output.seek(0)
            media = MediaIoBaseUpload(output, mimetype='text/csv')
            
            # --- PERBAIKAN LOGIKA ROBOT (UPDATE BUKAN CREATE) ---
            # Cari apakah file master sudah ada
            q_master = f"'{folder_id}' in parents and name = '{master_file_name}' and trashed = false"
            master_files = drive_service.files().list(q=q_master).execute().get('files', [])

            if master_files:
                # JIKA ADA: Lakukan 'Update' ke file milik Bapak (Tidak memakan kuota robot)
                file_id_to_update = master_files[0]['id']
                drive_service.files().update(fileId=file_id_to_update, media_body=media).execute()
                st.sidebar.success("✅ Database Master (CSV) berhasil di-update!")
            else:
                # Fallback (Jika Bapak belum upload file kosong, robot akan mencoba Create dan error)
                st.sidebar.warning("Mencoba membuat file baru (Jika error kuota, mohon upload file MASTER_COMPILED_DATA.csv kosong ke Drive)")
                drive_service.files().create(body={'name': master_file_name, 'parents': [folder_id]}, media_body=media).execute()
                st.sidebar.success("✅ Database Master (CSV) baru berhasil dibuat!")

            return final_df
    except Exception as e:
        st.sidebar.error(f"Gagal Recompile: {e}")
        return pd.DataFrame()

# --- 4. DATA PROCESSING ---

@st.cache_data(ttl=3600)  # <--- TAMBAHKAN BARIS SAKTI INI DI SINI
def process_oms_data(df):
    if df.empty: return df
    df.columns = [str(c).strip() for c in df.columns]
    needed_cols = ['Marketplace', 'Order Date', 'Order Number', 'Paid Amount', 'Shipping Provider']
    df = df[[c for c in needed_cols if c in df.columns]].copy()
    
    if 'Order Date' in df.columns:
        df['Order Date'] = pd.to_datetime(df['Order Date'], format='%d/%m/%Y, %H:%M:%S', errors='coerce')
        df['Campaign_Month'] = df['Order Date'].dt.strftime('%b %Y')
        df['Order_Hour'] = df['Order Date'].dt.hour
        df['Month_Sort'] = df['Order Date'].dt.to_period('M')
        df['Order_Date_Only'] = df['Order Date'].dt.date
        
    if 'Paid Amount' in df.columns:
        df['Paid Amount'] = df['Paid Amount'].astype(str).str.replace(',', '').str.replace('Rp', '').str.strip()
        df['Paid Amount'] = pd.to_numeric(df['Paid Amount'], errors='coerce').fillna(0)
        
    return df

# --- 5. MAIN DASHBOARD ---
def main():
    st.markdown('<div class="main-header">🎯 Double Date Order Tracker </div>', unsafe_allow_html=True)
    
    # --- SIDEBAR CONTROLS ---
    with st.sidebar:
        st.markdown("### 💾 Data Synchronization")
        if st.button("🔄 Force Re-Sync & Compile All", use_container_width=True, type="primary"):
            st.cache_data.clear()
            force_recompile_and_upload()
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 📅 Global Monthly Filter")
        st.caption("Berlaku untuk Tab 2, 3, dan 4")

    # Load Data
    df_raw = load_smart_compiled_data()
    if df_raw.empty:
        df_raw = force_recompile_and_upload()
    
    df = process_oms_data(df_raw)
    if df.empty: return st.info("Menunggu data...")

    # Data Level Order (Unique)
    df_order = df.drop_duplicates(subset=['Order Number']).copy()

    # Get months for global filter
    campaign_opts = sorted(df_order['Campaign_Month'].dropna().unique().tolist(), key=lambda x: datetime.strptime(x, '%b %Y'))
    
    with st.sidebar:
        sel_months = st.multiselect("Pilih Bulan:", options=campaign_opts, default=campaign_opts)

    # Apply global filter
    df_filtered = df_order[df_order['Campaign_Month'].isin(sel_months)] if sel_months else df_order

    # --- KPI CARDS ---
    c1, c2, c3 = st.columns(3)
    def render_card(title, val, color):
        st.markdown(f'<div class="kpi-card" style="border-top-color:{color}"><div class="kpi-title">{title}</div><div class="kpi-val">{val}</div></div>', unsafe_allow_html=True)

    with c1: render_card("🛒 Total Orders", f"{len(df_filtered):,}", "#3B82F6")
    with c2: render_card("💰 Paid Amount", f"Rp {df_filtered['Paid Amount'].sum():,.0f}", "#10B981")
    with c3: render_card("🛍️ Avg Order Value", f"Rp {df_filtered['Paid Amount'].mean():,.0f}", "#F59E0B")

    # --- TABS ---
    t1, t2, t3, t4 = st.tabs(["📊 MoM BATTLE", "🚚 MARKETPLACE & LOGISTICS", "⏱️ HOURLY VELOCITY", "📋 EXPLORER"])

    # TAB 1: MoM (Hanya Tab ini yang pakai seleksi mandiri jika mau membandingkan spesifik)
    with t1:
        st.subheader("📈 Month-over-Month Battle")
        mom_df = df_filtered.groupby('Month_Sort').agg(Orders=('Order Number','nunique'), Revenue=('Paid Amount','sum')).reset_index()
        mom_df['Month_Str'] = mom_df['Month_Sort'].dt.strftime('%b %Y')
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=mom_df['Month_Str'], y=mom_df['Orders'], name='Orders', marker_color='#6366F1', text=mom_df['Orders']))
        fig.add_trace(go.Scatter(x=mom_df['Month_Str'], y=mom_df['Revenue'], name='Revenue', yaxis='y2', line=dict(color='#10B981', width=3)))
        fig.update_layout(yaxis2=dict(overlaying='y', side='right'), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True, key="mom_main")

        st.divider()
        st.subheader("🛒 Marketplace Trend (Top 10)")
        
        # Multiselect for Marketplace
        top_10_names = df_filtered.groupby('Marketplace')['Order Number'].nunique().nlargest(10).index.tolist()
        sel_mp_trend = st.multiselect("Pilih Marketplace:", options=top_10_names, default=top_10_names[:5])
        
        if sel_mp_trend:
            mp_trend = df_filtered[df_filtered['Marketplace'].isin(sel_mp_trend)].groupby(['Month_Sort', 'Marketplace'])['Order Number'].nunique().reset_index()
            mp_trend['Month_Str'] = mp_trend['Month_Sort'].dt.strftime('%b %Y')
            fig_mp = px.line(mp_trend, x='Month_Str', y='Order Number', color='Marketplace', markers=True)
            st.plotly_chart(fig_mp, use_container_width=True, key="mp_trend_multi")

    # TAB 2: Marketplace & Logistics (Terpengaruh Global Filter)
    with t2:
        st.subheader(f"📊 Logistics & Platform Share ({', '.join(sel_months)})")
        c_m, c_l = st.columns(2)
        with c_m:
            mp_share = df_filtered.groupby('Marketplace')['Order Number'].nunique().reset_index()
            st.plotly_chart(px.pie(mp_share, values='Order Number', names='Marketplace', hole=0.4), key="mp_share_pie")
        with c_l:
            log_load = df_filtered.groupby('Shipping Provider')['Order Number'].nunique().nlargest(10).reset_index()
            st.plotly_chart(px.bar(log_load, x='Order Number', y='Shipping Provider', orientation='h'), key="log_bar")

    # TAB 3: Hourly Velocity (Terpengaruh Global Filter)
    with t3:
        st.subheader(f"⏱️ Hourly Peaks ({', '.join(sel_months)})")
        hr_df = df_filtered.groupby('Order_Hour')['Order Number'].nunique().reset_index()
        fig_hr = px.bar(hr_df, x='Order_Hour', y='Order Number', color='Order Number')
        st.plotly_chart(fig_hr, use_container_width=True, key="hourly_v")

    # TAB 4: Explorer
    with t4:
        st.dataframe(df_filtered.sort_values('Order Date', ascending=False), use_container_width=True)

if __name__ == "__main__":
    main()
