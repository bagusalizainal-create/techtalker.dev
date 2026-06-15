"""TechTalkerID Dashboard
Live server monitoring untuk dash.techtalkerid.dev
"""
from flask import Flask, jsonify
import psutil
import platform
import datetime
import socket
import time

app = Flask(__name__)
START = time.time()


@app.route("/")
def index():
    """Tiny HTML dashboard."""
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime = int(time.time() - START)
    sys_uptime = int(time.time() - psutil.boot_time())

    html = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>techtalkerid Dashboard</title>
<meta http-equiv="refresh" content="5">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0a0e1a; color: #cbd5e1; padding: 24px; line-height: 1.5;
  }}
  h1 {{ color: #4ade80; margin-bottom: 8px; font-size: 1.5rem; }}
  .sub {{ color: #64748b; margin-bottom: 24px; font-size: 0.9rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
  .card {{
    background: #131826; border: 1px solid #1e293b; border-radius: 10px;
    padding: 16px;
  }}
  .card h3 {{ font-size: 0.75rem; text-transform: uppercase; color: #64748b; letter-spacing: 1px; margin-bottom: 8px; }}
  .val {{ font-size: 1.6rem; font-weight: 700; color: #e2e8f0; }}
  .small {{ font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }}
  .bar {{
    background: #1e293b; height: 8px; border-radius: 4px; margin-top: 8px; overflow: hidden;
  }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, #4ade80, #22d3ee); transition: width 0.3s; }}
  .warn {{ color: #fbbf24; }} .crit {{ color: #f87171; }}
  .footer {{ margin-top: 24px; text-align: center; color: #475569; font-size: 0.8rem; }}
</style></head><body>
<h1>● Dashboard techtalkerid.dev</h1>
<p class="sub">Live server stats • Auto-refresh setiap 5 detik</p>

<div class="grid">
  <div class="card">
    <h3>CPU</h3>
    <div class="val {'crit' if cpu > 80 else 'warn' if cpu > 50 else ''}">{cpu:.1f}%</div>
    <div class="small">{psutil.cpu_count()} cores</div>
    <div class="bar"><div class="bar-fill" style="width:{cpu}%"></div></div>
  </div>

  <div class="card">
    <h3>Memory</h3>
    <div class="val">{mem.percent:.1f}%</div>
    <div class="small">{mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB</div>
    <div class="bar"><div class="bar-fill" style="width:{mem.percent}%"></div></div>
  </div>

  <div class="card">
    <h3>Disk (/)</h3>
    <div class="val">{disk.percent:.1f}%</div>
    <div class="small">{disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB</div>
    <div class="bar"><div class="bar-fill" style="width:{disk.percent}%"></div></div>
  </div>

  <div class="card">
    <h3>Network (total)</h3>
    <div class="val">↑ {net.bytes_sent // (1024**2)} MB</div>
    <div class="small">↓ {net.bytes_recv // (1024**2)} MB</div>
  </div>

  <div class="card">
    <h3>Hostname</h3>
    <div class="val" style="font-size:1.2rem">{socket.gethostname()}</div>
    <div class="small">{platform.platform()}</div>
  </div>

  <div class="card">
    <h3>Uptime</h3>
    <div class="val">{sys_uptime // 3600}h {(sys_uptime % 3600) // 60}m</div>
    <div class="small">Boot: {boot.strftime('%Y-%m-%d %H:%M')}</div>
  </div>
</div>

<p class="footer">API: <a href="/api/stats" style="color:#22d3ee">/api/stats</a> (JSON)</p>
</body></html>"""
    return html


@app.route("/api/stats")
def stats():
    """JSON endpoint untuk monitoring eksternal / Prometheus."""
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    return jsonify({
        "hostname": socket.gethostname(),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "cpu": {"percent": cpu, "cores": psutil.cpu_count()},
        "memory": {
            "percent": mem.percent,
            "used_mb": mem.used // (1024**2),
            "total_mb": mem.total // (1024**2),
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": disk.used // (1024**3),
            "total_gb": disk.total // (1024**3),
        },
        "network": {
            "bytes_sent_mb": net.bytes_sent // (1024**2),
            "bytes_recv_mb": net.bytes_recv // (1024**2),
        },
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "service_uptime_seconds": int(time.time() - START),
    })


@app.route("/health")
def health():
    return {"status": "ok", "service": "techtalkerid-dash"}
