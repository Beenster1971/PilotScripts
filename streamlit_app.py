# streamlit_app.py
import html
import streamlit as st
from simbrief_core import fetch_ofp, extract_fields, build_vfr, build_ifr

st.set_page_config(page_title="SimBrief → VFR/IFR Scripts", layout="wide")

# --- state
ss = st.session_state
ss.setdefault("vals", None)
ss.setdefault("expanded_script", None)   # None | 'vfr' | 'ifr'
ss.setdefault("font_vfr", 18)
ss.setdefault("font_ifr", 18)
ss.setdefault("left_visible", True)

# --- global styles
st.markdown("""
<style>
  .block-container { padding-top: 0.8rem; padding-bottom: 0.5rem; }

  /* Fixed hamburger (native Streamlit button inside a fixed wrapper) */
  .fab-wrap { position: fixed; top: 66px; left: 14px; z-index: 9999; }
  .fab-wrap button {
    width: 42px; height: 42px; border-radius: 10px;
    font-size: 22px; font-weight: 700;
    padding: 0; line-height: 1; text-align: center;
  }

  /* Single-column call rows using the checkbox widget */
  /* Each row is a checkbox widget container */
  [data-testid="stCheckbox"] {
    border-bottom: 1px solid rgba(255,255,255,0.10);
    margin: 0; padding: 10px 0;
  }
  /* Hide the stock checkbox box, keep it focusable/clickable */
  [data-testid="stCheckbox"] input[type="checkbox"] {
    position: absolute; opacity: 0; width: 0; height: 0;
  }
  /* Label becomes the full-width row hit-target */
  [data-testid="stCheckbox"] label {
    display: block; width: 100%; cursor: pointer; margin: 0;
  }
  /* Streamlit wraps label text in a <p> – we style it for font/line-height */
  [data-testid="stCheckbox"] label p {
    margin: 0; white-space: pre-wrap; word-break: break-word;
  }

  /* “Dim” a completed row */
  [data-testid="stCheckbox"]:has(input:checked) { opacity: 0.45; }

  /* Optional: hover affordance */
  [data-testid="stCheckbox"] label:hover { filter: brightness(1.04); }
</style>
""", unsafe_allow_html=True)

# ---------- FAB (only when inputs hidden) ----------
def fab():
    st.markdown(
        '<div class="fab" onclick="document.querySelector(\'button[aria-label=\\\'fab_open\\\']\').click()">≡</div>',
        unsafe_allow_html=True
    )

# invisible button used by the FAB to trigger a Streamlit action (no extra visible UI)
if not ss.left_visible:
    if st.button("open_inputs", key="fab_open", help="Show inputs", type="primary"):
        ss.left_visible = True
        st.rerun()
    fab()

st.title("🎙️ SimBrief → VFR/IFR Radio Scripts")

# HAMBURGER – native st.button in a fixed wrapper (always works)
col_hamburger = st.container()
with col_hamburger:
    st.markdown('<div class="fab-wrap">', unsafe_allow_html=True)
    if not st.session_state.get("left_visible", True):
        if st.button("≡", key="show_inputs_hamburger"):
            st.session_state["left_visible"] = True
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- layout
if ss.left_visible:
    col_left, col_right = st.columns([0.95, 2.05], gap="large")
else:
    col_right = st.container()
    col_left = None

# ---------- LEFT PANEL
if ss.left_visible:
    with col_left:
        top_cols = st.columns([1, 0.45])
        with top_cols[0]: st.markdown("#### Inputs")
        with top_cols[1]:
            if st.button("⮜ Hide", key="btn_hide_left", use_container_width=True):
                ss.left_visible = False; st.rerun()

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
            except Exception as e:
                ss.vals = None
                st.error(f"Failed to fetch/extract OFP: {e}")

        with st.expander("Extracted fields (debug)", expanded=False):
            if ss.vals: st.json(ss.vals)
            else: st.caption("Nothing fetched yet.")

