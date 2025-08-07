
# Wire Length & Voltage Drop Helper (Streamlit)

An MVP calculator that lets you paste an electrical product URL (optimized for City Electric Supply pages), enter project runs, and get:
- Total cable footage (with slack & waste)
- Per‑run voltage‑drop sanity checks and suggested minimum AWG
- Packaging-aware buy plan (e.g., 250/500/1000 ft)
- CSV export

> Estimations only. Not a substitute for NEC/CEC compliance or professional engineering judgment.

## One‑Click Deploy (Free)

You can deploy this **for free** on Streamlit Cloud in ~5 minutes.

### Steps
1. **Create a GitHub repo** (public is fine for a demo).
2. Add these files to the repo:
   - `wire_calculator_app.py`
   - `requirements.txt`
   - `README.md`
3. Go to **https://streamlit.io/cloud** and click **Deploy an app**.
4. Connect your GitHub, pick your repo/branch, and set:
   - **Main file path**: `wire_calculator_app.py`
5. Click **Deploy**.

Streamlit will build from `requirements.txt` and give you a **live URL** to share.

### Optional tweaks
- To keep the app link semi-private on the free tier, just don’t index the URL—share it only with your team.
- If you later need a private app or higher resources, you can upgrade the plan or move to a different host.

## Local Run (Optional)
```bash
pip install -r requirements.txt
streamlit run wire_calculator_app.py
```

## Features
- Paste product URL → tool scrapes CES page structure to detect **AWG**, **material**, and **packaging** where possible.
- Round‑trip toggle for runs.
- Multi‑conductor multiplier (e.g., 12/2 → conductor_count=2).
- Per‑run voltage‑drop table with suggested minimum AWG.
- Ampacity sanity check (copper @ 75°C placeholder).
- Packaging overrides: enter `250,500,1000` to model typical spools.
- CSV export for quotes.

## Disclaimers
- Scraping is “best effort.” For demos, you can paste CES URLs or enter packaging manually.
- Always verify results with code, ampacity, insulation, temperature, and derating in the field.
