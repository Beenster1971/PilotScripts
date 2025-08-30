from pathlib import Path
import re
import json
import threading
from xml.etree import ElementTree as ET

import requests
from flask import Flask, request, render_template_string, make_response
import webview  # pywebview

SIMBRIEF_JSON_URL = "https://www.simbrief.com/api/xml.fetcher.php?{id_type}={id_val}&json=1"
SIMBRIEF_XML_URL  = "https://www.simbrief.com/api/xml.fetcher.php?{id_type}={id_val}"

SIM_ID_DEFAULT = "548969"  # default SimBrief ID
ICAO_RE = re.compile(r"^[A-Za-z]{4}$")

app = Flask(__name__)

# ---------- Helpers ----------
def norm_icao(v: str) -> str:
    """Uppercase and validate 4-letter ICAO; return '' if invalid."""
    if not isinstance(v, str):
        return ""
    s = v.strip().upper()
    return s if ICAO_RE.match(s or "") else ""

def first_nonempty(d, keys):
    for k in keys:
        v = d.get(k, "")
        if isinstance(v, (str, int, float)):
            s = str(v).strip()
            if s:
                return s
    return ""

def deep_find_icao(obj, keys):
    """Depth-first search for keys; return first valid 4-letter ICAO."""
    stack = [obj]
    target = set(keys)
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in target and isinstance(v, (str, int, float)):
                    s = norm_icao(str(v))
                    if s:
                        return s
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""

def xml_find_icao(root, xpaths):
    for xp in xpaths:
        el = root.find(xp)
        if el is not None and (el.text or "").strip():
            s = norm_icao(el.text)
            if s:
                return s
    return ""

def is_numeric(s: str) -> bool:
    return s.isdigit()

def feet_from_cruise(v):
    v = (v or "").upper().strip()
    if not v:
        return ""
    if v.startswith("FL"):
        try:
            return str(int(v[2:]) * 100)
        except Exception:
            return v
    digits = re.sub(r"[^0-9]", "", v)
    return digits or v

def first(d, keys):
    for k in keys:
        v = d.get(k, "")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return ""