# ---------- RIGHT (SCRIPTS)
with col_right:
    vals = ss.vals
    if not vals:
        st.info("Enter SimBrief ID and click **Fetch & Build Scripts** in the inputs panel.")
    else:
        # if inputs hidden, still render scripts using last-known values or sensible defaults
        def get(k, default):
            return locals()[k] if (ss.left_visible and (k in locals())) else default

        vfr_text = ifr_text = ""
        if not ss.left_visible or get("include_vfr", True):
            vfr_text = build_vfr(vals,
                                 get("hold","A1"), get("wind","240/12"), get("atis","Alpha"), get("qnh","1013"),
                                 get("alt","2400"), get("dep_rwy_fb","27"), get("arr_rwy_fb","27"),
                                 get("pos","over Grafham Water VRP"), get("timez","1522"),
                                 get("next_pt","St Neots VRP"), get("eta","1530"), get("dist_dir","8 miles south"))
        if not ss.left_visible or get("include_ifr", True):
            ifr_text = build_ifr(vals,
                                 get("hold","A1"), get("wind","240/12"), get("atis","Alpha"), get("qnh","1013"),
                                 get("clevel","6000"), get("squawk","4721"), get("alt","2400"),
                                 get("dep_rwy_fb","27"), get("arr_rwy_fb","27"))

        # expand logic
        def set_expand(kind: str):
            ss.expanded_script = (None if ss.expanded_script == kind else kind)

        # row renderer using checkboxes as row items (box hidden; label is the row)
        def render_rows(script_text: str, kind: str, font_px: int):
            """
            Render each radio line as a full-width tappable row.
            - Uses native st.checkbox for state (box hidden via CSS).
            - The label is the entire row; tapping toggles 'done'.
            - Wraps text; subtle delimiter between rows.
            """
            if not script_text:
                return
            rows = [ln.strip() for ln in script_text.split("\n") if ln.strip()]
            st.caption(f"{len(rows)} calls")

            # Render one Streamlit checkbox per line (state stored per row key)
            for i, ln in enumerate(rows):
                key = f"{kind}_row_{i}"
                # Force the font-size for this row by injecting a zero-height marker before it
                st.markdown(f"<div style='height:0;font-size:{font_px}px'></div>", unsafe_allow_html=True)
                st.checkbox(ln, key=key)

        def script_box(title: str, text: str, kind: str):
            if not text: return
            expanded = (ss.expanded_script == kind)
            font_key = "font_vfr" if kind == "vfr" else "font_ifr"
            font_px = ss[font_key]

            c1, c2, c3, c4, c5 = st.columns([1.4, 1.1, 1.7, 0.7, 0.7])
            with c1: st.subheader(title)
            with c2:
                if expanded:
                    if st.button("Restore split", key=f"restore_{kind}", use_container_width=True):
                        set_expand(kind); st.rerun()
                else:
                    if st.button(f"Expand {kind.upper()}", key=f"expand_{kind}", use_container_width=True):
                        set_expand(kind); st.rerun()
            with c3:
                st.download_button(
                    f"Download {kind.upper()} (.txt)", data=text,
                    file_name=f"{kind.upper()}_script.txt", mime="text/plain",
                    key=f"dl_{kind}", use_container_width=True
                )
            with c4:
                if st.button("A−", key=f"dec_{kind}", type="secondary", use_container_width=True):
                    ss[font_key] = max(12, font_px - 2); st.rerun()
            with c5:
                if st.button("A+", key=f"inc_{kind}", type="secondary", use_container_width=True):
                    ss[font_key] = min(40, font_px + 2); st.rerun()

            # render as single-column “table” with CSS-toggled rows
            render_rows(text, kind, ss[font_key])

        if ss.expanded_script in (None, 'vfr'):
            script_box("VFR Script", vfr_text, "vfr")
            st.markdown("<div style='margin:.25rem 0'></div>", unsafe_allow_html=True)
        if ss.expanded_script in (None, 'ifr'):
            script_box("IFR Script", ifr_text, "ifr")

        if vfr_text or ifr_text:
            combined = ""
            if vfr_text: combined += "=== VFR Script ===\n" + vfr_text + "\n\n"
            if ifr_text: combined += "=== IFR Script ===\n" + ifr_text
            st.download_button("Download Combined (.txt)", data=combined, file_name="RT_Scripts.txt",
                               mime="text/plain", key="dl_both", use_container_width=True)
