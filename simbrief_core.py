# simbrief_core.py
import re, json
from xml.etree import ElementTree as ET
import requests

SIMBRIEF_JSON_URL = "https://www.simbrief.com/api/xml.fetcher.php?{id_type}={id_val}&json=1"
SIMBRIEF_XML_URL  = "https://www.simbrief.com/api/xml.fetcher.php?{id_type}={id_val}"

ICAO_RE = re.compile(r"^[A-Za-z]{4}$")

def is_numeric(s: str) -> bool:
    return s.isdigit()

def norm_icao(v: str) -> str:
    if not isinstance(v, str): return ""
    s = v.strip().upper()
    return s if ICAO_RE.match(s or "") else ""

def feet_from_cruise(v):
    v = (v or "").upper().strip()
    if not v: return ""
    if v.startswith("FL"):
        try: return str(int(v[2:]) * 100)
        except Exception: return v
    digits = re.sub(r"[^0-9]", "", v)
    return digits or v

def first_nonempty(d, keys):
    for k in keys:
        v = d.get(k, "")
        if isinstance(v, (str, int, float)):
            s = str(v).strip()
            if s: return s
    return ""

def deep_first(obj, keys):
    try_keys = set(keys)
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in try_keys and isinstance(v, (str, int, float)):
                    s = str(v).strip()
                    if s: return s
                if isinstance(v, (dict, list)): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""

def deep_find_icao(obj, keys):
    stack = [obj]; target = set(keys)
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in target and isinstance(v, (str, int, float)):
                    s = norm_icao(str(v))
                    if s: return s
                if isinstance(v, (dict, list)): stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""

def xml_first(root, xpaths):
    for xp in xpaths:
        el = root.find(xp)
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""

def xml_find_icao(root, xpaths):
    for xp in xpaths:
        el = root.find(xp)
        if el is not None and (el.text or "").strip():
            s = norm_icao(el.text)
            if s: return s
    return ""

def callsign_from(flat):
    reg = first_nonempty(flat, ["registration", "aircraft_registration", "reg"])
    if reg: return reg
    airline = first_nonempty(flat, ["icao_airline", "airline"])
    flt = first_nonempty(flat, ["flight_number", "fltnum"])
    if airline and flt: return f"{airline}{flt}"
    typ = first_nonempty(flat, ["aircraft_icao", "aircraft_icaotype", "aircraftType", "aircraft"])
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
            return ("json", data, json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        pass
    # Fallback XML
    r = requests.get(url_xml, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return ("xml", root, r.text)

def extract_fields(mode, payload):
    out = {"origin":"", "destination":"", "callsign":"", "cruise_feet":"",
           "sid":"", "dep_rwy":"", "arr_rwy":"", "star":""}
    if mode == "json":
        j = payload
        flat = {}
        for parent in ["general", "origin", "destination", "aircraft", "atc", "params", "navlog"]:
            node = j.get(parent, {})
            if isinstance(node, dict): flat.update(node)
        flat.update({k:v for k,v in j.items() if isinstance(v,(str,int,float))})

        orig_candidates = ["depicao","origin_icao","orig_icao","origin","orig","icao_origin",
                           "origicao","oicao","originIcao","originICAO"]
        dest_candidates = ["arricao","destination_icao","dest_icao","destination","dest","icao_destination",
                           "desticao","dicao","destinationIcao","destinationICAO"]

        o = norm_icao(first_nonempty(flat, orig_candidates)) or deep_find_icao(j, orig_candidates)
        d = norm_icao(first_nonempty(flat, dest_candidates)) or deep_find_icao(j, dest_candidates)

        out["origin"], out["destination"] = o, d
        cruise = first_nonempty(flat, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"]) \
                 or deep_first(j, ["cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"])
        out["cruise_feet"] = feet_from_cruise(cruise)

        out["sid"]     = first_nonempty(flat, ["sid","sid_name","departure_sid"]) or deep_first(j, ["sid","sid_name","departure_sid"])
        out["dep_rwy"] = first_nonempty(flat, ["dep_rwy","departure_runway","runway_dep"]) or deep_first(j, ["dep_rwy","departure_runway","runway_dep"])
        out["arr_rwy"] = first_nonempty(flat, ["arr_rwy","arrival_runway","runway_arr"]) or deep_first(j, ["arr_rwy","arrival_runway","runway_arr"])
        out["star"]    = first_nonempty(flat, ["star","star_name","arrival_star"]) or deep_first(j, ["star","star_name","arrival_star"])
        out["callsign"]= callsign_from(flat)
        return out

    # XML
    root = payload
    out["origin"]      = xml_find_icao(root, ["general/depicao","origin","origin_icao","depairport_icao","originICAO"])
    out["destination"] = xml_find_icao(root, ["general/arricao","destination","destination_icao","arrairport_icao","destinationICAO"])
    out["cruise_feet"] = feet_from_cruise(xml_first(root, ["general/cruise_altitude","cruise_altitude","cruise_level","initial_altitude","planned_cruise_altitude"]))
    out["sid"]         = xml_first(root, ["sid","sid_name","departure_sid"])
    out["dep_rwy"]     = xml_first(root, ["dep_rwy","departure_runway","departure/runway"])
    out["arr_rwy"]     = xml_first(root, ["arr_rwy","arrival_runway","arrival/runway"])
    out["star"]        = xml_first(root, ["star","star_name","arrival_star"])

    reg    = xml_first(root, ["registration","aircraft/registration"])
    airline= xml_first(root, ["icao_airline","airline"])
    fltnum = xml_first(root, ["flight_number","fltnum"])
    typ    = xml_first(root, ["aircraft/icao","aircraftType","aircraft/icaotype"])
    out["callsign"] = reg or (f"{airline}{fltnum}" if airline and fltnum else typ)
    return out

# UK/EU VFR phrasing
def _phrase_alt(alt: str) -> str:
    s = (alt or "").strip()
    if not s: return s
    if re.search(r"(ft|feet|FL)", s, flags=re.IGNORECASE): return s
    if re.fullmatch(r"\d{2,5}", s): return f"{s} feet"
    return s

def build_vfr(v, hold, wind, atis_word, qnh, alt, dep_rwy, arr_rwy,
              pos, timez, next_pt, eta, dist_dir):
    AC, DEP, ARR = v["callsign"], v["origin"], v["destination"]
    DR = v["dep_rwy"] or dep_rwy
    AR = v["arr_rwy"] or arr_rwy
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
