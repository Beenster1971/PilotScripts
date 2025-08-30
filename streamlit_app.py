# streamlit_app.py
import streamlit as st
from simbrief_core import fetch_ofp, extract_fields, build_vfr, build_ifr

st.set_page_config(page_title="SimBrief → VFR/IFR Scripts", layout="wide")

st.title("🎙️ SimBrief → VFR/IFR Radio Scripts")

with st.sidebar:
    st.header("Inputs")
    sim_id = st.text_input("SimBrief ID (username or numeric Pilot ID)", value="548969")
    include_vfr = st.checkbox("Output VFR", value=True)
    include_ifr = st.checkbox("Output IFR", value=True)

    st.subheader("Manual fields (not in OFP)")
    hold = st.text_input("Holding Point", value="A1")
    wind = st.text_input("Surface Wind", value="240/12")
    atis = st.text_input("ATIS (phonetic word)", value="Alpha")
    qnh = st.text_input("QNH (hPa)", value="1013")
    clevel = st.text_input("Initial Cleared Level (feet)", value="6000")
    squawk = st.text_input("Squawk", value="4721")
    alt = st.text_input("Enroute/Join Altitude", value="2400")
    dep_rwy_fb = st.text_input("Fallback Departure Runway", value="27")
    arr_rwy_fb = st.text_input("Fallback Arrival Runway", value="27")

    st.subheader("UK VFR call extras")
    pos = st.text_input("Present Position", value="over Grafham Water VRP")
    timez = st.text_input("Time (UTC hhmm)", value="1522")
    next_pt = st.text_input("Next Reporting Point", value="St Neots VRP")
    eta = st.text_input("ETA to Next Point (hhmm)", value="1530")
    dist_dir = st.text_input("Distance/Direction from Arrival", value="8 miles south")

col_left, col_right = st.columns([2, 3])

with col_left:
    if st.button("Fetch & Build Scripts", type="primary"):
        st.session_state["trigger"] = True

    # Persist last fetch
    if "trigger" in st.session_state and st.session_state["trigger"]:
        try:
            mode, payload, raw = fetch_ofp(sim_id.strip() or "548969")
            vals = extract_fields(mode, payload)
            st.success("Fetched OFP and extracted fields.")

            with st.expander("Extracted fields (debug)", expanded=False):
                st.json(vals)
        except Exception as e:
            st.error(f"Failed to fetch/extract OFP: {e}")
            vals = None
    else:
        vals = None

with col_right:
    if vals:
        vfr_text = ifr_text = ""
        if include_vfr:
            vfr_text = build_vfr(vals, hold, wind, atis, qnh, alt, dep_rwy_fb, arr_rwy_fb,
                                 pos, timez, next_pt, eta, dist_dir)
        if include_ifr:
            ifr_text = build_ifr(vals, hold, wind, atis, qnh, clevel, squawk, alt, dep_rwy_fb, arr_rwy_fb)

        # Show scripts
        if vfr_text:
            with st.expander("VFR Script", expanded=True):
                st.code(vfr_text)
                st.download_button("Download VFR (.txt)", data=vfr_text, file_name="VFR_script.txt", mime="text/plain")
        if ifr_text:
            with st.expander("IFR Script", expanded=True):
                st.code(ifr_text)
                st.download_button("Download IFR (.txt)", data=ifr_text, file_name="IFR_script.txt", mime="text/plain")

        # Combined download
        if vfr_text or ifr_text:
            combined = ""
            if vfr_text: combined += "=== VFR Script ===\n" + vfr_text + "\n\n"
            if ifr_text: combined += "=== IFR Script ===\n" + ifr_text
            st.download_button("Download Combined (.txt)", data=combined, file_name="RT_Scripts.txt", mime="text/plain")
    else:
        st.info("Enter SimBrief ID and click **Fetch & Build Scripts**.")
