# simbrief_rtf_webview_app.py
# Standalone Windows WebView app (Flask + pywebview)
# Features:
#  - Default SimBrief ID = 548969
#  - Extracts ICAOs properly
#  - ATIS expects phonetic word ("Alpha", "Bravo", etc.)
#  - Fullscreen toggle buttons (true fullscreen, bigger font)

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

app = Flask(__name__)

# ---------- Helpers ----------
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
        flat = {}
        for parent in ["general", "origin", "destination", "aircraft", "atc", "params", "navlog"]:
            node = j.get(parent, {})
            if isinstance(node, dict):
                flat.update(node)
        flat.update({k: v for k, v in j.items() if isinstance(v, (str, int, float))})

        out["origin"] = (
            first(flat, ["origin","origin_icao","orig_icao","depicao"]) or
            deep_first(j, ["origin","origin_icao","orig_icao","depicao"])
        )
        out["destination"] = (
            first(flat, ["destination","destination_icao","dest_icao","arricao"]) or
            deep_first(j, ["destination","destination_icao","dest_icao","arricao"])
        )

        out["cruise_feet"] = feet_from_cruise(
            first(flat, ["cruise_altitude","cruise_level","initial_altitude"]) or
            deep_first(j, ["cruise_altitude","cruise_level","initial_altitude"])
        )
        out["sid"]      = first(flat, ["sid","sid_name","departure_sid"])
        out["dep_rwy"]  = first(flat, ["dep_rwy","departure_runway","runway_dep"])
        out["arr_rwy"]  = first(flat, ["arr_rwy","arrival_runway","runway_arr"])
        out["star"]     = first(flat, ["star","star_name","arrival_star"])
        out["callsign"] = callsign_from(flat)
        return out

    # XML
    root = payload
    out["origin"]      = xml_first(root, ["general/depicao","origin","origin_icao"])
    out["destination"] = xml_first(root, ["general/arricao","destination","destination_icao"])
    out["cruise_feet"] = feet_from_cruise(xml_first(root, ["general/cruise_altitude","cruise_altitude"]))
    out["sid"]         = xml_first(root, ["sid","departure_sid"])
    out["dep_rwy"]     = xml_first(root, ["dep_rwy","departure_runway"])
    out["arr_rwy"]     = xml_first(root, ["arr_rwy","arrival_runway"])
    out["star"]        = xml_first(root, ["star","arrival_star"])
    reg   = xml_first(root, ["registration","aircraft/registration"])
    airline = xml_first(root, ["icao_airline","airline"])
    fltnum  = xml_first(root, ["flight_number","fltnum"])
    typ     = xml_first(root, ["aircraft/icao","aircraftType"])
    if reg:
        out["callsign"] = reg
    elif airline and fltnum:
        out["callsign"] = f"{airline}{fltnum}"
    else:
        out["callsign"] = typ
    return out

