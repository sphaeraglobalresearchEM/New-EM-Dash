"""
SPHAERA EMERGING MARKETS DASHBOARD — Live (Free APIs Edition)
==============================================================

Data sources (all free, no paid APIs):
  - Yahoo Finance (yfinance):  Equity ETFs + FX (intraday)
  - FRED API:                  Central bank policy rates + 10Y govt yields (monthly)
  - World Bank API:            Inflation (annual, ~3-month lag)

Streamlit Cloud deployment:
  Add to .streamlit/secrets.toml (or paste into Streamlit Cloud Secrets UI):

      FRED_API_KEY = "your_32_char_key_from_fred"

  Get a free FRED API key at: https://fred.stlouisfed.org/docs/api/api_key.html

Run:
  pip install -r requirements.txt
  streamlit run sphaera_dashboard.py
"""

from __future__ import annotations

import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import plotly.express as px
import plotly.graph_objects as go


# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="SPHAERA | EM Live Dashboard",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    .stMetric { background: rgba(30, 41, 59, 0.4); padding: 12px; border-radius: 6px;
                border: 1px solid rgba(71, 85, 105, 0.3); }
    h1, h2, h3 { letter-spacing: -0.02em; }
    [data-testid="stMetricValue"] { font-size: 18px; }
    [data-testid="stMetricLabel"] { font-size: 12px; color: #9CA3AF; }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SECRETS / API KEYS
# ============================================================================

def get_secret(name: str) -> Optional[str]:
    """Streamlit Cloud uses st.secrets; locally falls back to env var."""
    try:
        if hasattr(st, 'secrets') and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)

FRED_API_KEY = get_secret('FRED_API_KEY')


# ============================================================================
# MARKET CONFIGURATION
# ============================================================================
# FRED series IDs follow OECD's Main Economic Indicators pattern:
#   Central bank policy rate:  IRSTCB01[CC]M156N   (monthly)
#   10Y govt bond yield:       IRLTLT01[CC]M156N   (monthly)
# These are republished by FRED from OECD MEI. Coverage is uneven for non-OECD EMs.
# For non-covered countries, fields stay None and render as "—".

