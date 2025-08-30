# streamlit_app.py
import html
import streamlit as st
from simbrief_core import fetch_ofp, extract_fields, build_vfr, build_ifr

st.set_page_config(page_title="SimBrief → VFR/IFR Scripts", layout="wide")

# --- state
if "vals" not in st.session_state: st.session_state["vals"] = None
if "expanded_script" not in st.session_state: st.session_state["expanded_script"] = None  # None | 'vfr' | 'ifr'
if "font_vfr" not in st.session_state: st.session_state["font_vfr"] = 16  # px
if "font_ifr" not in st.session_state: st.session_state["font_ifr"] = 16  # px

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.0rem; padding-bottom: 1rem; }
      /* iPad-friendly buttons */
      .touch-btn > button { padding: 0.6rem 0.9rem; font-size: 1rem; }
      .touch-icon > button { padding: 0.55rem 0.75rem; font-size: 1.1rem; }
      .tight-row { margin-top: 0.25rem; margin-bottom: 0.25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🎙️ SimBrief → VFR/IFR Radio Scripts")

# 2-column layout (left controls, right scripts)
col_left, col_right = st.columns([0.95, 2.05], gap="large")

with col_left:
    with st.expander("Inputs", expanded=True):  # collapsible left pane
        sim_id = st.text_input("SimBrief ID (username or numeric Pilot ID)", value="548969")
        include_vfr = st.checkbox("Output VFR", value=True)
        include_ifr = st.checkbox("Output IFR", value=True)

        # Fetch in left pane just under checkboxes
        fetch = st.button("Fetch & Build Scripts", type="primary")

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

        if fetch:
            try:
                mode, payload, raw = fetch_ofp(sim_id.strip() or "548969")
                st.session_state.vals = extract_fields(mode, payload)
                st.success("Fetched OFP and extracted fields.")
            except Exception as e:
                st.session_state.vals = None
                st.error(f"Failed to fetch/extract OFP: {e}")

    # Extracted fields at the bottom of the left pane
    with st.expander("Extracted fields (debug)", expanded=False):
        if st.session_state.vals:
            st.json(st.session_state.vals)
        else:
            st.caption("Nothing fetched yet.")

with col_right:
    vals = st.session_state.vals
    if not vals:
        st.info("Enter SimBrief ID and tap **Fetch & Build Scripts** in the left pane.")
    else:
        # Build scripts
        vfr_text = ifr_text = ""
        if include_vfr:
            vfr_text = build_vfr(vals, hold, wind, atis, qnh, alt, dep_rwy_fb, arr_rwy_fb,
                                 pos, timez, next_pt, eta, dist_dir)
        if include_ifr:
            ifr_text = build_ifr(vals, hold, wind, atis, qnh, clevel, squawk, alt, dep_rwy_fb, arr_rwy_fb)

        def set_expand(kind: str):
            st.session_state.expanded_script = (None if st.session_state.expanded_script == kind else kind)

        def render_code_block(code_text: str, font_px: int, key: str):
            """Render pre/code with a specified font size (HTML escaped)."""
            safe = html.escape(code_text)
            st.markdown(
                f"""
                <div style="font-size:{font_px}px; line-height:1.5;">
                  <pre style="white-space:pre-wrap; margin:0;">{safe}</pre>
                </div>
                """,
                unsafe_allow_html=True,
            )

        def script_box(title: str, text: str, kind: str):
            if not text:
                return
            expanded = (st.session_state.expanded_script == kind)
            # choose which font size state to use
            font_key = "font_vfr" if kind == "vfr" else "font_ifr"
            font_px = st.session_state[font_key]

            # Header row: title, expand/restore, download, font +/- (touch friendly)
            c1, c2, c3, c4, c5 = st.columns([1.4, 1.1, 1.7, 0.7, 0.7])  # balanced for iPad
            with c1: st.subheader(title)
            with c2:
                if expanded:
                    if st.button("Restore split", key=f"restore_{kind}", help="Show both scripts", use_container_width=True):
                        set_expand(kind)  # toggles back to None
                else:
                    if st.button(f"Expand {kind.upper()}", key=f"expand_{kind}", help="Fill the right column", use_container_width=True):
                        set_expand(kind)
            with c3:
                st.download_button(
                    f"Download {kind.upper()} (.txt)",
                    data=text,
                    file_name=f"{kind.upper()}_script.txt",
                    mime="text/plain",
                    key=f"dl_{kind}",
                    use_container_width=True,
                )
            # A− / A+ buttons, nice big hit area for tablets
            with c4:
                if st.container().button("A−", key=f"dec_{kind}", help="Decrease font size", type="secondary"):
                    st.session_state[font_key] = max(12, font_px - 2)
                    st.rerun()
            with c5:
                if st.container().button("A+", key=f"inc_{kind}", help="Increase font size", type="secondary"):
                    st.session_state[font_key] = min(36, font_px + 2)
                    st.rerun()

            # The code itself
            render_code_block(text, st.session_state[font_key], key=f"code_{kind}")

        # Expanded logic: show one or both
        if st.session_state.expanded_script in (None, 'vfr'):
            script_box("VFR Script", vfr_text, "vfr")
            st.markdown("<div class='tight-row'></div>", unsafe_allow_html=True)
        if st.session_state.expanded_script in (None, 'ifr'):
            script_box("IFR Script", ifr_text, "ifr")

        # Combined download
        if vfr_text or ifr_text:
            combined = ""
            if vfr_text: combined += "=== VFR Script ===\n" + vfr_text + "\n\n"
            if ifr_text: combined += "=== IFR Script ===\n" + ifr_text
            st.download_button("Download Combined (.txt)", data=combined, file_name="RT_Scripts.txt", mime="text/plain", key="dl_both", use_container_width=True)