# ---------- Script Builders ----------
def build_vfr(v, hold, wind, atis_word, qnh, alt, dep_rwy, arr_rwy):
    AC, DEP, ARR = v["callsign"], v["origin"], v["destination"]
    ALT = v["cruise_feet"] or alt
    DR = v["dep_rwy"] or dep_rwy
    AR = v["arr_rwy"] or arr_rwy
    return "\n".join([
        f"DEPARTURE {DEP} TOWER, {AC}, VFR TO {ARR}, WITH Information {atis_word}, REQUEST TAXI.",
        f"{AC}, TAXI TO HOLDING POINT {hold} RUNWAY {DR}.",
        f"{DEP} TOWER, {AC}, READY FOR DEPARTURE, RUNWAY {DR}, VFR TO {ARR}.",
        f"{AC}, CLEARED FOR TAKE-OFF RUNWAY {DR}, WIND {wind}.",
        f"{DEP} TOWER, {AC}, LEAVING THE ZONE, CLIMBING TO {ALT} FEET.",
        f"{ARR} INFORMATION/TOWER, {AC}, (POSITION), VFR, REQUEST JOIN, QNH {qnh}.",
        f"{AC}, FINAL RUNWAY {AR}.",
        f"{AC}, CLEARED TO LAND RUNWAY {AR}, WIND {wind}, QNH {qnh}.",
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

# ---------- UI Template ----------
TEMPLATE = """
<!doctype html><html><head>
<meta charset="utf-8"/>
<style>
body { background:#0b1220; color:#e8eefc; font-family:sans-serif; margin:0; }
header { padding:12px; background:#111a2b; }
.card { background:#0f1a2f; border:1px solid #1e2a44; border-radius:8px; padding:12px; margin:10px 0; }
pre { white-space:pre-wrap; font-size:14px; background:#0b1430; padding:12px; border-radius:8px; }
.fs pre { font-size:20px; }
.btn { background:#2e7df6; color:white; padding:6px 12px; border-radius:6px; text-decoration:none; margin-right:6px;}
</style>
<script>
function toggleFullscreen(){
  if(window.pywebview && window.pywebview.api && window.pywebview.api.toggle_fullscreen){
    window.pywebview.api.toggle_fullscreen();
  } else {
    if(!document.fullscreenElement){document.documentElement.requestFullscreen();}
    else{document.exitFullscreen();}
  }
  document.body.classList.toggle('fs');
}
function exitFullscreen(){
  if(window.pywebview && window.pywebview.api && window.pywebview.api.exit_fullscreen){
    window.pywebview.api.exit_fullscreen();
  }
  if(document.fullscreenElement){document.exitFullscreen();}
  document.body.classList.remove('fs');
}
</script>
</head><body>
<header><h2>SimBrief → RT Scripts</h2></header>
<div style="padding:12px">
<form method="post">
<div class="card">
<label>SimBrief ID</label>
<input name="sim_id" value="{{sim_id}}" style="width:200px"/>
<label><input type="checkbox" name="include_vfr" value="1" {% if include_vfr %}checked{% endif %}/> VFR</label>
<label><input type="checkbox" name="include_ifr" value="1" {% if include_ifr %}checked{% endif %}/> IFR</label>
</div>
<div class="card">
<label>Holding Point</label><input name="hold" value="{{hold}}"/>
<label>Wind</label><input name="wind" value="{{wind}}"/>
<label>ATIS (phonetic word)</label><input name="atis" value="{{atis}}"/>
<label>QNH</label><input name="qnh" value="{{qnh}}"/>
<label>Cleared Level</label><input name="clevel" value="{{clevel}}"/>
<label>Squawk</label><input name="squawk" value="{{squawk}}"/>
<label>Approach Altitude</label><input name="alt" value="{{alt}}"/>
<label>Dep RWY Fallback</label><input name="dep_rwy_fb" value="{{dep_rwy_fb}}"/>
<label>Arr RWY Fallback</label><input name="arr_rwy_fb" value="{{arr_rwy_fb}}"/>
</div>
<button class="btn" type="submit">Build</button>
<button class="btn" type="button" onclick="toggleFullscreen()">Toggle Fullscreen</button>
<button class="btn" type="button" onclick="exitFullscreen()">Exit Fullscreen</button>
</form>
{% if fields %}
<div class="card">
<h3>Extracted Fields</h3>
<pre>{{fields}}</pre>
</div>
{% endif %}
{% if vfr_text %}
<div class="card"><h3>VFR</h3><pre>{{vfr_text}}</pre></div>
{% endif %}
{% if ifr_text %}
<div class="card"><h3>IFR</h3><pre>{{ifr_text}}</pre></div>
{% endif %}
</div></body></html>
"""

@app.route("/", methods=["GET","POST"])
def index():
    ctx = {
        "sim_id": SIM_ID_DEFAULT,
        "include_vfr": True, "include_ifr": True,
        "hold":"A1","wind":"220/12KT","atis":"Alpha","qnh":"1013",
        "clevel":"6000","squawk":"4721","alt":"4500","dep_rwy_fb":"27","arr_rwy_fb":"27"
    }
    vfr_text, ifr_text, fields = "","",""
    if request.method=="POST":
        for k in ctx: ctx[k] = request.form.get(k, ctx[k])
        try:
            mode,payload,raw = fetch_ofp(ctx["sim_id"])
            vals = extract_fields(mode,payload)
            fields = json.dumps(vals, indent=2)
            if ctx["include_vfr"]: vfr_text = build_vfr(vals, ctx["hold"], ctx["wind"], ctx["atis"], ctx["qnh"], ctx["alt"], ctx["dep_rwy_fb"], ctx["arr_rwy_fb"])
            if ctx["include_ifr"]: ifr_text = build_ifr(vals, ctx["hold"], ctx["wind"], ctx["atis"], ctx["qnh"], ctx["clevel"], ctx["squawk"], ctx["alt"], ctx["dep_rwy_fb"], ctx["arr_rwy_fb"])
        except Exception as e:
            fields=f"Error: {e}"
    return render_template_string(TEMPLATE, **ctx, vfr_text=vfr_text, ifr_text=ifr_text, fields=fields)

# pywebview API
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
    webview.create_window("SimBrief RT Scripts", f"http://127.0.0.1:{port}", width=1100,height=800)
    webview.start(api=api)
