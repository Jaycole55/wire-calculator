
import re
import math
import csv
import io
import requests
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Wire Length & Voltage Drop Helper", page_icon="🔌", layout="wide")

st.title("🔌 Wire Length & Voltage Drop Helper — v2")
st.caption("Paste a product URL, enter your runs, and get a buy-ready estimate with voltage drop & ampacity sanity checks.")

# ------------------ Helpers ------------------

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text

def normalize_space(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_pack_length(text: str):
    # Returns (length_in_ft, unit_label) if found
    if not text:
        return None, None
    # Look for "500 ft", "1000 ft", "1000ft", "per foot", etc.
    m = re.search(r"(\d{2,5})\s*(ft|feet|FT)\b", text, re.I)
    if m:
        return int(m.group(1)), "ft"
    if re.search(r"\b(per\s+foot|by\s+the\s+foot|sold\s+by\s+foot)\b", text, re.I):
        return 1, "ft_each"
    return None, None

def parse_awg(text: str):
    if not text:
        return None
    # e.g., "6 AWG", "AWG 2", "#4 AWG"
    m = re.search(r"(?:#?\s*)(\d{1,2})\s*AWG\b", text, re.I)
    if m:
        return int(m.group(1))
    # MCM / kcmil
    m2 = re.search(r"(\d{2,4})\s*(?:kcmil|MCM)\b", text, re.I)
    if m2:
        return int(m2.group(1))  # treated separately
    return None

def detect_material(text: str):
    if not text:
        return None
    if re.search(r"\bcopper\b|\bcu\b", text, re.I):
        return "copper"
    if re.search(r"\baluminum\b|\balum\b|\bal\b", text, re.I):
        return "aluminum"
    return None

def ces_specific_scrape(soup: BeautifulSoup):
    scraped = {}
    # short description
    short = soup.select_one("div.short-description.text-dark")
    if short:
        scraped["short_description"] = normalize_space(short.get_text(" "))

    # feature bullets
    features = [normalize_space(li.get_text(" ")) for li in soup.select("li")]
    features_text = " | ".join(features[:50])
    if features_text:
        scraped["features"] = features

    # product specs block
    specs_block = ""
    strongs = soup.select("strong")
    for s in strongs:
        if "product specification" in s.get_text().strip().lower():
            section = s.find_parent()
            if section:
                specs_block = normalize_space(section.get_text(" "))
            break
    scraped["specs_block"] = specs_block

    combined_text = " ".join([scraped.get("short_description",""), features_text, specs_block])
    awg = parse_awg(combined_text)
    material = detect_material(combined_text)
    pack_len, pack_unit = parse_pack_length(combined_text)

    scraped["detected_awg"] = awg
    scraped["material"] = material
    scraped["pack_length_ft"] = pack_len
    scraped["pack_unit"] = pack_unit
    return scraped

def generic_scrape(soup: BeautifulSoup):
    text = normalize_space(soup.get_text(" "))
    return {
        "page_text_preview": text[:4000],
        "detected_awg": parse_awg(text),
        "material": detect_material(text),
        "pack_length_ft": parse_pack_length(text)[0],
        "pack_unit": parse_pack_length(text)[1],
    }

def extract_specs(url: str):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(url).hostname or ""
    data = {}
    if "cityelectricsupply.com" in host:
        data = ces_specific_scrape(soup)
    else:
        data = generic_scrape(soup)

    data["url"] = url
    return data


# Resistances per 1000 ft at ~75°C (approx), source: common tables
COPPER_OHMS_PER_KFT = {
    14: 2.525, 12: 1.588, 10: 0.999, 8: 0.6282, 6: 0.3951, 4: 0.2485, 3: 0.1970,
    2: 0.1563, 1: 0.1239, 0: 0.0983,  # 1/0
    -1: 0.0779,  # 2/0
    -2: 0.0618,  # 3/0
    -3: 0.0490,  # 4/0
}

AL_OHMS_PER_KFT = {
    12: 2.52, 10: 1.588, 8: 0.999, 6: 0.6282, 4: 0.3951, 3: 0.3133, 2: 0.2485, 1: 0.1970,
    0: 0.1563, -1: 0.1239, -2: 0.0983, -3: 0.0779
}

# Ampacity quick reference (VERY simplified, 75°C, copper THHN in raceway, not derated)
# These are placeholders for sanity checking only.
COPPER_AMPACITY_75C = {
    14: 20, 12: 25, 10: 35, 8: 50, 6: 65, 4: 85, 3: 100,
    2: 115, 1: 130, 0: 150, -1: 175, -2: 200, -3: 230
}

def awg_label(n):
    if n >= 0:
        return f"{n} AWG"
    mapping = {-1: "2/0 AWG", -2: "3/0 AWG", -3: "4/0 AWG"}
    return mapping.get(n, f"{n}")

def suggest_awg(material: str, amps: float, volts: float, one_way_length_ft: float, max_drop_pct: float):
    if material == "aluminum":
        table = AL_OHMS_PER_KFT
    else:
        table = COPPER_OHMS_PER_KFT  # default to copper
    sizes = sorted(table.keys(), reverse=True)  # -3 (4/0) ... 14
    for size in sizes:
        r_per_ft = table[size] / 1000.0
        v_drop = 2 * amps * r_per_ft * one_way_length_ft
        if (v_drop / volts) * 100.0 <= max_drop_pct:
            return size, v_drop
    return sizes[-1], 2 * amps * (table[sizes[-1]] / 1000.0) * one_way_length_ft

def make_csv_download(df: pd.DataFrame, filename: str = "wire_estimate.csv"):
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    return csv_buf.getvalue()

# ------------------ UI ------------------

meta_left, meta_right = st.columns([1,1])
with meta_left:
    project_name = st.text_input("Project name (optional)", value="")
with meta_right:
    st.write(" ")
    st.write(f"Report date: {datetime.today().strftime('%Y-%m-%d')}")

top = st.container()
with top:
    left, right = st.columns([1.4, 1])

    # ---------------- LEFT COLUMN ----------------
    with left:
        st.subheader("1) Product URL & Specs")

        # Product URL
        url = st.text_input(
            "Product URL",
            placeholder="https://www.cityelectricsupply.com/soow-6-4-portable-cord",
            value=""
        )

        # Paste-specs fallback (unique key prevents duplicate-id errors)
        manual_specs_text = st.text_area(
            "Or paste product specs (optional)",
            help="If a site blocks scraping, paste text/specs from the product page. I'll try to detect AWG, material, and packaging.",
            height=140,
            key="manual_specs_fallback"
        )

        use_round_trip = st.checkbox("Treat each run as round-trip length (out-and-back)", value=True)

        conductor_count = st.number_input(
            "Number of conductors in the cable (for multi-conductor cable)",
            min_value=1, max_value=20, value=1, step=1
        )
        st.caption("For multi-conductor cables (e.g., 12/2), enter 2; tool multiplies footage accordingly.")

        manual_pack = st.text_input(
            "Packaging override (comma-separated feet; e.g., 250,500,1000). Leave blank to use detected packaging.",
            value=""
        )

    # ---------------- RIGHT COLUMN ----------------
    with right:
        st.subheader("Parsed product specs")
        specs = {}

        if manual_specs_text.strip():
            # Parse from pasted text when scraping is blocked
            specs = {
                "url": "(manual input)",
                "detected_awg": parse_awg(manual_specs_text),
                "material": detect_material(manual_specs_text),
            }
            pl, pu = parse_pack_length(manual_specs_text)
            specs["pack_length_ft"] = pl
            specs["pack_unit"] = pu
            st.success("Parsed from pasted specs.")
            st.json(specs)

        elif url.strip():
            try:
                specs = extract_specs(url)
                st.json(specs)
            except Exception as e:
                st.error(f"Couldn't fetch/parse the page: {e}")
                specs = {"url": url}


with right:
    st.subheader("Parsed product specs")
    specs = {}

    if manual_specs_text.strip():
        # Try to detect specs from pasted text
        specs = {
            "url": "(manual input)",
            "detected_awg": parse_awg(manual_specs_text),
            "material": detect_material(manual_specs_text),
        }
        pl, pu = parse_pack_length(manual_specs_text)
        specs["pack_length_ft"] = pl
        specs["pack_unit"] = pu
        st.success("Parsed from pasted specs.")
        st.json(specs)

    elif url.strip():
        try:
            specs = extract_specs(url)
            st.json(specs)
        except Exception as e:
            st.error(f"Couldn't fetch/parse the page: {e}")
            specs = {"url": url}



        st.subheader("Electrical assumptions")
        col1, col2 = st.columns(2)
        with col1:
            volts = st.number_input("System voltage", min_value=12.0, max_value=600.0, value=120.0, step=1.0)
            amps = st.number_input("Circuit current (A)", min_value=0.0, value=15.0, step=0.5)
        with col2:
            max_drop = st.number_input("Max allowable voltage drop (%)", min_value=1.0, max_value=10.0, value=3.0, step=0.5)
            material_override = st.selectbox("Conductor material (if known)", ["auto-detect", "copper", "aluminum"])

st.markdown("---")

st.subheader("2) Runs table")
st.caption("Edit the table directly. Lengths are one-way unless 'round-trip' is checked above.")
default_rows = pd.DataFrame({
    "Run Label": [f"Run {i+1}" for i in range(3)],
    "Length (ft, one-way)": [50.0, 75.0, 100.0]
})
runs_df = st.data_editor(default_rows, num_rows="dynamic", use_container_width=True)

st.subheader("3) Slack & Waste")
colA, colB, colC, colD = st.columns(4)
with colA:
    terminations = st.number_input("Number of terminations", min_value=0, value=10, step=1)
with colB:
    slack_per_termination = st.number_input("Slack per termination (ft)", min_value=0.0, value=2.0, step=0.5)
with colC:
    vertical_allowance = st.number_input("Vertical rise allowance per termination (ft)", min_value=0.0, value=0.0, step=0.5)
with colD:
    waste_pct = st.slider("Waste/contingency (%)", 0, 30, 10)

st.markdown("---")

if st.button("Calculate Wire Needs", type="primary"):
    # Extract run lengths
    run_lengths = runs_df["Length (ft, one-way)"].fillna(0).astype(float).tolist()
    if use_round_trip:
        effective_runs = [r*2 for r in run_lengths]
    else:
        effective_runs = run_lengths
    sum_runs = sum(effective_runs)

    total_slack = terminations * (slack_per_termination + vertical_allowance)
    base_total = sum_runs + total_slack
    total_with_waste = base_total * (1 + waste_pct / 100.0)

    # Conductor multiplier for multi-conductor cable (buying by the cable, not individual wires)
    total_cable_feet = total_with_waste
    total_conductor_feet = total_with_waste * conductor_count

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sum of runs (ft, effective)", f"{sum_runs:,.1f}")
    c2.metric("Slack/vertical add (ft)", f"{total_slack:,.1f}")
    c3.metric("Total cable to order (ft)", f"{total_cable_feet:,.1f}")
    c4.metric("Total conductor feet (ft)", f"{total_conductor_feet:,.1f}")

    # Material detection override logic
    detected_material = specs.get("material") if specs else None
    detected_pack = specs.get("pack_length_ft") if specs else None
    detected_pack_unit = specs.get("pack_unit") if specs else None
    detected_awg = specs.get("detected_awg") if specs else None

    if material_override != "auto-detect":
        mat = material_override
    else:
        mat = detected_material or "copper"

    st.write(f"**Assumed conductor material for voltage drop**: `{mat}`")

    # Per-run voltage drop table
    vdrop_rows = []
    for _, row in runs_df.iterrows():
        label = row.get("Run Label", "")
        one_way = float(row.get("Length (ft, one-way)", 0) or 0)
        length_for_drop = one_way  # voltage drop uses one-way length in the formula below
        size, vdrop = (None, None)
        if amps > 0 and volts > 0 and length_for_drop > 0:
            size, vdrop = suggest_awg(mat, amps, volts, length_for_drop, max_drop)
            size_label = awg_label(size) if size is not None else ""
            pct = (vdrop / volts) * 100 if vdrop is not None else None
        else:
            size_label = ""
            pct = None
        vdrop_rows.append({
            "Run Label": label,
            "One-way length (ft)": one_way,
            "Suggested min AWG (VD)": size_label,
            "Est. V_drop (V)": round(vdrop, 2) if vdrop is not None else "",
            "Est. V_drop (%)": round(pct, 2) if pct is not None else ""
        })
    vdrop_df = pd.DataFrame(vdrop_rows)
    st.subheader("Voltage Drop — Per Run (sanity check)")
    st.dataframe(vdrop_df, use_container_width=True)

    # Ampacity sanity check against detected product AWG (very simplified)
    if detected_awg is not None:
        ampacity = COPPER_AMPACITY_75C.get(detected_awg) if mat == "copper" else None
        st.subheader("Ampacity Sanity")
        if ampacity:
            if amps > ampacity:
                st.warning(f"Detected product {detected_awg} AWG copper may be undersized for {amps:.1f} A (quick ref {ampacity} A @75°C). Verify with NEC tables and derating.")
            else:
                st.info(f"Quick check: {detected_awg} AWG copper ~{ampacity} A @75°C. Enter actual insulation, temperature rating, and apply derating as required.")
        else:
            st.caption("Ampacity quick ref only implemented for copper in this MVP.")

    # Packaging recommendation with override support
    st.subheader("Packaging / Buy Helper")
    packs = []
    if manual_pack.strip():
        try:
            packs = sorted({int(x.strip()) for x in manual_pack.split(",") if x.strip()}, reverse=True)
        except Exception:
            st.error("Couldn't parse packaging override. Use comma-separated integers like: 250,500,1000")
            packs = []
    elif detected_pack and detected_pack_unit == "ft":
        packs = [int(detected_pack)]

    if packs:
        # Greedy rounding: use largest pack sizes first
        remaining = total_cable_feet
        purchase_plan = []
        for p in packs:
            count = int(remaining // p)
            if remaining % p != 0:
                # We will decide after loop whether to add one more of the smallest
                pass
            purchase_plan.append([p, count])
            remaining = remaining - (count * p)
        # If any remainder, add one smallest pack
        if remaining > 0:
            purchase_plan[-1][1] += 1
            remaining = 0

        plan_df = pd.DataFrame(purchase_plan, columns=["Pack Length (ft)", "Quantity"])
        plan_df = plan_df[plan_df["Quantity"] > 0]
        st.success("Recommended buy plan (rounded up):")
        st.dataframe(plan_df, use_container_width=True)
    elif detected_pack_unit == "ft_each":
        st.success("Detected **sold by the foot**. Recommend ordering the exact total with a small round-up (e.g., nearest 10 ft).")
    else:
        st.warning("Packaging not detected. Use the override to model 250/500/1000 ft spools or check the product page.")

    # Export summary CSV
    summary = {
        "Project": project_name,
        "Date": datetime.today().strftime("%Y-%m-%d"),
        "URL": url,
        "Material": mat,
        "Detected AWG": detected_awg if detected_awg is not None else "",
        "Voltage (V)": volts,
        "Current (A)": amps,
        "Max Drop (%)": max_drop,
        "Round-trip runs": "Yes" if use_round_trip else "No",
        "Conductor count": conductor_count,
        "Sum runs (ft, effective)": round(sum_runs, 2),
        "Slack/vertical (ft)": round(total_slack, 2),
        "Total cable (ft)": round(total_cable_feet, 2),
        "Total conductor feet (ft)": round(total_conductor_feet, 2)
    }
    summary_df = pd.DataFrame([summary])
    runs_out = runs_df.copy()
    runs_out["Effective length used (ft)"] = [r*2 if use_round_trip else r for r in runs_df["Length (ft, one-way)"].fillna(0).astype(float).tolist()]
    export_df = summary_df.join(runs_out, how="cross")

    csv_data = make_csv_download(export_df)
    st.download_button("Download estimate CSV", data=csv_data, file_name="wire_estimate.csv", mime="text/csv")

st.markdown("---")
st.caption("Estimations only. Not a substitute for NEC/CEC compliance or professional engineering judgment. Verify insulation, temperature rating, conduit fill, and derating per code.")
