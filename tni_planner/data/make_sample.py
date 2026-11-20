"""Generates data/sample_project.json - illustrative numbers only."""
import json, copy, pathlib

S = lambda n, h, hs=None, ws=None: {"name": n, "duration_h": h, "limits": {"hs_max": hs, "ws_max": ws}}

ports = {
    "Eemshaven": {"name": "Eemshaven", "location": {"lat": 53.45, "lon": 6.83}, "day_rate_eur": 15000, "fixed_cost_eur": 1500000},
    "Esbjerg": {"name": "Esbjerg", "location": {"lat": 55.47, "lon": 8.44}, "day_rate_eur": 18000, "fixed_cost_eur": 500000},
    "Rotterdam": {"name": "Rotterdam", "location": {"lat": 51.95, "lon": 4.03}, "day_rate_eur": 12000, "fixed_cost_eur": 0},
}
vessels = {
    "HLV-A": {"name": "HLV-A", "type": "Floating HLV (DP)", "transit_speed_kn": 10, "day_rate_eur": 380000, "mob_demob_eur": 4000000, "deck_capacity": 4},
    "JUV-M": {"name": "JUV-M", "type": "Jack-up (foundations)", "transit_speed_kn": 9, "day_rate_eur": 230000, "mob_demob_eur": 2500000, "deck_capacity": 3},
    "WTIV-1": {"name": "WTIV-1", "type": "Jack-up WTIV", "transit_speed_kn": 11, "day_rate_eur": 290000, "mob_demob_eur": 3000000, "deck_capacity": 4},
    "WTIV-2": {"name": "WTIV-2", "type": "Jack-up WTIV (next-gen)", "transit_speed_kn": 12, "day_rate_eur": 340000, "mob_demob_eur": 3500000, "deck_capacity": 6},
    "CLV-1": {"name": "CLV-1", "type": "Cable lay vessel", "transit_speed_kn": 11, "day_rate_eur": 130000, "mob_demob_eur": 1200000, "deck_capacity": 12},
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
       "load_steps": [S("spool cable", 3, None, None)], "transit_limits": {"hs_max": 3.0, "ws_max": 18},
       "install_steps": [S("1st end pull-in", 8, 1.5, 12), S("surface lay", 10, 2.5, 15), S("2nd end pull-in", 8, 1.5, 12)],
       "infield_move_h": 1}
wtg = {"id": "WTG", "name": "WTG installation", "component": "Wind turbine", "quantity": N,
       "vessel": "WTIV-1", "port": "Eemshaven", "after": "MP", "lag_days": 0,
       "load_steps": [S("load-out WTG set", 12, None, 12)], "transit_limits": {"hs_max": 2.5, "ws_max": 15},
       "install_steps": [S("jack-up", 4, 1.8, 12), S("tower", 6, None, 12), S("nacelle", 7, None, 10),
                         S("blades (3x)", 12, None, 10), S("jack-down", 3, 1.8, 12)],
       "infield_move_h": 2}

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
pathlib.Path(__file__).with_name("sample_project.json").write_text(json.dumps(project, indent=2))
