# streamlit_app.py
import html
import streamlit as st
from simbrief_core import fetch_ofp, extract_fields, build_vfr, build_ifr

st.set_page_config(page_title="SimBrief → VFR/IFR Scripts", layout="wide")

# --- state
ss = st.session_state
ss.setdefault("vals", None)
ss.setdefault("expanded_script", None)   # None | 'vfr' | 'ifr'
ss.setdefault("font_vfr", 18)           # px default a bit larger
ss.setdefault("font_ifr", 18)           # px
ss.setdefault("left_visible", True)     # show/hide inputs panel
ss.setdefault("done_vfr", set())        # indices of completed VFR rows
ss.setdefault("done_ifr", set())        # indices of completed IFR rows

# --- styles (FAB position fixed so it's not clipped; row visuals + wrapping)
st.markdown("""
<style>
  .block-container { padding-top: 0.8rem; padding-bottom: 0.5rem; }
  /* Floating hamburger — drop below Streamlit header so it's never clipped */
  .fab {
    position: fixed; top: 68px; left: 14px; z-index: 9999;
    background: #2e7df6; color: #fff; border-radius: 10px;
    padding: 10px 14px; font-weight: 600; cursor: pointer;
    box-shadow: 0 2px 10px rgba(0,0,0,.35); user-select: none;
  }
  .fab:hover { filter: brightness(1.05); }
  .tight-row { margin-top: .25rem; margin-bottom: .25rem; }
  /* Script rows */
  .call-row {
    display: flex; gap: 10px; align-items: flex-start;
    padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.08);
  }
  .call-row:last-child { border-bottom: 0; }
  .call-btn > button {
    min-width: 40px; padding: 0.45rem 0.6rem; font-size: 1.05rem;
  }
  .call-text {
    flex: 1 1 auto; white-space: pre-wrap; word-break: break-word;
  }
  .call-dim { opacity: 0.45; }
</style>
""", unsafe_allow_html=True)

# Floating hamburger when inputs hidden
if not ss.left_visible:
    # the following button exists just to trigger a Streamlit action; we click it via the FAB div
    if st.button("≡  Inputs", key="fab_open", help="Show inputs", type="primary"):
        ss.left_visible = True
        st.rerun()
    st.markdown(
        '<div class="fab" onclick="document.querySelector(\'button[aria-label=\\\'fab_open\\\']\').click()">≡ Inputs</div>',
        unsafe_allow_html=True
    )

st.title("🎙️ SimBrief → VFR/IFR Radio Scripts")

# Layout: either full-width scripts or 2 columns
if ss.left_visible:
    col_left, col_right = st.columns([0.95, 2.05], gap="large")
else:
    col_right = st.container()
    col_left = None

# --------------- LEFT PANEL ---------------
if ss.left_visible:
    with col_left:
        top_cols = st.columns([1, 0.45])
        with top_cols[0]:
            st.markdown("#### Inputs")
        with top_cols[1]:
            if st.button("⮜ Hide", key="btn_hide_left", use_container_width=True, help="Hide inputs panel"):
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
                # reset completion marks on new fetch
                ss.done_vfr = set()
                ss.done_ifr = set()
            except Exception as e:
                ss.vals = None
                st.error(f"Failed to fetch/extract OFP: {e}")

        with st.expander("Extracted fields (debug)", expanded=False):
            if ss.vals: st.json(ss.vals)
            else: st.caption("Nothing fetched yet.")

# --------------- RIGHT PANEL (SCRIPTS) ---------------
with col_right:
    vals = ss.vals
    if not vals:
        st.info("Enter SimBrief ID and click **Fetch & Build Scripts** in the inputs panel.")
    else:
        # Use last-known inputs if left panel hidden (so scripts still render)
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

        def set_expand(kind: str):
            ss.expanded_script = (None if ss.expanded_script == kind else kind)

        def render_rows(text: str, kind: str, font_px: int):
            """
            Render each radio line as a tappable row:
            - Subtle divider between rows
            - Tap button dims/undims the line (toggle)
            - Text wraps and respects font size
            """
            if not text: return
            rows = [ln.strip() for ln in text.split("\n") if ln.strip()]
            done_set = ss.done_vfr if kind == "vfr" else ss.done_ifr

            # Reset/clear controls
            cA, cB, cC = st.columns([1, .8, .8])
            with cA: st.caption(f"{len(rows)} calls")
            with cB:
                if st.button("Reset marks", key=f"reset_{kind}", use_container_width=True):
                    done_set.clear(); st.rerun()
            with cC:
                if st.button("Mark all", key=f"markall_{kind}", use_container_width=True):
                    done_set.clear(); done_set.update(range(len(rows))); st.rerun()

            for i, ln in enumerate(rows):
                c1, c2 = st.columns([0.12, 0.88])
                with c1:
                    lab = "✓" if i in done_set else "•"
                    if st.container().button(lab, key=f"btn_{kind}_{i}", help="Tap to toggle", use_container_width=True):
                        if i in done_set: done_set.remove(i)
                        else: done_set.add(i)
                        st.rerun()
                with c2:
                    safe = html.escape(ln)
                    dim = " call-dim" if i in done_set else ""
                    st.markdown(
                        f"""<div class="call-row">
                                <div class="call-text{dim}" style="font-size:{font_px}px; line-height:1.55;">{safe}</div>
                            </div>""",
                        unsafe_allow_html=True
                    )

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

            # the new row-based renderer
            render_rows(text, kind, ss[font_key])

        if ss.expanded_script in (None, 'vfr'):
            script_box("VFR Script", vfr_text, "vfr")
            st.markdown("<div class='tight-row'></div>", unsafe_allow_html=True)
        if ss.expanded_script in (None, 'ifr'):
            script_box("IFR Script", ifr_text, "ifr")

        # Combined download
        if vfr_text or ifr_text:
            combined = ""
            if vfr_text: combined += "=== VFR Script ===\n" + vfr_text + "\n\n"
            if ifr_text: combined += "=== IFR Script ===\n" + ifr_text
            st.download_button("Download Combined (.txt)", data=combined, file_name="RT_Scripts.txt",
                               mime="text/plain", key="dl_both", use_container_width=True)