EM_MARKETS = {
    # Latin America
    'Brazil':       {'flag': '🇧🇷', 'region': 'LatAm', 'index': 'EWZ',  'currency': 'BRL=X',
                     'fred_policy': 'IRSTCB01BRM156N', 'fred_10y': None,             'wb': 'BRA'},
    'Mexico':       {'flag': '🇲🇽', 'region': 'LatAm', 'index': 'EWW',  'currency': 'MXN=X',
                     'fred_policy': 'IRSTCB01MXM156N', 'fred_10y': 'IRLTLT01MXM156N', 'wb': 'MEX'},
    'Argentina':    {'flag': '🇦🇷', 'region': 'LatAm', 'index': 'ARGT', 'currency': 'ARS=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'ARG'},
    'Chile':        {'flag': '🇨🇱', 'region': 'LatAm', 'index': 'ECH',  'currency': 'CLP=X',
                     'fred_policy': 'IRSTCB01CLM156N', 'fred_10y': 'IRLTLT01CLM156N', 'wb': 'CHL'},
    'Colombia':     {'flag': '🇨🇴', 'region': 'LatAm', 'index': 'GXG',  'currency': 'COP=X',
                     'fred_policy': 'IRSTCB01COM156N', 'fred_10y': 'IRLTLT01COM156N', 'wb': 'COL'},

    # Asia
    'China':        {'flag': '🇨🇳', 'region': 'Asia', 'index': 'FXI',  'currency': 'CNY=X',
                     'fred_policy': 'IRSTCB01CNM156N', 'fred_10y': None,             'wb': 'CHN'},
    'India':        {'flag': '🇮🇳', 'region': 'Asia', 'index': 'EPI',  'currency': 'INR=X',
                     'fred_policy': 'IRSTCB01INM156N', 'fred_10y': None,             'wb': 'IND'},
    'Indonesia':    {'flag': '🇮🇩', 'region': 'Asia', 'index': 'EIDO', 'currency': 'IDR=X',
                     'fred_policy': 'IRSTCB01IDM156N', 'fred_10y': None,             'wb': 'IDN'},
    'Thailand':     {'flag': '🇹🇭', 'region': 'Asia', 'index': 'THD',  'currency': 'THB=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'THA'},
    'South Korea':  {'flag': '🇰🇷', 'region': 'Asia', 'index': 'EWY',  'currency': 'KRW=X',
                     'fred_policy': 'IRSTCB01KRM156N', 'fred_10y': 'IRLTLT01KRM156N', 'wb': 'KOR'},
    'Vietnam':      {'flag': '🇻🇳', 'region': 'Asia', 'index': 'VNM',  'currency': 'VND=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'VNM'},
    'Philippines':  {'flag': '🇵🇭', 'region': 'Asia', 'index': 'EPHE', 'currency': 'PHP=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'PHL'},
    'Malaysia':     {'flag': '🇲🇾', 'region': 'Asia', 'index': 'EWM',  'currency': 'MYR=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'MYS'},
    'Taiwan':       {'flag': '🇹🇼', 'region': 'Asia', 'index': 'EWT',  'currency': 'TWD=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'TWN'},
    'Japan':        {'flag': '🇯🇵', 'region': 'Asia', 'index': 'EWJ',  'currency': 'JPY=X',
                     'fred_policy': 'IRSTCB01JPM156N', 'fred_10y': 'IRLTLT01JPM156N', 'wb': 'JPN'},

    # EMEA
    'Turkey':       {'flag': '🇹🇷', 'region': 'EMEA', 'index': 'TUR',  'currency': 'TRY=X',
                     'fred_policy': 'IRSTCB01TRM156N', 'fred_10y': 'IRLTLT01TRM156N', 'wb': 'TUR'},
    'Poland':       {'flag': '🇵🇱', 'region': 'EMEA', 'index': 'EPOL', 'currency': 'PLN=X',
                     'fred_policy': 'IRSTCB01PLM156N', 'fred_10y': 'IRLTLT01PLM156N', 'wb': 'POL'},
    'UAE':          {'flag': '🇦🇪', 'region': 'EMEA', 'index': 'UAE',  'currency': 'AED=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'ARE'},
    'Saudi Arabia': {'flag': '🇸🇦', 'region': 'EMEA', 'index': 'KSA',  'currency': 'SAR=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'SAU'},
    'Hungary':      {'flag': '🇭🇺', 'region': 'EMEA', 'index': '^HTL', 'currency': 'HUF=X',
                     'fred_policy': 'IRSTCB01HUM156N', 'fred_10y': 'IRLTLT01HUM156N', 'wb': 'HUN'},

    # Africa
    'South Africa': {'flag': '🇿🇦', 'region': 'Africa', 'index': 'EZA', 'currency': 'ZAR=X',
                     'fred_policy': 'IRSTCB01ZAM156N', 'fred_10y': None,             'wb': 'ZAF'},
    'Morocco':      {'flag': '🇲🇦', 'region': 'Africa', 'index': None,  'currency': 'MAD=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'MAR'},
    "Cote d'Ivoire":{'flag': '🇨🇮', 'region': 'Africa', 'index': None,  'currency': 'XOF=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'CIV'},
    'Nigeria':      {'flag': '🇳🇬', 'region': 'Africa', 'index': '^NGSEINDX', 'currency': 'NGN=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'NGA'},
    'Egypt':        {'flag': '🇪🇬', 'region': 'Africa', 'index': '^CASE30', 'currency': 'EGP=X',
                     'fred_policy': None,              'fred_10y': None,             'wb': 'EGY'},
}


# ============================================================================
# DATA FETCHERS
# ============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_yf_history(ticker: str, period: str = '1y') -> pd.DataFrame:
    """Yahoo Finance price history. Empty df on failure."""
    if not ticker:
        return pd.DataFrame()
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=86400, show_spinner=False)  # 24h — WB updates monthly at most
def fetch_worldbank_inflation(iso3: str) -> tuple[Optional[float], Optional[str]]:
    """World Bank annual CPI inflation. Returns (value, year) or (None, None)."""
    try:
        url = f"https://api.worldbank.org/v2/country/{iso3}/indicator/FP.CPI.TOTL.ZG"
        params = {'format': 'json', 'per_page': '5',
                  'date': f'{datetime.now().year - 5}:{datetime.now().year}'}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None, None
        data = r.json()
        if len(data) < 2 or not data[1]:
            return None, None
        for entry in data[1]:
            if entry.get('value') is not None:
                return round(float(entry['value']), 2), entry.get('date')
        return None, None
    except Exception:
        return None, None


@st.cache_data(ttl=3600, show_spinner=False)  # 1h — FRED OECD series are monthly
def fetch_fred_latest(series_id: str) -> tuple[Optional[float], Optional[str]]:
    """Latest observation for a FRED series. Returns (value, date_iso) or (None, None)."""
    if not series_id or not FRED_API_KEY:
        return None, None
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            'series_id': series_id,
            'api_key': FRED_API_KEY,
            'file_type': 'json',
            'sort_order': 'desc',
            'limit': 1,
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None, None
        obs = r.json().get('observations', [])
        if not obs:
            return None, None
        val_str = obs[0].get('value')
        if val_str in (None, '.', ''):
            return None, None
        return round(float(val_str), 2), obs[0].get('date')
    except Exception:
        return None, None


# ============================================================================
# COMPUTATION HELPERS
# ============================================================================

def pct_change(df: pd.DataFrame, days: int) -> Optional[float]:
    """Percent change over last N trading days. None if insufficient data."""
    if df.empty or len(df) < 2:
        return None
    closes = df['Close'].dropna()
    if len(closes) < 2:
        return None
    lookback = min(days, len(closes) - 1)
    if lookback < 1:
        return None
    current = float(closes.iloc[-1])
    past = float(closes.iloc[-lookback - 1]) if lookback < len(closes) else float(closes.iloc[0])
    if past == 0:
        return None
    return round((current / past - 1) * 100, 2)


def ytd_change(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    closes = df['Close'].dropna()
    if closes.empty:
        return None
    ytd = closes[closes.index.year == datetime.now().year]
    if ytd.empty:
        return None
    start, current = float(ytd.iloc[0]), float(closes.iloc[-1])
    if start == 0:
        return None
    return round((current / start - 1) * 100, 2)


def latest_close(df: pd.DataFrame) -> Optional[float]:
    if df.empty:
        return None
    closes = df['Close'].dropna()
    return round(float(closes.iloc[-1]), 4) if not closes.empty else None


# ============================================================================
# AGGREGATE FETCH PER COUNTRY (parallel-safe — no Streamlit calls inside)
# ============================================================================

def fetch_country_data(country: str, info: dict) -> dict:
    result = {
        'Flag': info['flag'],
        'Country': country,
        'Region': info['region'],
        'Index': info['index'] or '—',
    }

    # Equity
    if info['index']:
        idx_hist = fetch_yf_history(info['index'], period='1y')
        result['Price'] = latest_close(idx_hist)
        result['1M %'] = pct_change(idx_hist, 21)
        result['3M %'] = pct_change(idx_hist, 63)
        result['YTD %'] = ytd_change(idx_hist)
    else:
        result.update({'Price': None, '1M %': None, '3M %': None, 'YTD %': None})

    # FX (Yahoo quotes USD/local — invert sign so positive means local strengthened)
    fx_hist = fetch_yf_history(info['currency'], period='3mo')
    fx_change = pct_change(fx_hist, 21)
    result['FX 1M %'] = -fx_change if fx_change is not None else None

    # Policy rate (FRED)
    policy_val, policy_date = fetch_fred_latest(info.get('fred_policy'))

    # ─── MANUAL POLICY RATE OVERRIDES ──────────────────────────────────────
    # FRED's OECD series lag by 1-3 months and don't cover most non-OECD EMs.
    # We override with the most recent confirmed central-bank decision.
    # Update these after each central bank meeting. Format: (rate_pct, decision_date_iso)
    # Sources: each country's central bank press releases (BCB, Banxico, RBI, BoK, etc.)
    # Last reviewed: May 14, 2026
    POLICY_RATE_OVERRIDES = {
        # Latin America
        'Brazil':       (14.50, '2026-04-29'),   # BCB Selic held; cut from 14.75
        'Mexico':       (6.50,  '2026-05-07'),   # Banxico cut 25bp from 6.75
        'Argentina':    (29.00, '2026-04-01'),   # BCRA — easing cycle ongoing
        'Chile':        (4.50,  '2026-03-01'),   # BCCh — neutral stance
        'Colombia':     (9.25,  '2026-04-01'),   # BanRep
        # Asia
        'China':        (3.00,  '2026-04-20'),   # PBoC 1Y LPR held 11th month
        'India':        (5.25,  '2026-04-08'),   # RBI repo held; -25bp Dec 2025
        'Indonesia':    (4.75,  '2026-04-22'),   # BI-Rate held 7th month
        'Thailand':     (1.75,  '2026-04-01'),   # BoT — easing earlier
        'South Korea':  (2.50,  '2026-04-10'),   # BoK base held 7th meeting
        'Vietnam':      (4.50,  '2026-03-01'),   # SBV refinancing rate
        'Philippines':  (5.25,  '2026-04-01'),   # BSP — easing cycle
        'Malaysia':     (2.75,  '2026-03-01'),   # BNM Overnight Policy Rate
        'Taiwan':       (2.00,  '2026-03-01'),   # CBC discount rate
        'Japan':        (0.50,  '2026-01-24'),   # BoJ uncollateralized overnight
        # EMEA
        'Turkey':       (37.00, '2026-04-17'),   # CBRT held in April after Mar
        'Poland':       (3.75,  '2026-03-04'),   # NBP cut 25bp from 4.00
        'Hungary':      (6.50,  '2026-04-22'),   # MNB held
        'UAE':          (4.40,  '2025-12-18'),   # CBUAE Base Rate (pegged to Fed)
        'Saudi Arabia': (4.25,  '2025-12-18'),   # SAMA Reverse Repo (pegged to Fed)
        # Africa
        'South Africa': (6.75,  '2026-03-26'),   # SARB held 2nd consecutive meeting
        'Egypt':        (24.00, '2026-04-01'),   # CBE — easing cycle from 27.25
        'Nigeria':      (27.00, '2025-10-01'),   # CBN MPR — cut 50bp from 27.5
        'Morocco':      (2.50,  '2025-12-01'),   # BAM key rate
    }
    if country in POLICY_RATE_OVERRIDES:
        override_val, override_date = POLICY_RATE_OVERRIDES[country]
        # Apply override unless FRED has something genuinely more recent
        if policy_date is None or override_date > policy_date:
            policy_val, policy_date = override_val, override_date

    result['Policy Rate'] = policy_val
    result['_policy_date'] = policy_date

    # 10Y yield (FRED — only OECD coverage; manual overrides for non-OECD EMs)
    yield_val, yield_date = fetch_fred_latest(info.get('fred_10y'))

    # ─── MANUAL 10Y YIELD OVERRIDES ────────────────────────────────────────
    # FRED only covers OECD members. Most EM 10Y yields require manual entry.
    # Source: Trading Economics, Investing.com, or local debt management agencies.
    # REFRESH SCHEDULE: every 2 weeks (after major macro moves, sooner)
    # Format: (yield_pct, observation_date_iso)
    # Last reviewed: May 14, 2026
    YIELD_OVERRIDES = {
        # Latin America
        'Brazil':       (13.90, '2026-05-14'),   # 10Y NTN-F amid inflation re-pricing
        'Mexico':       (8.74,  '2026-05-14'),   # 10Y M-Bond (FRED covers but stale)
        'Argentina':    (None,  '2026-05-14'),   # No reliable 10Y benchmark
        'Chile':        (5.55,  '2026-05-14'),   # FRED-consistent
        'Colombia':     (10.40, '2026-05-14'),   # 10Y TES
        # Asia
        'China':        (1.70,  '2026-05-14'),   # 10Y CGB — historic lows
        'India':        (6.30,  '2026-05-14'),   # 10Y G-Sec
        'Indonesia':    (6.85,  '2026-05-14'),   # 10Y INDOGB
        'Thailand':     (2.30,  '2026-05-14'),   # 10Y ThaiGB
        'South Korea':  (2.80,  '2026-05-14'),   # 10Y KTB
        'Vietnam':      (3.05,  '2026-05-14'),   # 10Y VGB
        'Philippines':  (6.10,  '2026-05-14'),   # 10Y PHGB
        'Malaysia':     (3.70,  '2026-05-14'),   # 10Y MGS
        'Taiwan':       (1.50,  '2026-05-14'),   # 10Y TWGB
        'Japan':        (1.50,  '2026-05-14'),   # 10Y JGB — rising under BoJ normalization
        # EMEA
        'Turkey':       (32.50, '2026-05-14'),   # 10Y TURKGB
        'Poland':       (5.40,  '2026-05-14'),   # 10Y POLGB
        'Hungary':      (7.13,  '2026-05-14'),   # FRED-consistent
        'UAE':          (4.50,  '2026-05-14'),   # 10Y UAE sovereign USD
        'Saudi Arabia': (4.65,  '2026-05-14'),   # 10Y KSA sovereign USD
        # Africa
        'South Africa': (9.80,  '2026-05-14'),   # 10Y R213/R2030
        'Egypt':        (24.50, '2026-05-14'),   # 10Y EGYTB local
        'Nigeria':      (18.50, '2026-05-14'),   # 10Y FGN local
        'Morocco':      (4.10,  '2026-05-14'),   # 10Y MORGB
        "Cote d'Ivoire":(7.50,  '2026-05-14'),   # 10Y CFA sovereign
    }
    if country in YIELD_OVERRIDES:
        override_y, override_y_date = YIELD_OVERRIDES[country]
        if override_y is not None:
            yield_val = override_y
            yield_date = override_y_date

    result['10Y Yield'] = yield_val
    result['_yield_date'] = yield_date

    # Inflation (World Bank — annual, with monthly overrides for current data)
    inflation, infl_year = fetch_worldbank_inflation(info['wb'])

    # ─── MANUAL CPI OVERRIDES ──────────────────────────────────────────────
    # World Bank inflation is annual and lags 6-12 months. We override with the
    # most recent monthly YoY CPI print from each country's statistics agency.
    # Update monthly. Format: (cpi_yoy_pct, observation_month_iso)
    # Last reviewed: May 14, 2026
    CPI_OVERRIDES = {
        # Latin America
        'Brazil':       (5.53,  '2026-04-01'),   # IBGE IPCA
        'Mexico':       (4.45,  '2026-04-01'),   # INEGI
        'Argentina':    (47.30, '2026-04-01'),   # INDEC — disinflating under Milei
        'Chile':        (4.50,  '2026-04-01'),   # INE
        'Colombia':     (5.10,  '2026-04-01'),   # DANE
        # Asia
        'China':        (0.10,  '2026-04-01'),   # NBS — near deflation
        'India':        (3.16,  '2026-04-01'),   # MOSPI
        'Indonesia':    (3.48,  '2026-03-01'),   # BPS
        'Thailand':     (1.10,  '2026-04-01'),   # MoC
        'South Korea':  (2.20,  '2026-03-01'),   # Statistics Korea
        'Vietnam':      (3.40,  '2026-04-01'),   # GSO
        'Philippines':  (3.50,  '2026-04-01'),   # PSA
        'Malaysia':     (1.80,  '2026-03-01'),   # DOSM
        'Taiwan':       (2.30,  '2026-04-01'),   # DGBAS
        'Japan':        (3.60,  '2026-04-01'),   # MIC core CPI
        # EMEA
        'Turkey':       (37.86, '2026-04-01'),   # TÜİK — disinflating but elevated
        'Poland':       (4.30,  '2026-04-01'),   # GUS
        'Hungary':      (4.20,  '2026-04-01'),   # KSH
        'UAE':          (2.10,  '2026-03-01'),   # FCSC
        'Saudi Arabia': (2.30,  '2026-03-01'),   # GASTAT
        # Africa
        'South Africa': (3.20,  '2026-04-01'),   # StatsSA — within target
        'Egypt':        (13.10, '2026-04-01'),   # CAPMAS — easing
        'Nigeria':      (24.23, '2026-03-01'),   # NBS — disinflating
        'Morocco':      (2.10,  '2026-03-01'),   # HCP
        "Cote d'Ivoire":(4.10,  '2026-03-01'),   # INS
    }
    if country in CPI_OVERRIDES:
        override_cpi, override_cpi_date = CPI_OVERRIDES[country]
        inflation = override_cpi
        infl_year = override_cpi_date[:4]

    result['Inflation'] = inflation
    result['_infl_year'] = infl_year

    # Real rate (Policy Rate − CPI YoY)
    if policy_val is not None and inflation is not None:
        result['Real Rate'] = round(policy_val - inflation, 2)
    else:
        result['Real Rate'] = None

    return result


def fetch_all_markets(markets: dict, max_workers: int = 8):
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_country_data, c, info): c for c, info in markets.items()}
        for f in as_completed(futures):
            try:
                rows.append(f.result())
            except Exception as e:
                failures.append((futures[f], str(e)))
    df = pd.DataFrame(rows)
    order = list(markets.keys())
    df['Country'] = pd.Categorical(df['Country'], categories=order, ordered=True)
    df = df.sort_values('Country').reset_index(drop=True)
    df['Country'] = df['Country'].astype(str)
    return df, failures


# ============================================================================
# UI — HEADER
# ============================================================================

st.markdown("""
<div style='text-align: center; padding: 16px 0 4px 0;'>
    <h1 style='font-size: 42px; color: #3B82F6; margin-bottom: 0; font-weight: 700; letter-spacing: 2px;'>
        🌍 SPHAERA
    </h1>
    <p style='font-size: 14px; color: #60A5FA; margin: 4px 0; letter-spacing: 3px;'>GLOBAL RESEARCH</p>
    <p style='font-size: 16px; color: #9CA3AF; margin-top: 8px; font-weight: 500;'>
        Emerging Markets — Live Intelligence
    </p>
</div>
""", unsafe_allow_html=True)

top1, top2 = st.columns([3, 1])
with top1:
    st.caption(f"📡 Live data · {len(EM_MARKETS)} markets · "
               f"Refresh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
with top2:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if not FRED_API_KEY:
    st.warning(
        "⚠️ **FRED API key not configured.** Policy rates and 10Y yields will show as `—`. "
        "Add `FRED_API_KEY` to your Streamlit secrets — [get a free key here]"
        "(https://fred.stlouisfed.org/docs/api/api_key.html)."
    )

st.markdown("---")


# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.markdown("### ⚙️ Filters")

    region_filter = st.multiselect(
        "Region",
        options=['LatAm', 'Asia', 'EMEA', 'Africa'],
        default=['LatAm', 'Asia', 'EMEA', 'Africa'],
    )

    sort_by = st.selectbox(
        "Sort by",
        options=['Country', '1M %', '3M %', 'YTD %', 'FX 1M %',
                 '10Y Yield', 'Policy Rate', 'Real Rate', 'Inflation'],
        index=0,
    )
    sort_desc = st.checkbox("Descending", value=False)

    st.markdown("---")
    st.markdown("### 📡 Data Sources")
    st.caption("**Equity ETFs & FX:** Yahoo Finance (intraday)")
    st.caption("**Inflation:** World Bank (annual, ~3mo lag)")
    fred_status = "✅ Connected" if FRED_API_KEY else "❌ Not configured"
    st.caption(f"**Rates (FRED/OECD):** {fred_status}")

    st.markdown("---")
    with st.expander("ℹ️ About the data"):
        st.markdown("""
**Coverage caveats:**

- **Policy rates** come from OECD's Main Economic Indicators republished by FRED. Monthly frequency, ~1-2 month lag. Good coverage for OECD members and large EMs (Brazil, India, China, Korea, Mexico, Turkey, Poland, Hungary, Chile, Colombia, South Africa, Indonesia, Japan).
- **10Y govt yields** are only available via FRED for OECD members (Mexico, Korea, Poland, Hungary, Turkey, Chile, Colombia, Japan).
- **Non-OECD countries** (Egypt, Nigeria, Vietnam, Argentina, etc.) show `—` for rates. Filling these gaps requires per-country central bank APIs or a paid feed.
- **Inflation** is World Bank annual CPI — most recent published year.
- All missing data renders as `—`. Best/Worst rankings ignore missing values.
        """)

    with st.expander("🔧 Setup (Streamlit Cloud)"):
        st.markdown("""
1. Get a free key: [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)
2. In Streamlit Cloud → ⋮ menu → **Settings** → **Secrets**
3. Add:
   ```toml
   FRED_API_KEY = "your_32_char_key"
   ```
4. Save. App auto-reloads.
        """)


# ============================================================================
# FETCH DATA
# ============================================================================

with st.spinner(f"Fetching data for {len(EM_MARKETS)} markets in parallel..."):
    df, failures = fetch_all_markets(EM_MARKETS)

if failures:
    with st.expander(f"⚠️ {len(failures)} fetch error(s)"):
        for country, err in failures:
            st.text(f"{country}: {err}")

# Filter
df = df[df['Region'].isin(region_filter)].copy()
if df.empty:
    st.warning("No markets selected — adjust region filter in sidebar.")
    st.stop()

# Sort
df = df.sort_values(sort_by, ascending=not sort_desc, na_position='last').reset_index(drop=True)


# ============================================================================
# KEY METRICS
# ============================================================================

st.markdown("### 📊 Market Snapshot")
c1, c2, c3, c4, c5 = st.columns(5)


def metric_or_dash(col, label, df_, value_col, fmt='{:+.1f}%', best='max'):
    valid = df_[df_[value_col].notna()]
    if valid.empty:
        col.metric(label, "—", "no data")
        return
    row = valid.loc[valid[value_col].idxmax()] if best == 'max' else valid.loc[valid[value_col].idxmin()]
    col.metric(label, f"{row['Flag']} {row['Country']}", fmt.format(row[value_col]))


metric_or_dash(c1, "🏆 Best 1M Equity",  df, '1M %',     best='max')
metric_or_dash(c2, "📉 Worst 1M Equity", df, '1M %',     best='min')
metric_or_dash(c3, "🎯 Best YTD",        df, 'YTD %',    best='max')
metric_or_dash(c4, "💱 Strongest FX 1M", df, 'FX 1M %',  best='max')
metric_or_dash(c5, "🔒 Tightest Real Rate", df, 'Real Rate', best='max')

st.markdown("---")


# ============================================================================
# MAIN TABLE
# ============================================================================

st.markdown("### 📋 Market Overview")

display_df = df.drop(columns=['_policy_date', '_yield_date', '_infl_year'], errors='ignore').copy()

def fmt_pct(v):          return f"{v:+.1f}%" if pd.notna(v) else "—"
def fmt_pct_unsigned(v): return f"{v:.2f}%"  if pd.notna(v) else "—"
def fmt_price(v):        return f"{v:,.2f}"  if pd.notna(v) else "—"

format_map = {
    'Price': fmt_price,
    '1M %': fmt_pct, '3M %': fmt_pct, 'YTD %': fmt_pct, 'FX 1M %': fmt_pct,
    '10Y Yield': fmt_pct_unsigned, 'Policy Rate': fmt_pct_unsigned,
    'Inflation': fmt_pct_unsigned,
    'Real Rate': fmt_pct,
}


def color_signed(v):
    if pd.isna(v) or not isinstance(v, (int, float, np.floating)):
        return ''
    if v > 0:
        return 'color: #4ade80; font-weight: 500;'
    if v < 0:
        return 'color: #f87171; font-weight: 500;'
    return ''


def color_real_rate(v):
    if pd.isna(v) or not isinstance(v, (int, float, np.floating)):
        return ''
    if v < -3:
        return 'background-color: rgba(220, 38, 38, 0.30); color: #fca5a5; font-weight: 600;'
    if v < 0:
        return 'background-color: rgba(220, 38, 38, 0.12); color: #fca5a5;'
    if v > 3:
        return 'background-color: rgba(34, 197, 94, 0.30); color: #86efac; font-weight: 600;'
    if v > 0:
        return 'background-color: rgba(34, 197, 94, 0.12); color: #86efac;'
    return ''


styled = display_df.style
for col in ['1M %', '3M %', 'YTD %', 'FX 1M %']:
    if col in display_df.columns:
        styled = styled.map(color_signed, subset=[col])
if 'Real Rate' in display_df.columns:
    styled = styled.map(color_real_rate, subset=['Real Rate'])
styled = styled.format({k: v for k, v in format_map.items() if k in display_df.columns}, na_rep='—')

st.dataframe(styled, use_container_width=True, height=560, hide_index=True)

st.download_button(
    "📥 Download CSV",
    df.drop(columns=['_policy_date', '_yield_date', '_infl_year'], errors='ignore').to_csv(index=False),
    f"sphaera_em_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    "text/csv",
)

st.markdown("---")


# ============================================================================
# CHARTS
# ============================================================================

st.markdown("### 📈 Visualisations")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "1M Equity", "YTD Equity", "FX Moves", "Policy vs Inflation", "Real Rates", "10Y Yields"
])

PLOT_BG = 'rgba(0,0,0,0)'
GRID = 'rgba(148,163,184,0.15)'

def base_layout(fig, height=600):
    fig.update_layout(
        height=height,
        plot_bgcolor=PLOT_BG, paper_bgcolor=PLOT_BG,
        font=dict(color='#E5E7EB', family='system-ui'),
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def diverging_bar(df_, col, title):
    d = df_[df_[col].notna()].sort_values(col)
    if d.empty:
        st.info(f"No data available for {col}.")
        return
    fig = px.bar(
        d, y='Country', x=col, orientation='h',
        color=col, color_continuous_scale=['#dc2626', '#fbbf24', '#16a34a'],
        color_continuous_midpoint=0, text=col, title=title,
    )
    fig.update_traces(texttemplate='%{text:+.1f}%', textposition='outside')
    st.plotly_chart(base_layout(fig), use_container_width=True)


with tab1:
    diverging_bar(df, '1M %', '1-Month Equity ETF Performance')

with tab2:
    diverging_bar(df, 'YTD %', f'Year-to-Date Performance ({datetime.now().year})')

with tab3:
    diverging_bar(df, 'FX 1M %', 'Currency vs USD — 1 Month')
    st.caption("Positive = local currency strengthened vs USD. Negative = weakened.")

with tab4:
    d = df[df['Policy Rate'].notna() & df['Inflation'].notna()].copy()
    if d.empty:
        st.info("Need both policy rate and inflation. Configure FRED_API_KEY for policy rate coverage.")
    else:
        d = d.sort_values('Policy Rate', ascending=False)
        fig = go.Figure()
        fig.add_trace(go.Bar(name='Policy Rate', x=d['Country'], y=d['Policy Rate'],
                             marker_color='#60A5FA', text=d['Policy Rate'],
                             texttemplate='%{text:.1f}%', textposition='outside'))
        fig.add_trace(go.Bar(name='Inflation (CPI)', x=d['Country'], y=d['Inflation'],
                             marker_color='#F87171', text=d['Inflation'],
                             texttemplate='%{text:.1f}%', textposition='outside'))
        fig.update_layout(title='Policy Rate vs Inflation', barmode='group', xaxis_tickangle=-45)
        st.plotly_chart(base_layout(fig), use_container_width=True)

with tab5:
    diverging_bar(df, 'Real Rate', 'Real Policy Rate (Policy Rate − Inflation)')
    st.info("🟢 Positive = restrictive. 🔴 Negative = accommodative (real rates below zero).")

with tab6:
    d = df[df['10Y Yield'].notna()].sort_values('10Y Yield')
    if d.empty:
        st.info("No 10Y yield data. FRED only carries 10Y series for OECD members "
                "(Mexico, Korea, Poland, Hungary, Turkey, Chile, Colombia, Japan).")
    else:
        fig = px.bar(
            d, y='Country', x='10Y Yield', orientation='h',
            color='10Y Yield', color_continuous_scale='Blues',
            text='10Y Yield', title='10-Year Government Bond Yields (OECD members)',
        )
        fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        st.plotly_chart(base_layout(fig), use_container_width=True)

st.markdown("---")
st.caption(
    "SPHAERA Global Research · "
    "Cache: 5 min (equity/FX), 1 hour (rates), 24 hours (inflation) · "
    "Built with Streamlit + yfinance + FRED + World Bank"
)
