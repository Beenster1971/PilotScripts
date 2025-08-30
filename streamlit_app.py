# streamlit_app.py
import streamlit as st
from simbrief_core import fetch_ofp, extract_fields, build_vfr, build_ifr

st.set_page_config(page_title="SimBrief → VFR/IFR Scripts", layout="wide")

# ---------- STATE ----------
ss = st.session_state
ss.setdefault("vals", None)
ss.setdefault("expanded_script", None)   # None | 'vfr' | 'ifr'
ss.setdefault("left_visible", True)
ss.setdefault("font_px", 28)             # global font size for script rows

# ---------- GLOBAL CSS ----------
st.markdown(f"""
<style>
  .block-container {{ padding-top: 0.8rem; padding-bottom: 0.5rem; }}

  /* Global font size for script rows */
  :root {{ --script-font: {ss.get('font_px', 28)}px; }}

  /* Hamburger above title (only when inputs are hidden) */
  .fab-wrap {{
    position: fixed; top: 24px; left: 16px; z-index: 9999;
  }}
  .fab-wrap button {{
    width: 42px; height: 42px; border-radius: 10px;
    font-size: 22px; font-weight: 700; padding: 0; line-height: 1;
    text-align: center;
  }}

  /* ====== SCRIPT AREA ONLY ====== */
  #scripts .row-btn > button {{
    width: 100%;
    text-align: left;
    padding: 10px 0;
    background: transparent;
    border: 0;
    box-shadow: none;
  }}
  #scripts .row-btn > button div p {{
    margin: 0;
    white-space: pre-wrap; word-break: break-word;
    font-size: var(--script-font);
    line-height: 1.55;
  }}
  #scripts .row-sep {{
    height: 1px;
    background: rgba(255,255,255,0.10);
    margin: 4px 0 12px 0;
  }}
  #scripts .dim > button div p {{ opacity: .45; }}
</style>
""", unsafe_allow_html=True)

# ---------- HAMBURGER (place above title) ----------
if not ss.left_visible:
    st.markdown('<div class="fab-wrap">', unsafe_allow_html=True)
    if st.button("≡", key="hamburger_show_inputs"):
        ss.left_visible = True
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- TITLE ----------
st.title("🎙️ SimBrief → VFR/IFR Radio Scripts")

# ---------- LAYOUT ----------
if ss.left_visible:
    col_left, col_right = st.columns([0.95, 2.05], gap="large")
else:
    col_right = st.container()
    col_left = None

# ---------- LEFT PANEL ----------
if ss.left_visible:
    with col_left:
        top_cols = st.columns([1, 0.45])
        with top_cols[0]:
            st.markdown("#### Inputs")
        with top_cols[1]:
            if st.button("⮜ Hide", key="btn_hide_left", use_container_width=True):
                ss.left_visible = False
                st.rerun()

        sim_id = st.text_input("SimBrief ID (username or numeric Pilot ID)", value="548969")
        include_vfr = st.checkbox("Output VFR", value=True)
        include_ifr = st.checkbox("Output IFR", value=True)
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
                ss.vals = extract_fields(mode, payload)
                st.success("Fetched OFP and extracted fields.")
                # reset line states on new fetch
                for k in list(ss.keys()):
                    if k.startswith("vfr_done_") or k.startswith("ifr_done_"):
                        del ss[k]
            except Exception as e:
                ss.vals = None
                st.error(f"Failed to fetch/extract OFP: {e}")

        with st.expander("Extracted fields (debug)", expanded=False):
            if ss.vals:
                st.json(ss.vals)
            else:
                st.caption("Nothing fetched yet.")

