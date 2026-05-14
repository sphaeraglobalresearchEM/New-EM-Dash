# SPHAERA EM Dashboard

Live emerging-markets dashboard. Uses only free APIs.

**Live demo:** _your_app_url.streamlit.app_ (fill in once deployed)

---

## Deploy in 10 minutes

1. **Get FRED API key** (free, instant): https://fredaccount.stlouisfed.org/apikeys
2. **Push these files to a public GitHub repo**
3. **Deploy at https://share.streamlit.io** with main file = `sphaera_dashboard.py`
4. **Paste FRED key** into Streamlit Cloud → Settings → Secrets:
   ```toml
   FRED_API_KEY = "your_32_char_key"
   ```

Done. Auto-redeploys on every git push.

---

## File checklist

```
your-repo/
├── sphaera_dashboard.py        ← main app (Streamlit Cloud entry point)
├── requirements.txt            ← Python dependencies
├── README.md                   ← this file
├── .gitignore                  ← keeps secrets out of git
└── .streamlit/
    ├── config.toml             ← dark theme + server settings
    └── secrets.toml.example    ← template (real secrets go in Streamlit Cloud UI)
```

⚠️ Never commit a real `.streamlit/secrets.toml` — the `.gitignore` blocks it.

---

## What's live

| Field | Source | Update | Coverage |
|---|---|---|---|
| Equity 1M/3M/YTD | Yahoo Finance | Intraday | 19 of 25 EMs |
| FX 1M | Yahoo Finance | Intraday | All 25 |
| Policy rates | FRED (OECD) | Monthly | 13 of 25 |
| 10Y yields | FRED (OECD) | Monthly | 8 of 25 (OECD only) |
| Inflation | World Bank | Annual | All 25 |
| Real rate, term premium | Computed | — | Where data available |

Missing data renders as `—`. Best/Worst metrics ignore `None`.

---

## Run locally

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit secrets.toml, paste your FRED key
streamlit run sphaera_dashboard.py
```