def deep_first(obj, keys):
    try_keys = set(keys)
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in try_keys:
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                    if isinstance(v, (int, float)):
                        return str(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""

def xml_first(root, xpaths):
    for xp in xpaths:
        el = root.find(xp)
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""

def callsign_from(flat):
    reg = first(flat, ["registration", "aircraft_registration", "reg"])
    if reg: return reg
    airline = first(flat, ["icao_airline", "airline"])
    flt = first(flat, ["flight_number", "fltnum"])
    if airline and flt: return f"{airline}{flt}"
    typ = first(flat, ["aircraft_icao", "aircraft_icaotype", "aircraftType", "aircraft"])
    return typ or ""

def fetch_ofp(sim_id: str):
    id_type = "userid" if is_numeric(sim_id) else "username"
    url_json = SIMBRIEF_JSON_URL.format(id_type=id_type, id_val=sim_id)
    url_xml  = SIMBRIEF_XML_URL.format(id_type=id_type, id_val=sim_id)

    # Prefer JSON
    try:
        r = requests.get(url_json, timeout=15)
        if r.status_code == 200:
            data = r.json()
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            return ("json", data, pretty)
    except Exception:
        pass

    # Fallback to XML
    r = requests.get(url_xml, timeout=15)
    r.raise_for_status()
    text = r.text
    root = ET.fromstring(r.content)
    return ("xml", root, text)

def extract_fields(mode, payload):
    out = {
        "origin": "", "destination": "", "callsign": "", "cruise_feet": "",
        "sid": "", "dep_rwy": "", "arr_rwy": "", "star": ""
    }

    if mode == "json":
        j = payload
        # Flatten some common nodes
        flat = {}
        for parent in ["general", "origin", "destination", "aircraft", "atc", "params", "navlog"]:
            node = j.get(parent, {})
            if isinstance(node, dict):
                flat.update(node)
        # Also top-level primitives
        flat.update({k: v for k, v in j.items() if isinstance(v, (str, int, float))})

        # Robust origin/destination candidates
        orig_candidates = [
            "depicao","origin_icao","orig_icao","origin","orig","icao_origin",
            "origicao","oicao","originIcao","originICAO"
        ]
        dest_candidates = [
            "arricao","destination_icao","dest_icao","destination","dest","icao_destination",
            "desticao","dicao","destinationIcao","destinationICAO"
        ]

        # 1) Try flat dict
        o = norm_icao(first_nonempty(flat, orig_candidates))
        d = norm_icao(first_nonempty(flat, dest_candidates))

        # 2) Deep search if needed (handles nested variations)
        if not o:
            o = deep_find_icao(j, orig_candidates)
        if not d:
            d = deep_find_icao(j, dest_candidates)

        out["origin"] = o
        out["destination"] = d

        # Cruise
        cruise = first_nonempty(flat, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"])
        if not cruise:
            cruise = deep_find_icao(j, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"])  # returns '' if not 4 letters; fine
        out["cruise_feet"] = feet_from_cruise(cruise)

        # SID/RWY/STAR
        out["sid"]     = first_nonempty(flat, ["sid","sid_name","departure_sid"]) or deep_first(j, ["sid","sid_name","departure_sid"])
        out["dep_rwy"] = first_nonempty(flat, ["dep_rwy","departure_runway","runway_dep"]) or deep_first(j, ["dep_rwy","departure_runway","runway_dep"])
        out["arr_rwy"] = first_nonempty(flat, ["arr_rwy","arrival_runway","runway_arr"]) or deep_first(j, ["arr_rwy","arrival_runway","runway_arr"])
        out["star"]    = first_nonempty(flat, ["star","star_name","arrival_star"]) or deep_first(j, ["star","star_name","arrival_star"])

        # Callsign
        out["callsign"] = callsign_from(flat)
        return out

    # --- XML path ---
    root = payload
    out["origin"] = xml_find_icao(root, [
        "general/depicao","origin","origin_icao","depairport_icao","originICAO"
    ])
    out["destination"] = xml_find_icao(root, [
        "general/arricao","destination","destination_icao","arrairport_icao","destinationICAO"
    ])

    # Cruise
    out["cruise_feet"] = feet_from_cruise(
        xml_first(root, ["general/cruise_altitude","cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"])
    )

    # SID/STAR/RWY
    out["sid"]     = xml_first(root, ["sid","sid_name","departure_sid"])
    out["dep_rwy"] = xml_first(root, ["dep_rwy","departure_runway","departure/runway"])
    out["arr_rwy"] = xml_first(root, ["arr_rwy","arrival_runway","arrival/runway"])
    out["star"]    = xml_first(root, ["star","star_name","arrival_star"])

    # Callsign
    reg    = xml_first(root, ["registration","aircraft/registration"])
    airline= xml_first(root, ["icao_airline","airline"])
    fltnum = xml_first(root, ["flight_number","fltnum"])
    typ    = xml_first(root, ["aircraft/icao","aircraftType","aircraft/icaotype"])
    if reg:
        out["callsign"] = reg
    elif airline and fltnum:
        out["callsign"] = f"{airline}{fltnum}"
    else:
        out["callsign"] = typ
    return out

# ---------- Script Builders ----------
def _phrase_alt(alt: str) -> str:
    """Ensure altitude reads naturally. If numeric, append 'feet'."""
    s = (alt or "").strip()
    if not s:
        return s
    # keep if user already wrote units or a flight level
    if re.search(r"(ft|feet|FL)", s, flags=re.IGNORECASE):
        return s
    # numeric only? add 'feet'
    if re.fullmatch(r"\d{2,5}", s):
        return f"{s} feet"
    return s

def build_vfr(v, hold, wind, atis_word, qnh, alt, dep_rwy, arr_rwy,
              pos, timez, next_pt, eta, dist_dir):
    AC  = v["callsign"]
    DEP = v["origin"]
    ARR = v["destination"]
    DR  = v["dep_rwy"] or dep_rwy
    AR  = v["arr_rwy"] or arr_rwy
    # prefer cruise_feet if present, else manual; then phrase it
    ALT = _phrase_alt(v["cruise_feet"] or alt)

    return "\n".join([
        f"{DEP} Tower, {AC}, VFR to {ARR}, with Information {atis_word}, request taxi.",
        f"{AC}, taxi to holding point {hold}, runway {DR}. (Read back clearance as issued.)",
        f"{DEP} Tower, {AC}, ready for departure, runway {DR}, VFR to {ARR}.",
        f"{AC}, lining up / taking off runway {DR}, surface wind {wind}, cleared for take-off.",
        f"{DEP} Tower, {AC}, leaving the zone, climbing to {ALT}, request frequency change.",
        f"{AC}, {pos}, {timez} Zulu, {ALT}, next {next_pt} (ETA {eta}).",
        f"{ARR} Information / Tower, {AC}, {dist_dir} from {ARR}, VFR, request join, QNH {qnh}.",
        f"{AC}, downwind / base / final, runway {AR}.",
        f"{AC}, cleared to land, runway {AR}, surface wind {wind}, QNH {qnh}.",
        f"{ARR} Ground, {AC}, runway vacated, request taxi to parking.",
    ])

def build_ifr(v, hold, wind, atis_word, qnh, clevel, squawk, alt, dep_rwy, arr_rwy):
    AC, DEP, ARR = v["callsign"], v["origin"], v["destination"]
    DR = v["dep_rwy"] or dep_rwy
    AR = v["arr_rwy"] or arr_rwy
    sid = v["sid"] or "(SID N/A)"
    return "\n".join([
        f"{DEP} DELIVERY, {AC}, IFR TO {ARR}, WITH Information {atis_word}, REQUEST CLEARANCE.",
        f"{AC}, CLEARED TO {ARR} VIA {sid}, CLIMB {clevel} FEET, SQUAWK {squawk}.",
        f"{DEP} GROUND, {AC}, REQUEST TAXI RUNWAY {DR}.",
        f"{DEP} TOWER, {AC}, READY RUNWAY {DR}.",
        f"{AC}, CLEARED FOR TAKE-OFF RUNWAY {DR}, WIND {wind}.",
        f"{ARR} APPROACH, {AC}, INFORMATION {atis_word}, REQUEST APPROACH.",
        f"{AC}, CLEARED APPROACH RUNWAY {AR}, DESCEND {alt} FEET, QNH {qnh}.",
        f"{ARR} TOWER, {AC}, FINAL RUNWAY {AR}.",
    ])

# ---------- UI Template (unchanged style; per-panel expand/collapse) ----------
TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>SimBrief → RT Scripts</title>
  <style>
    :root{
      --bg:#0b1220; --panel:#0f1a2f; --border:#1e2a44; --muted:#9fb0d4; --text:#e8eefc; --accent:#2e7df6;
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}
    header{padding:14px 20px;background:#111a2b;border-bottom:1px solid var(--border)}
    h1{margin:0;font-size:18px;font-weight:600}
    .container{padding:18px 20px;display:flex;flex-direction:column;gap:14px;min-height:calc(100vh - 54px)}
    .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px}
    label{display:block;font-size:13px;color:var(--muted);margin:6px 0 6px}
    input[type=text]{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #2a3b62;background:#0b1430;color:var(--text)}
    .row{display:flex;gap:16px;flex-wrap:wrap;align-items:center}
    .btn{display:inline-flex;align-items:center;gap:6px;padding:9px 12px;border-radius:10px;background:var(--accent);color:#fff;border:0;cursor:pointer;text-decoration:none;font-size:13px}
    .btn.secondary{background:#263556}
    .small{font-size:12px;color:var(--muted)}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    .fields-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}
    .field{display:flex;flex-direction:column}
    .controls{display:flex;gap:8px;flex-wrap:wrap}
    /* Scripts area layout */
    .scripts-wrap{display:flex;flex-direction:column;gap:12px;min-height:300px}
    .scripts-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;flex:1;min-height:0}
    .script-card{display:flex;flex-direction:column;min-height:0}
    .script-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
    .script-title{margin:0;font-size:15px;font-weight:600;color:var(--text)}
    .script-actions{display:flex;gap:6px}
    .icon-btn{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:8px;padding:6px 8px;cursor:pointer}
    .icon-btn:hover{border-color:#375083;color:#c8d5f2}
    pre{background:#0b1430;border:1px solid #2a3b62;padding:12px;border-radius:10px;overflow:auto;white-space:pre-wrap;line-height:1.35;font-size:14px;flex:1;min-height:0}
    /* Expand states */
    body.expand-vfr .scripts-grid{grid-template-columns:1fr}
    body.expand-vfr .ifr-card{display:none}
    body.expand-ifr .scripts-grid{grid-template-columns:1fr}
    body.expand-ifr .vfr-card{display:none}
    body.expand-vfr .vfr-card pre,
    body.expand-ifr .ifr-card pre{font-size:18px}
    /* Keep things visible when expanded: let scripts area consume the space */
    .top-section{display:flex;flex-direction:column;gap:14px}
    @media (max-width:1100px){
      .grid2{grid-template-columns:1fr}
    }
    /* Full-window overlay for expanded script */
    .overlay{
    position:fixed; inset:0; z-index:9999;
    background: rgba(5, 10, 20, 0.92);
    display:none; align-items:center; justify-content:center;
    }
    .overlay.show{ display:flex; }
    .overlay-inner{
    width:min(1100px, 96vw);
    height:min(92vh, 980px);
    background: var(--panel);
    border:1px solid var(--border);
    border-radius:14px;
    display:flex; flex-direction:column; padding:14px;
    }
    .overlay-header{
    display:flex; align-items:center; justify-content:space-between;
    margin-bottom:10px;
    }
    .overlay-header h3{ margin:0; font-size:16px; font-weight:600; color:var(--text); }
    .overlay-actions{ display:flex; gap:8px; }
    .overlay pre{
    flex:1; min-height:0; margin:0;
    background:#0b1430; border:1px solid #2a3b62;
    border-radius:10px; padding:14px;
    overflow:auto; white-space:pre-wrap; line-height:1.4;
    font-size:18px;  /* default bigger font in overlay */
    }
  </style>
  <script>
    function expandVFR(){
      document.body.classList.remove('expand-ifr');
      document.body.classList.toggle('expand-vfr');
    }
    function expandIFR(){
      document.body.classList.remove('expand-vfr');
      document.body.classList.toggle('expand-ifr');
    }
    function restoreSplit(){
      document.body.classList.remove('expand-vfr','expand-ifr');
    }
    function openOverlay(kind){
        const overlay = document.getElementById('expandOverlay');
        const pre = document.getElementById('overlayPre');
        const title = document.getElementById('overlayTitle');
        const src = document.getElementById(kind === 'vfr' ? 'vfr_text_pre' : 'ifr_text_pre');
        if (!src) return;
        pre.textContent = src.textContent; // copy the script text
        title.textContent = (kind === 'vfr') ? 'VFR Script (Expanded)' : 'IFR Script (Expanded)';
        overlay.classList.add('show');
    }
    function closeOverlay(){
        document.getElementById('expandOverlay').classList.remove('show');
    }
    function increaseFont(){
        const pre = document.getElementById('overlayPre');
        const style = window.getComputedStyle(pre);
        const cur = parseFloat(style.fontSize) || 18;
        pre.style.fontSize = (cur + 2) + 'px';
    }
    function decreaseFont(){
        const pre = document.getElementById('overlayPre');
        const style = window.getComputedStyle(pre);
        const cur = parseFloat(style.fontSize) || 18;
        pre.style.fontSize = Math.max(12, cur - 2) + 'px';
    }
  </script>
</head>
<body>
<header><h1>🎙️ SimBrief → VFR/IFR Radio Scripts</h1></header>
<div class="container">
  <form method="post" class="top-section">
    <div class="grid2">
      <div class="card">
        <h3 style="margin:0 0 10px 0;">Inputs</h3>
        <label>SimBrief ID (username or numeric Pilot ID)</label>
        <input type="text" name="sim_id" value="{{sim_id or ''}}" required />
        <div class="row" style="margin-top:6px">
          <label><input type="checkbox" name="include_vfr" value="1" {% if include_vfr %}checked{% endif %}/> Output VFR</label>
          <label><input type="checkbox" name="include_ifr" value="1" {% if include_ifr %}checked{% endif %}/> Output IFR</label>
        </div>
      </div>
      <div class="card">
        <h3 style="margin:0 0 10px 0;">Manual fields (not in OFP)</h3>
        <div class="fields-grid">
          {% for k,lab,val in manual_fields %}
          <div class="field">
            <label>{{lab}}</label>
            <input type="text" name="{{k}}" value="{{val}}"/>
          </div>
          {% endfor %}
        </div>
        <p class="small" style="margin-top:8px">ATIS expects the phonetic word (e.g. <em>Alpha</em>, <em>Bravo</em>, <em>Charlie</em>). Fallback runways are used if the OFP doesn't contain runways.</p>
      </div>
    </div>

    <div class="controls">
      <button class="btn" type="submit">Fetch & Build Scripts</button>
      {% if scripts_ready %}
        <a class="btn secondary" href="/download?kind=both&{{dl_qs}}">Download Combined (.txt)</a>
        {% if vfr_text %}<a class="btn secondary" href="/download?kind=vfr&{{dl_qs}}">Download VFR (.txt)</a>{% endif %}
        {% if ifr_text %}<a class="btn secondary" href="/download?kind=ifr&{{dl_qs}}">Download IFR (.txt)</a>{% endif %}
      {% endif %}
    </div>
  </form>

  {% if fields %}
  <div class="card">
    <h3 style="margin:0 0 10px 0;">Extracted Fields</h3>
    <pre style="margin:0">{{fields}}</pre>
  </div>
  {% endif %}

  {% if vfr_text or ifr_text %}
  <div class="scripts-wrap">
    <div class="scripts-grid">
      {% if vfr_text %}
      <div class="card script-card vfr-card">
        <div class="script-header">
          <h3 class="script-title">VFR Script</h3>
          <div class="script-actions">
            <button class="icon-btn" type="button" title="Expand VFR (fill app)" onclick="openOverlay('vfr')">⤢</button>
            <button class="icon-btn" type="button" title="Restore split view" onclick="restoreSplit()">⤡</button>
          </div>
        </div>
        <pre id="vfr_text_pre">{{vfr_text}}</pre>
      </div>
      {% endif %}

      {% if ifr_text %}
      <div class="card script-card ifr-card">
        <div class="script-header">
          <h3 class="script-title">IFR Script</h3>
          <div class="script-actions">
            <button class="icon-btn" type="button" title="Expand IFR (fill app)" onclick="openOverlay('ifr')">⤢</button>
            <button class="icon-btn" type="button" title="Restore split view" onclick="restoreSplit()">⤡</button>
          </div>
        </div>
        <pre id="ifr_text_pre">{{ifr_text}}</pre>
      </div>
      {% endif %}
    </div>
  </div>
  {% endif %}
</div>
<!-- Full-window overlay for expanded script -->
<div id="expandOverlay" class="overlay" aria-hidden="true">
  <div class="overlay-inner">
    <div class="overlay-header">
      <h3 id="overlayTitle">Script</h3>
      <div class="overlay-actions">
        <button type="button" class="icon-btn" onclick="decreaseFont()">A−</button>
        <button type="button" class="icon-btn" onclick="increaseFont()">A+</button>
        <button type="button" class="icon-btn" onclick="closeOverlay()">✕</button>
      </div>
    </div>
    <pre id="overlayPre"></pre>
  </div>
</div>
</body>
</html>
"""

def build_manual_fields(ctx):
    return [
        ("hold", "Holding Point", ctx["hold"]),
        ("wind", "Surface Wind", ctx["wind"]),
        ("atis", "ATIS (phonetic word, e.g. Alpha)", ctx["atis"]),
        ("qnh", "QNH (hPa)", ctx["qnh"]),
        ("clevel", "Initial Cleared Level (feet)", ctx["clevel"]),
        ("squawk", "Squawk", ctx["squawk"]),
        ("alt", "Enroute/Join Altitude (e.g. 2400 or 2400 feet)", ctx["alt"]),
        ("dep_rwy_fb", "Fallback Departure Runway", ctx["dep_rwy_fb"]),
        ("arr_rwy_fb", "Fallback Arrival Runway", ctx["arr_rwy_fb"]),
        # New UK-style VFR call items
        ("pos", "Present Position (e.g. over Grafham Water VRP)", ctx["pos"]),
        ("time", "Time (UTC hhmm)", ctx["time"]),
        ("next_pt", "Next Reporting Point", ctx["next_pt"]),
        ("eta", "ETA to Next Point (hhmm)", ctx["eta"]),
        ("dist_dir", "Distance/Direction from Arrival (e.g. 8 miles south)", ctx["dist_dir"]),
    ]


@app.route("/", methods=["GET","POST"])
def index():
    ctx = {
        "sim_id": SIM_ID_DEFAULT,
        "include_vfr": True, "include_ifr": True,
        "hold":"A1","wind":"240/12","atis":"Alpha","qnh":"1013",
        "clevel":"6000","squawk":"4721","alt":"2400",
        "dep_rwy_fb":"27","arr_rwy_fb":"27",
        # NEW manual VFR placeholders:
        "pos":"(e.g. over Grafham Water VRP)",
        "time":"(hhmm)",
        "next_pt":"(e.g. St Neots VRP)",
        "eta":"(hhmm)",
        "dist_dir":"(e.g. 8 miles south)"
    }
    vfr_text, ifr_text, fields = "","",""
    scripts_ready = False

    if request.method=="POST":
        # SimBrief ID
        ctx["sim_id"] = request.form.get("sim_id", ctx["sim_id"]).strip() or SIM_ID_DEFAULT
        # Checkboxes (explicit handling)
        ctx["include_vfr"] = ("include_vfr" in request.form)
        ctx["include_ifr"] = ("include_ifr" in request.form)
        # Manual fields
        for k in ["hold","wind","atis","qnh","clevel","squawk","alt","dep_rwy_fb","arr_rwy_fb","pos","time","next_pt","eta","dist_dir"]:
            ctx[k] = request.form.get(k, ctx[k]).strip()

        try:
            mode,payload,raw = fetch_ofp(ctx["sim_id"])
            vals = extract_fields(mode,payload)
            fields = json.dumps(vals, indent=2)
            if ctx["include_vfr"]:
                vfr_text = build_vfr(
                    vals,
                    ctx["hold"], ctx["wind"], ctx["atis"], ctx["qnh"], ctx["alt"],
                    ctx["dep_rwy_fb"], ctx["arr_rwy_fb"],
                    ctx["pos"], ctx["time"], ctx["next_pt"], ctx["eta"], ctx["dist_dir"]
                )
            if ctx["include_ifr"]:
                ifr_text = build_ifr(vals, ctx["hold"], ctx["wind"], ctx["atis"], ctx["qnh"], ctx["clevel"], ctx["squawk"], ctx["alt"], ctx["dep_rwy_fb"], ctx["arr_rwy_fb"])
            scripts_ready = bool(vfr_text or ifr_text)
        except Exception as e:
            fields=f"Error: {e}"
            scripts_ready = False

        # Build querystring for download links
        from urllib.parse import urlencode
        dl_qs = urlencode(dict(
            sim_id=ctx["sim_id"],
            include_vfr=int(ctx["include_vfr"]),
            include_ifr=int(ctx["include_ifr"]),
            hold=ctx["hold"], wind=ctx["wind"], atis=ctx["atis"], qnh=ctx["qnh"],
            clevel=ctx["clevel"], squawk=ctx["squawk"], alt=ctx["alt"],
            dep_rwy_fb=ctx["dep_rwy_fb"], arr_rwy_fb=ctx["arr_rwy_fb"]
        ))
        manual_fields = build_manual_fields(ctx)
        return render_template_string(TEMPLATE, **ctx, vfr_text=vfr_text, ifr_text=ifr_text,
                                      fields=fields, scripts_ready=scripts_ready,
                                      manual_fields=manual_fields, dl_qs=dl_qs)

    # GET
    manual_fields = build_manual_fields(ctx)
    return render_template_string(TEMPLATE, **ctx, vfr_text="", ifr_text="",
                                  fields="", scripts_ready=False, manual_fields=manual_fields, dl_qs="")

# No OS fullscreen; pywebview API kept minimal for future use if needed
class Api:
    def __init__(self): self._win=None
    def toggle_fullscreen(self):
        if webview.windows: webview.windows[0].toggle_fullscreen()
    def exit_fullscreen(self):
        if webview.windows: webview.windows[0].toggle_fullscreen()

def run_flask(port):
    import logging; logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run("127.0.0.1", port, debug=False, use_reloader=False)

def find_free_port(base=8000):
    import socket
    for p in range(base, base+50):
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1",p)); return p
        except: continue
    return base

if __name__=="__main__":
    port=find_free_port()
    t=threading.Thread(target=run_flask,args=(port,),daemon=True); t.start()
    api=Api()
    webview.create_window(
        "SimBrief RT Scripts",
        url=f"http://127.0.0.1:{port}/",
        width=1200,
        height=850,
        js_api=api
    )
    webview.start(gui='edgechromium', http_server=False, debug=False)

