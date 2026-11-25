import argparse
import json
import os
import socket
import threading

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

SR = 48000
PRESETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")

RANGES = {
    "hp": (20, 2000, 1),
    "drive": (0, 48, 0.5),
    "hard": (0, 1, 1),
    "clip": (1, 100, 1),
    "hold": (1, 32, 1),
    "bits": (2, 16, 1),
    "lp": (500, 20000, 50),
    "vol": (-40, 12, 0.5),
    "bypass": (0, 1, 1),
}

PRESETS = {
    "limpio": {"hp": 20, "drive": 0, "hard": 0, "clip": 100, "hold": 1, "bits": 16, "lp": 20000, "vol": 0, "bypass": 0},
    "saturado": {"hp": 90, "drive": 20, "hard": 0, "clip": 60, "hold": 1, "bits": 12, "lp": 11000, "vol": -4, "bypass": 0},
    "earrape": {"hp": 180, "drive": 42, "hard": 1, "clip": 15, "hold": 3, "bits": 4, "lp": 7000, "vol": 0, "bypass": 0},
    "lofi": {"hp": 250, "drive": 8, "hard": 0, "clip": 80, "hold": 5, "bits": 7, "lp": 3800, "vol": 0, "bypass": 0},
    "telefono": {"hp": 450, "drive": 14, "hard": 1, "clip": 55, "hold": 2, "bits": 9, "lp": 3200, "vol": -2, "bypass": 0},
    "robot": {"hp": 120, "drive": 16, "hard": 1, "clip": 40, "hold": 14, "bits": 3, "lp": 9000, "vol": -6, "bypass": 0},
}


class Params:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = dict(PRESETS["earrape"])
        self.user = {}
        self.load_user()

    def all_presets(self):
        return {**PRESETS, **self.user}

    def set(self, key, value):
        if key not in RANGES:
            return
        lo, hi, _ = RANGES[key]
        v = min(max(float(value), lo), hi)
        if key in ("hard", "hold", "bits", "bypass"):
            v = int(round(v))
        with self.lock:
            self.values[key] = v

    def apply(self, name):
        p = self.all_presets().get(name)
        if p:
            for k, v in p.items():
                self.set(k, v)

    def snapshot(self):
        with self.lock:
            return dict(self.values)

    def load_user(self):
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.user = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            self.user = {}

    def save_user(self, name):
        name = name.strip()[:32]
        if not name or name in PRESETS:
            return False
        self.user[name] = self.snapshot()
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.user, f, indent=2, ensure_ascii=False)
        return True


class FXChain:
    def __init__(self, params, sr=SR):
        self.params = params
        self.sr = sr
        self.cache = params.snapshot()
        self.hp_val = None
        self.lp_val = None
        self.hold_val = 0.0
        self.hold_phase = 0

    def _design(self, p):
        nyq = self.sr / 2
        if p["hp"] != self.hp_val:
            self.hp_val = p["hp"]
            self.hp_sos = butter(2, min(p["hp"], nyq * 0.95) / nyq, "highpass", output="sos")
            self.hp_zi = sosfilt_zi(self.hp_sos) * 0.0
        if p["lp"] != self.lp_val:
            self.lp_val = p["lp"]
            self.lp_sos = butter(4, min(p["lp"], nyq * 0.95) / nyq, "lowpass", output="sos")
            self.lp_zi = sosfilt_zi(self.lp_sos) * 0.0

    def _sample_hold(self, x, n):
        if n <= 1:
            self.hold_phase = 0
            return x
        if self.hold_phase >= n:
            self.hold_phase = 0
        idx = np.arange(len(x))
        src = idx - (self.hold_phase + idx) % n
        y = np.where(src >= 0, x[np.maximum(src, 0)], self.hold_val)
        if len(x):
            last = src[-1]
            self.hold_val = x[last] if last >= 0 else self.hold_val
        self.hold_phase = (self.hold_phase + len(x)) % n
        return y

    def process(self, x):
        if self.params.lock.acquire(blocking=False):
            self.cache = dict(self.params.values)
            self.params.lock.release()
        p = self.cache
        x = np.nan_to_num(np.asarray(x, dtype=np.float64))
        self._design(p)
        y, self.hp_zi = sosfilt(self.hp_sos, x, zi=self.hp_zi)
        if p["bypass"]:
            self.lp_zi = self.lp_zi * 0.0
            return np.clip(x, -1.0, 1.0).astype(np.float32)
        y = y * 10 ** (p["drive"] / 20)
        c = max(p["clip"] / 100.0, 0.01)
        if p["hard"]:
            y = np.clip(y, -c, c) / c
        else:
            y = np.tanh(y / c)
        y = self._sample_hold(y, int(p["hold"]))
        q = 2 ** (int(p["bits"]) - 1)
        y = np.round(y * q) / q
        y, self.lp_zi = sosfilt(self.lp_sos, y, zi=self.lp_zi)
        y = y * 10 ** (p["vol"] / 20)
        return np.clip(np.nan_to_num(y), -1.0, 1.0).astype(np.float32)


PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mic FX</title>
<style>
:root{--bg:#111;--fg:#eee;--ac:#ff3b3b;--card:#1d1d1d}
*{box-sizing:border-box}
body{margin:0;padding:14px;font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg)}
h1{margin:0 0 12px;font-size:22px}
.presets{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-bottom:14px}
button{padding:14px 6px;border:0;border-radius:10px;background:var(--card);color:var(--fg);font-size:15px;font-weight:600}
button.on{background:var(--ac)}
.row{background:var(--card);border-radius:10px;padding:10px 12px;margin-bottom:8px}
.lab{display:flex;justify-content:space-between;font-size:14px;margin-bottom:4px}
.val{font-weight:700;color:var(--ac)}
input[type=range]{width:100%;height:32px;accent-color:var(--ac)}
.save{display:flex;gap:8px;margin-top:12px}
.save input{flex:1;padding:12px;border-radius:10px;border:0;background:var(--card);color:var(--fg);font-size:15px}
</style></head><body>
<h1>Mic FX</h1>
<div class="presets" id="pr"></div>
<div id="sl"></div>
<div class="save"><input id="nm" placeholder="nombre preset"><button onclick="save()">Guardar</button></div>
<script>
const R=%RANGES%,N={hp:"Pasa-altos Hz",drive:"Drive dB",hard:"Clip duro",clip:"Umbral clip %",hold:"Hold (SR÷)",bits:"Bits",lp:"Pasa-bajos Hz",vol:"Volumen dB",bypass:"Bypass"};
let t={};
function post(u,d){return fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)}).then(r=>r.json())}
function render(s){
 const pr=document.getElementById("pr");pr.innerHTML="";
 Object.keys(s.presets).forEach(n=>{const b=document.createElement("button");b.textContent=n;
  b.onclick=()=>{post("/preset",{name:n}).then(x=>{render(x);[...pr.children].forEach(c=>c.classList.toggle("on",c.textContent==n))})};pr.appendChild(b)});
 const sl=document.getElementById("sl");
 if(!sl.children.length){for(const k in R){const [lo,hi,st]=R[k];const d=document.createElement("div");d.className="row";
  d.innerHTML=`<div class="lab"><span>${N[k]}</span><span class="val" id="v_${k}"></span></div><input type="range" id="s_${k}" min="${lo}" max="${hi}" step="${st}">`;
  sl.appendChild(d);const i=d.querySelector("input");
  i.oninput=()=>{document.getElementById("v_"+k).textContent=i.value;clearTimeout(t[k]);t[k]=setTimeout(()=>post("/set",{[k]:+i.value}),30)}}}
 for(const k in s.params){const i=document.getElementById("s_"+k);if(i){i.value=s.params[k];document.getElementById("v_"+k).textContent=s.params[k]}}
}
function save(){const n=document.getElementById("nm").value;if(n)post("/save",{name:n}).then(render)}
fetch("/state").then(r=>r.json()).then(render);
</script></body></html>"""


def make_app(params):
    from flask import Flask, jsonify, request

    app = Flask(__name__)
    page = PAGE.replace("%RANGES%", json.dumps(RANGES))

    def state():
        return jsonify(params=params.snapshot(), presets=params.all_presets())

    @app.get("/")
    def index():
        return page

    @app.get("/state")
    def get_state():
        return state()

    @app.post("/set")
    def set_params():
        for k, v in (request.get_json(silent=True) or {}).items():
            try:
                params.set(k, v)
            except (TypeError, ValueError):
                pass
        return state()

    @app.post("/preset")
    def preset():
        params.apply((request.get_json(silent=True) or {}).get("name", ""))
        return state()

    @app.post("/save")
    def save():
        params.save_user(str((request.get_json(silent=True) or {}).get("name", "")))
        return state()

    return app


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def parse_dev(v):
    if v is None:
        return None
    return int(v) if v.isdigit() else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--block", type=int, default=512)
    a = ap.parse_args()

    import sounddevice as sd

    if a.list:
        print(sd.query_devices())
        return

    params = Params()
    fx = FXChain(params)

    def callback(indata, outdata, frames, time, status):
        y = fx.process(indata[:, 0])
        outdata[:, 0] = y
        outdata[:, 1] = y

    stream = sd.Stream(
        samplerate=SR,
        blocksize=a.block,
        dtype="float32",
        latency="low",
        channels=(1, 2),
        device=(parse_dev(a.inp), parse_dev(a.out)),
        callback=callback,
    )
    app = make_app(params)
    with stream:
        print(f"Panel: http://{local_ip()}:{a.port}")
        app.run(host="0.0.0.0", port=a.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
