# simbrief_rtf_webview_app.py (updated)
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

        # Try many common SimBrief keys
        out["origin"] = (
            first(flat, ["origin","origin_icao","orig_icao","depairport_icao","originICAO","depicao","orig","icao_origin"]) or
            deep_first(j, ["origin","origin_icao","orig_icao","depairport_icao","originICAO","depicao","orig","icao_origin"])
        )
        out["destination"] = (
            first(flat, ["destination","destination_icao","dest_icao","arrairport_icao","destinationICAO","arricao","dest","icao_destination"]) or
            deep_first(j, ["destination","destination_icao","dest_icao","arrairport_icao","destinationICAO","arricao","dest","icao_destination"])
        )

        out["cruise_feet"] = feet_from_cruise(
            first(flat, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"]) or
            deep_first(j, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"])
        )
        out["sid"]         = first(flat, ["sid","sid_name","departure_sid"]) or deep_first(j, ["sid","sid_name","departure_sid"])
        out["dep_rwy"]     = first(flat, ["dep_rwy","departure_runway","runway_dep"]) or deep_first(j, ["dep_rwy","departure_runway","runway_dep"])
        out["arr_rwy"]     = first(flat, ["arr_rwy","arrival_runway","runway_arr"]) or deep_first(j, ["arr_rwy","arrival_runway","runway_arr"])
        out["star"]        = first(flat, ["star","star_name","arrival_star"]) or deep_first(j, ["star","star_name","arrival_star"])
        out["callsign"]    = callsign_from(flat)
        return out

    # XML: add more fallbacks including general/depicao & general/arricao
    root = payload
    out["origin"]      = xml_first(root, ["origin","origin_icao","orig_icao","depairport_icao","originICAO","general/depicao"])
    out["destination"] = xml_first(root, ["destination","destination_icao","dest_icao","arrairport_icao","destinationICAO","general/arricao"])
    out["cruise_feet"] = feet_from_cruise(xml_first(root, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude","general/cruise_altitude"]))
    out["sid"]         = xml_first(root, ["sid","sid_name","departure_sid"])
    out["dep_rwy"]     = xml_first(root, ["dep_rwy","departure_runway","runway_dep","departure/runway"])
    out["arr_rwy"]     = xml_first(root, ["arr_rwy","arrival_runway","runway_arr","arrival/runway"])
    out["star"]        = xml_first(root, ["star","star_name","arrival_star"])
    reg   = xml_first(root, ["registration","aircraft/registration"])
    airline = xml_first(root, ["icao_airline","airline"])
    fltnum  = xml_first(root, ["flight_number","fltnum"])
    typ     = xml_first(root, ["aircraft/icao","aircraftType","aircraft/icaotype"])
    if reg:
        out["callsign"] = reg
    elif airline and fltnum:
        out["callsign"] = f"{airline}{fltnum}"
    else:
        out["callsign"] = typ
    return out

def build_vfr(v, hold, wind, atis, qnh, alt, dep_rwy, arr_rwy):
    AC, DEP, ARR = v["callsign"], v["origin"], v["destination"]
    ALT = v["cruise_feet"] or alt
    DR = v["dep_rwy"] or dep_rwy
    AR = v["arr_rwy"] or arr_rwy
    return "\n".join([
        f"DEPARTURE {DEP} TOWER, {AC}, VFR TO {ARR}, WITH {atis}, REQUEST TAXI.",
        f"{AC}, TAXI TO HOLDING POINT {hold} RUNWAY {DR}. (READ BACK CLEARANCE AS ISSUED.)",
        f"{DEP} TOWER, {AC}, READY FOR DEPARTURE, RUNWAY {DR}, VFR TO {ARR}.",
        f"{AC}, LINING UP/TAKING OFF RUNWAY {DR}, SURFACE WIND {wind}, CLEARED FOR TAKE-OFF.",
        f"{DEP} TOWER, {AC}, LEAVING THE ZONE, CLIMBING TO {ALT} FEET, REQUEST FREQUENCY CHANGE.",
        f"{AC}, (POSITION), (TIME), (ALTITUDE/LEVEL), NEXT (REPORTING POINT) (ETA).",
        f"{ARR} INFORMATION/TOWER, {AC}, (DISTANCE/DIRECTION) FROM {ARR}, VFR, REQUEST JOIN, QNH {qnh}.",
        f"{AC}, DOWNWIND/BASE/FINAL RUNWAY {AR}.",
        f"{AC}, CLEARED TO LAND RUNWAY {AR}, SURFACE WIND {wind}, QNH {qnh}.",
        f"{ARR} GROUND, {AC}, RUNWAY VACATED, REQUEST TAXI TO PARKING.",
    ])

def build_ifr(v, hold, wind, atis, qnh, clevel, squawk, alt, dep_rwy, arr_rwy):
    AC, DEP, ARR = v["callsign"], v["origin"], v["destination"]
    DR = v["dep_rwy"] or dep_rwy
    AR = v["arr_rwy"] or arr_rwy
    sid = v["sid"] or "(SID/N/A)"
    starseg = f" VIA {v['star']}" if v["star"] else ""
    return "\n".join([
        f"{DEP} DELIVERY/APPROACH, {AC}, IFR TO {ARR}, WITH {atis}, REQUEST CLEARANCE.",
        f"{AC}, CLEARED TO {ARR} VIA {sid}, CLIMB {clevel} FEET, SQUAWK {squawk}.",
        f"{DEP} GROUND, {AC}, IFR, REQUEST TAXI.",
        f"{AC}, TAXI TO HOLDING POINT {hold} RUNWAY {DR}. (READ BACK CLEARANCE AS ISSUED.)",
        f"{DEP} TOWER, {AC}, READY FOR DEPARTURE RUNWAY {DR}.",
        f"{AC}, AIRBORNE, PASSING (ALTITUDE), CLIMBING {clevel} FEET, CONTACTING DEPARTURE.",
        f"{AC}, (POSITION), (TIME), (FLIGHT LEVEL), NEXT (POINT) (ETA), (FOLLOWING POINT).",
        f"{ARR} APPROACH, {AC}, INFORMATION {atis}, REQUEST (ILS/RNP/VOR) APPROACH{starseg}.",
        f"{AC}, CLEARED (APPROACH TYPE) RUNWAY {AR}, DESCEND TO {alt} FEET, QNH {qnh}.",
        f"{ARR} TOWER, {AC}, FINAL RUNWAY {AR}.",
        f"{ARR} GROUND, {AC}, RUNWAY VACATED, REQUEST TAXI TO STAND/PARKING.",
    ])

# ---------- UI template with layout fixes + maximize toggles ----------
TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>SimBrief → RT Scripts</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 0; background:#0b1220; color:#e8eefc; }
    header { padding: 16px 24px; background: #111a2b; border-bottom: 1px solid #1e2a44; }
    h1 { margin: 0; font-size: 20px; }
    .container { padding: 20px 24px; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .card { background: #0f1a2f; border: 1px solid #1e2a44; border-radius: 12px; padding: 16px; }
    label { display:block; font-size: 13px; color:#a9b8d9; }
    input[type=text] { width: 100%; padding: 10px 12px; border-radius: 8px; border:1px solid #2a3b62; background:#0b1430; color:#e8eefc; margin-top:6px; margin-bottom:10px; }
    .row { display:flex; gap:20px; flex-wrap:wrap; align-items:center; margin-top:6px; }
    .btn { display:inline-block; padding:10px 14px; border-radius:10px; background:#2e7df6; color:white; text-decoration:none; border:0; cursor:pointer; }
    .btn.secondary { background:#263556; }
    .small { font-size:12px; color:#9fb0d4; }
    pre { background:#0b1430; border:1px solid #2a3b62; padding:12px; border-radius:10px; overflow:auto; white-space:pre-wrap; font-size: 14px; line-height: 1.35; }
    table { width:100%; border-collapse: collapse; }
    th, td { text-align:left; border-bottom: 1px solid #1e2a44; padding: 8px; }
    th { color:#9fb0d4; font-weight:600; font-size:13px; }
    .spacer { height: 10px; }
    .fields-grid { display:grid; grid-template-columns: 1fr 1fr; gap:12px 16px; }
    .field { display:flex; flex-direction:column; }
    /* Maximize modes */
    .scripts-grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; align-items:start; }
    body.max-vfr .scripts-grid { grid-template-columns: 1fr; }
    body.max-ifr .scripts-grid { grid-template-columns: 1fr; }
    body.max-vfr .ifr-card { display:none; }
    body.max-ifr .vfr-card { display:none; }
    body.max-vfr pre, body.max-ifr pre { font-size: 18px; }
    .toolbar { display:flex; gap:8px; align-items:center; margin-top:10px; }
  </style>
  <script>
    function toggleMax(which) {
      document.body.classList.remove('max-vfr','max-ifr');
      if (which === 'vfr') {
        if (!document.body.classList.contains('max-vfr')) document.body.classList.add('max-vfr');
      } else if (which === 'ifr') {
        if (!document.body.classList.contains('max-ifr')) document.body.classList.add('max-ifr');
      }
    }
    function clearMax() { document.body.classList.remove('max-vfr','max-ifr'); }
  </script>
</head>
<body>
<header><h1>🎙️ SimBrief → VFR/IFR Radio Scripts</h1></header>
<div class="container">
  <form method="post">
    <div class="grid2">
      <div class="card">
        <h3>Inputs</h3>
        <label>SimBrief ID (username or numeric Pilot ID)</label>
        <input type="text" name="sim_id" value="{{sim_id or ''}}" required />
        <div class="row">
          <label><input type="checkbox" name="include_vfr" value="1" {% if include_vfr %}checked{% endif %}/> Output VFR</label>
          <label><input type="checkbox" name="include_ifr" value="1" {% if include_ifr %}checked{% endif %}/> Output IFR</label>
        </div>
      </div>
      <div class="card">
        <h3>Manual fields (not in OFP)</h3>
        <div class="fields-grid">
          {% for k,lab,val in manual_fields %}
          <div class="field">
            <label>{{lab}}</label>
            <input type="text" name="{{k}}" value="{{val}}"/>
          </div>
          {% endfor %}
        </div>
        <p class="small">Fallback runways are used if OFP doesn't contain runways.</p>
      </div>
    </div>
    <div class="spacer"></div>
    <button class="btn" type="submit">Fetch & Build Scripts</button>
    {% if scripts_ready %}
      <a class="btn secondary" href="/download?kind=both&{{dl_qs}}">Download Combined (.txt)</a>
      {% if vfr_text %}<a class="btn secondary" href="/download?kind=vfr&{{dl_qs}}">Download VFR (.txt)</a>{% endif %}
      {% if ifr_text %}<a class="btn secondary" href="/download?kind=ifr&{{dl_qs}}">Download IFR (.txt)</a>{% endif %}
    {% endif %}
  </form>

  {% if fields %}
  <div class="spacer"></div>
  <div class="card">
    <h3>Extracted Fields</h3>
    <table>
      <thead><tr><th>Field</th><th>Value</th></tr></thead>
      <tbody>
        {% for k, v in fields.items() %}
        <tr><td>{{k}}</td><td>{{v}}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {% if vfr_text or ifr_text %}
  <div class="spacer"></div>
  <div class="toolbar">
    <button type="button" class="btn secondary" onclick="toggleMax('vfr')">Maximise VFR</button>
    <button type="button" class="btn secondary" onclick="toggleMax('ifr')">Maximise IFR</button>
    <button type="button" class="btn" onclick="clearMax()">Reset</button>
  </div>
  <div class="spacer"></div>
  <div class="scripts-grid">
    {% if vfr_text %}
    <div class="card vfr-card">
      <h3>VFR Script</h3>
      <pre>{{vfr_text}}</pre>
    </div>
    {% endif %}
    {% if ifr_text %}
    <div class="card ifr-card">
      <h3>IFR Script</h3>
      <pre>{{ifr_text}}</pre>
    </div>
    {% endif %}
  </div>
  {% endif %}

  {% if raw_payload %}
  <div class="spacer"></div>
  <div class="card">
    <h3>Raw OFP payload (JSON/XML)</h3>
    <pre>{{raw_payload}}</pre>
  </div>
  {% endif %}
</div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    defaults = {
        "include_vfr": True,
        "include_ifr": True,
        "hold": "A1",
        "wind": "220/12KT",
        "atis": "Information A",
        "qnh": "1013",
        "clevel": "6000",
        "squawk": "4721",
        "alt": "4500",
        "dep_rwy_fb": "27",
        "arr_rwy_fb": "27",
    }
    ctx = dict(defaults)
    ctx["sim_id"] = SIM_ID_DEFAULT  # default value

    manual_fields = [
        ("hold", "Holding Point", ctx["hold"]),
        ("wind", "Surface Wind", ctx["wind"]),
        ("atis", "ATIS Code", ctx["atis"]),
        ("qnh", "QNH (hPa)", ctx["qnh"]),
        ("clevel", "Initial Cleared Level (feet)", ctx["clevel"]),
        ("squawk", "Squawk", ctx["squawk"]),
        ("alt", "Approach Altitude (feet)", ctx["alt"]),
        ("dep_rwy_fb", "Fallback Departure Runway", ctx["dep_rwy_fb"]),
        ("arr_rwy_fb", "Fallback Arrival Runway", ctx["arr_rwy_fb"]),
    ]

    if request.method == "POST":
        sim_id = request.form.get("sim_id","").strip() or SIM_ID_DEFAULT
        include_vfr = request.form.get("include_vfr") == "1"
        include_ifr = request.form.get("include_ifr") == "1"

        # Pull manual fields
        for i, (k, lab, _) in enumerate(manual_fields):
            manual_fields[i] = (k, lab, request.form.get(k, defaults[k]).strip())

        ctx.update({
            "sim_id": sim_id,
            "include_vfr": include_vfr,
            "include_ifr": include_ifr,
        })

        vfr_text = ""
        ifr_text = ""
        fields_map = None
        raw_payload = ""

        if sim_id and (include_vfr or include_ifr):
            try:
                mode, payload, pretty_raw = fetch_ofp(sim_id)
                vals = extract_fields(mode, payload)
                fields_map = {
                    "Departure ICAO": vals.get("origin",""),
                    "Arrival ICAO": vals.get("destination",""),
                    "Aircraft Callsign/Reg": vals.get("callsign",""),
                    "Cruise Altitude (feet)": vals.get("cruise_feet",""),
                    "SID": vals.get("sid",""),
                    "Departure Runway": vals.get("dep_rwy",""),
                    "Arrival Runway": vals.get("arr_rwy",""),
                    "STAR": vals.get("star",""),
                }
                # Rehydrate latest manuals
                m = {k:v for (k,_,v) in manual_fields}
                if include_vfr:
                    vfr_text = build_vfr(vals, m["hold"], m["wind"], m["atis"], m["qnh"],
                                         m["alt"], m["dep_rwy_fb"], m["arr_rwy_fb"])
                if include_ifr:
                    ifr_text = build_ifr(vals, m["hold"], m["wind"], m["atis"], m["qnh"],
                                         m["clevel"], m["squawk"], m["alt"],
                                         m["dep_rwy_fb"], m["arr_rwy_fb"])
                raw_payload = pretty_raw
            except requests.HTTPError as e:
                raw_payload = f"HTTP error from SimBrief: {e}"
            except Exception as e:
                raw_payload = f"Unexpected error: {e}"

        # Build querystring for download links
        from urllib.parse import urlencode
        m = {k:v for (k,_,v) in manual_fields}
        dl_qs = urlencode(dict(
            sim_id=ctx["sim_id"],
            include_vfr=int(ctx["include_vfr"]),
            include_ifr=int(ctx["include_ifr"]),
            **m
        ))

        return render_template_string(TEMPLATE,
            sim_id=ctx["sim_id"], include_vfr=ctx["include_vfr"], include_ifr=ctx["include_ifr"],
            manual_fields=manual_fields, scripts_ready=bool(vfr_text or ifr_text),
            vfr_text=vfr_text, ifr_text=ifr_text, fields=fields_map,
            raw_payload=raw_payload, dl_qs=dl_qs
        )

    # GET
    return render_template_string(TEMPLATE,
        sim_id=ctx["sim_id"], include_vfr=ctx["include_vfr"], include_ifr=ctx["include_ifr"],
        manual_fields=manual_fields, scripts_ready=False,
        vfr_text="", ifr_text="", fields=None, raw_payload="", dl_qs=""
    )

@app.route("/download")
def download():
    kind = request.args.get("kind","both")
    sim_id = request.args.get("sim_id","").strip() or SIM_ID_DEFAULT
    include_vfr = request.args.get("include_vfr","1") == "1" if kind in ("both","vfr") else False
    include_ifr = request.args.get("include_ifr","1") == "1" if kind in ("both","ifr") else False

    # Manual fields
    hold = request.args.get("hold","A1")
    wind = request.args.get("wind","220/12KT")
    atis = request.args.get("atis","Information A")
    qnh  = request.args.get("qnh","1013")
    clevel = request.args.get("clevel","6000")
    squawk = request.args.get("squawk","4721")
    alt   = request.args.get("alt","4500")
    dep_rwy_fb = request.args.get("dep_rwy_fb","27")
    arr_rwy_fb = request.args.get("arr_rwy_fb","27")

    content = []
    try:
        mode, payload, _ = fetch_ofp(sim_id)
        vals = extract_fields(mode, payload)
        if include_vfr:
            content.append("=== VFR Script ===\n" + build_vfr(vals, hold, wind, atis, qnh, alt, dep_rwy_fb, arr_rwy_fb))
        if include_ifr:
            content.append("=== IFR Script ===\n" + build_ifr(vals, hold, wind, atis, qnh, clevel, squawk, alt, dep_rwy_fb, arr_rwy_fb))
    except Exception as e:
        content.append(f"Error generating scripts: {e}")

    txt = "\n\n".join(content)
    resp = make_response(txt)
    fname = "RT_Scripts.txt" if kind=="both" else (f"{kind.upper()}_script.txt")
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp

# ---------- Boot (Flask + WebView) ----------
def find_free_port(default=8000):
    import socket
    for p in range(default, default+50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return default

def run_flask(port):
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)  # quiet server logs in UI
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    port = find_free_port(8000)
    t = threading.Thread(target=run_flask, args=(port,), daemon=True)
    t.start()

    # Create window without launching an external browser
    webview.create_window("SimBrief RT Scripts", url=f"http://127.0.0.1:{port}/", width=1200, height=850)
    webview.start()
