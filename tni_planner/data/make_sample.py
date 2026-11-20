"""Generates data/sample_project.json - illustrative numbers only."""
import json, copy, pathlib

def S(n, h, hs=None, ws=None, uc=None, group=False, rate=None, pos="start"):
    d = {"name": n, "duration_h": h, "limits": {"hs_max": hs, "ws_max": ws, "uc_max": uc},
         "group_with_next": group, "position": pos}
    if rate:
        d["rate_m_per_h"] = rate
    return d

ports = {
    "Eemshaven": {"name": "Eemshaven", "location": {"lat": 53.45, "lon": 6.83}},
    "Esbjerg": {"name": "Esbjerg", "location": {"lat": 55.47, "lon": 8.44}},
    "Rotterdam": {"name": "Rotterdam", "location": {"lat": 51.95, "lon": 4.03}},
}
vessels = {
    "HLV-A": {"name": "HLV-A", "type": "Floating HLV (DP)", "transit_speed_kn": 10, "day_rate_eur": 380000, "deck_capacity": 4},
    "JUV-M": {"name": "JUV-M", "type": "Jack-up (foundations)", "transit_speed_kn": 9, "day_rate_eur": 230000, "deck_capacity": 3},
    "WTIV-1": {"name": "WTIV-1", "type": "Jack-up WTIV", "transit_speed_kn": 11, "day_rate_eur": 290000, "deck_capacity": 4},
    "WTIV-2": {"name": "WTIV-2", "type": "Jack-up WTIV (next-gen)", "transit_speed_kn": 12, "day_rate_eur": 340000, "deck_capacity": 6},
    "CLV-1": {"name": "CLV-1", "type": "Cable lay vessel", "transit_speed_kn": 11, "day_rate_eur": 130000, "deck_capacity": 12},
}
N = 60
mp_hlv = {"id": "MP", "name": "Monopile installation", "component": "Foundation", "quantity": N,
          "vessel": "HLV-A", "port": "Rotterdam", "start_date": "2028-04-01",
          "load_steps": [S("load-out MP", 6, None, 15)], "transit_limits": {"hs_max": 3.0, "ws_max": 18},
          "install_steps": [S("upend & set", 5, 1.75, 12), S("pile driving", 8, 2.0, 15), S("noise mitigation retrieval", 2, 2.0, 15)],
          "infield_move_h": 2}
mp_jup = copy.deepcopy(mp_hlv) | {"vessel": "JUV-M", "port": "Eemshaven",
          "install_steps": [S("jack-up", 4, 1.8, 12), S("upend & set", 5, None, 12), S("pile driving", 8, None, 15), S("jack-down", 3, 1.8, 12)]}
cab = {"id": "IAC", "name": "Array cable installation", "component": "Array cable", "quantity": N,
       "vessel": "CLV-1", "port": "Rotterdam", "after": "MP", "lag_days": -30,
       # Activity list follows the ABPmer IAC template (durations per cable section)
       "load_steps": [S("cable load-out (per section)", 6, None, 16)], "transit_limits": {"hs_max": None, "ws_max": 15},
       # Positions & freelay length per cable come from the RPL (data/samples/sample-demo-iac.csv)
       "rpl": "sample-demo-iac",
       "install_steps": [S("pre pull-in survey", 2, 2.5, 15, 0.75), S("first end pull-in", 2, 2.0, 15, 0.75, True),
                         S("achieve overpull & secure temporary hang-off", 0.5, 2.0, 15, None, True),
                         S("freelay", 7.7, 2.5, 15, None, True, rate=360), S("cut and seal cable", 4, 2.5, 15, pos="end"),
                         S("second end pull-in", 4, 2.0, 15, 0.75, pos="end")],
       "infield_move_h": 1.5, "infield_speed_kn": 6, "survival_limit": {"hs_max": 3.5, "window_h": 24}}
wtg = {"id": "WTG", "name": "WTG installation", "component": "Wind turbine", "quantity": N,
       "vessel": "WTIV-1", "port": "Eemshaven", "after": "MP", "lag_days": 0,
       "load_steps": [S("load-out WTG set", 12, None, 12)], "transit_limits": {"hs_max": 2.5, "ws_max": 15},
       "install_steps": [S("jack-up", 4, 1.8, 12), S("tower", 6, None, 12), S("nacelle", 7, None, 10),
                         S("blades (3x)", 12, None, 10), S("jack-down", 3, 1.8, 12)],
       "infield_move_h": 2}

def write_rpl():
    """Dummy RPL: OSS west of the array, 10 strings x 6 WTGs, ~1.2 km spacing, slightly curved routes."""
    import math
    site_lat, site_lon = project_site = (54.05, 6.0)
    dlat, dlon = 1.2 / 111.2, 1.2 / (111.2 * math.cos(math.radians(site_lat)))
    oss = (site_lat, site_lon - 4.0 * dlon)
    wtg = lambda r, c: (site_lat + (r - 4.5) * dlat, site_lon + (c - 2.5) * dlon)
    lines = ["cable_id,from,to,lat,lon"]
    for r in range(10):
        prev, prev_name = oss, "OSS"
        for c in range(6):
            cur, name = wtg(r, c), f"WTG-{r+1:02d}{c+1}"
            cid = f"IAC-{r+1:02d}-{c+1}"
            for k in range(5):                         # 5 route points, bowed sideways
                t = k / 4
                lat = prev[0] + (cur[0] - prev[0]) * t + 0.0008 * math.sin(math.pi * t)
                lon = prev[1] + (cur[1] - prev[1]) * t
                lines.append(f"{cid},{prev_name},{name},{lat:.6f},{lon:.6f}")
            prev, prev_name = cur, name
    out = pathlib.Path(__file__).with_name("samples") / "sample-demo-iac.csv"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")


def concept(name, desc, pkgs):
    vs = sorted({p["vessel"] for p in pkgs}); ps = sorted({p["port"] for p in pkgs})
    return {"name": name, "description": desc, "ports": [ports[p] for p in ps],
            "vessels": [vessels[v] for v in vs], "packages": pkgs}

project = {
    "name": "Demo OWF 900 MW", "site": {"lat": 54.05, "lon": 6.0},
    "n_turbines": N, "n_foundations": N, "n_cables": N,
    "weather": "synthetic", "hindcast_years": 20, "percentile": 50,
    "concepts": [
        concept("C1 HLV + WTIV Eemshaven", "Floating HLV monopiles from Rotterdam; WTGs from Eemshaven",
                [mp_hlv, cab, wtg]),
        concept("C2 HLV + next-gen WTIV Esbjerg", "As C1 but larger WTIV loading 6 sets from Esbjerg",
                [mp_hlv, cab, wtg | {"vessel": "WTIV-2", "port": "Esbjerg"}]),
        concept("C3 Jack-up foundations", "Monopiles by jack-up from Eemshaven; WTGs from Eemshaven",
                [mp_jup, cab, wtg]),
    ],
}
write_rpl()
pathlib.Path(__file__).with_name("sample_project.json").write_text(json.dumps(project, indent=2))