# ---------- RIGHT (SCRIPTS) ----------
with col_right:
    vals = ss.vals
    if not vals:
        st.info("Enter SimBrief ID and click **Fetch & Build Scripts** in the inputs panel.")
    else:
        # fallback getter when left panel is hidden
        def get(k, default):
            return locals()[k] if (ss.left_visible and (k in locals())) else default

        vfr_text = ifr_text = ""
        if not ss.left_visible or get("include_vfr", True):
            vfr_text = build_vfr(
                vals,
                get("hold", "A1"),
                get("wind", "240/12"),
                get("atis", "Alpha"),
                get("qnh", "1013"),
                get("alt", "2400"),
                get("dep_rwy_fb", "27"),
                get("arr_rwy_fb", "27"),
                get("pos", "over Grafham Water VRP"),
                get("timez", "1522"),
                get("next_pt", "St Neots VRP"),
                get("eta", "1530"),
                get("dist_dir", "8 miles south"),
            )

        if not ss.left_visible or get("include_ifr", True):
            ifr_text = build_ifr(
                vals,
                get("hold", "A1"),
                get("wind", "240/12"),
                get("atis", "Alpha"),
                get("qnh", "1013"),
                get("clevel", "6000"),
                get("squawk", "4721"),
                get("alt", "2400"),
                get("dep_rwy_fb", "27"),
                get("arr_rwy_fb", "27"),
            )

        def set_expand(kind: str):
            ss.expanded_script = None if ss.expanded_script == kind else kind

        # ---- Row renderer: full-width button rows (toggle dim) ----
        def render_rows(script_text: str, kind: str):
            if not script_text:
                return
            rows = [ln.strip() for ln in script_text.split("\n") if ln.strip()]
            st.caption(f"{len(rows)} calls")

            for i, ln in enumerate(rows):
                state_key = f"{kind}_done_{i}"
                done = ss.get(state_key, False)
                row_class = "dim" if done else ""
                st.markdown(f"<div class='row-btn {row_class}'>", unsafe_allow_html=True)
                # use_container_width + type=secondary keeps it subtle and wide
                if st.button(ln, key=f"{kind}_btn_{i}", use_container_width=True, type="secondary"):
                    ss[state_key] = not done
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("<div class='row-sep'></div>", unsafe_allow_html=True)

        # ---- Script box with controls ----
        def script_box(title: str, text: str, kind: str):
            if not text:
                return

            c1, c2, c3, c4, c5 = st.columns([1.4, 1.1, 1.7, 0.7, 0.7])
            with c1:
                st.subheader(title)
            with c2:
                if ss.expanded_script == kind:
                    if st.button("Restore split", key=f"restore_{kind}", use_container_width=True):
                        set_expand(kind); st.rerun()
                else:
                    if st.button(f"Expand {kind.upper()}", key=f"expand_{kind}", use_container_width=True):
                        set_expand(kind); st.rerun()
            with c3:
                st.download_button(
                    f"Download {kind.upper()} (.txt)",
                    data=text,
                    file_name=f"{kind.upper()}_script.txt",
                    mime="text/plain",
                    key=f"dl_{kind}",
                    use_container_width=True,
                )
            # A− / A+ control the single global font size
            with c4:
                if st.button("A−", key=f"dec_{kind}", type="secondary", use_container_width=True):
                    ss["font_px"] = max(16, ss["font_px"] - 2); st.rerun()
            with c5:
                if st.button("A+", key=f"inc_{kind}", type="secondary", use_container_width=True):
                    ss["font_px"] = min(48, ss["font_px"] + 2); st.rerun()

            render_rows(text, kind)

        # Scope the script area for CSS
        st.markdown("<div id='scripts'>", unsafe_allow_html=True)

        if ss.expanded_script in (None, "vfr"):
            script_box("VFR Script", vfr_text, "vfr")
            st.markdown("<div style='margin:.25rem 0'></div>", unsafe_allow_html=True)
        if ss.expanded_script in (None, "ifr"):
            script_box("IFR Script", ifr_text, "ifr")

        st.markdown("</div>", unsafe_allow_html=True)

        # Combined download
        if vfr_text or ifr_text:
            combined = ""
            if vfr_text:
                combined += "=== VFR Script ===\n" + vfr_text + "\n\n"
            if ifr_text:
                combined += "=== IFR Script ===\n" + ifr_text
            st.download_button(
                "Download Combined (.txt)",
                data=combined,
                file_name="RT_Scripts.txt",
                mime="text/plain",
                key="dl_both",
                use_container_width=True,
            )
