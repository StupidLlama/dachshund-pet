"""自動更新（pet/updater.py）：版本比較、查 GitHub（本機假伺服器）、下載解壓、換檔腳本。  python tests/test_updater.py"""
import io
import json
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
from pet import updater as U  # noqa: E402

# ---- 版本
assert U.parse_version("v0.4.10") == (0, 4, 10) and U.parse_version("junk") == ()
assert U.is_newer("v0.4.10", "0.4.9") and U.is_newer("v0.5", "0.4.9") and not U.is_newer("v0.4", "0.4.0")
assert not U.is_newer("v0.4.4", "0.4.4") and not U.is_newer("", "0.4.4")
print("ok - version compare")

# ---- 假 GitHub
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("DachshundPet/DachshundPet.exe", b"MZ fake")
    z.writestr("DachshundPet/assets/icon.png", b"png")
ZIP = buf.getvalue()
state = {"tag": "v9.9.9", "asset": True}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/latest":
            port = self.server.server_address[1]
            assets = [{"name": U.ASSET_NAME, "size": len(ZIP), "browser_download_url": f"http://127.0.0.1:{port}/zip"}] if state["asset"] else []
            body = json.dumps({"tag_name": state["tag"], "body": "## New\n- Bigger tomato", "assets": assets, "html_url": "x"}).encode()
        else:
            body = ZIP
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
api = f"http://127.0.0.1:{srv.server_address[1]}/latest"

info = U.check(api=api)
assert info and info["tag"] == "v9.9.9" and "Bigger tomato" in info["notes"]
assert U.check(skip="v9.9.9", api=api) is None                  # 按過 Skip
state["tag"] = "v" + U.__version__
assert U.check(api=api) is None                                 # 已經是最新
state.update(tag="v9.9.9", asset=False)
assert U.check(api=api) is None                                 # Release 還沒有 zip
state["asset"] = True
try:
    U.check(api="http://127.0.0.1:1/nothing")
    failed = False
except Exception:
    failed = True                                               # 連不上 → 例外（app 用 Background 接住）
assert failed
print("ok - check: newer / skip / up to date / no zip / offline")

# ---- 下載 + 解壓 + 換檔腳本
work = Path(tempfile.mkdtemp())
seen = []
new_dir = U.download(info, progress=lambda d, t: seen.append((d, t)), workdir=work)
assert (new_dir / "DachshundPet.exe").read_bytes() == b"MZ fake" and (new_dir / "assets" / "icon.png").exists()
assert seen and seen[-1] == (len(ZIP), len(ZIP)) and not (work / U.ASSET_NAME).exists()
bat = U.write_swap_script(new_dir, Path("C:/Pets/DachshundPet"), 1234)
txt = bat.read_text(encoding="mbcs" if sys.platform == "win32" else "utf-8")
assert bat.parent == work and 'PID eq 1234' in txt and f'robocopy "{new_dir}"' in txt and "DachshundPet.exe" in txt
assert f'rmdir /s /q "{work}"' in txt
print("ok - download, unzip, swap script")

# ---- Background
job = U.Background(U.check, "", api=api)
while not job.done:
    pass
assert job.result and job.result["tag"] == "v9.9.9" and job.error is None
job = U.Background(U.download, info, progress=None, workdir=Path(tempfile.mkdtemp()))
while not job.done:
    pass
assert job.result and job.progress[0] == len(ZIP)
print("ok - background jobs")
print("ALL UPDATER TESTS PASSED")
