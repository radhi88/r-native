# -*- coding: utf-8 -*-
"""tv_selftest.py — يختبر جسر TradingView عبر الرابط العام: سرّ صحيح (قبول) + سرّ خاطئ (403).
لا يفتح صفقة (action=ping/symbol=TESTONLY). يكتب النتيجة في data/r_native/tv_selftest_result.json.
"""
import json, urllib.request, time
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5") / "data" / "r_native"
SECRET = "<TV_BRIDGE_SECRET>"
try:
    URL = json.load(open(RN / "tv_tunnel.json", encoding="utf-8"))["webhook"]
except Exception:
    URL = "http://localhost:8025/tv"


def _post(secret):
    body = json.dumps({"secret": secret, "action": "ping", "symbol": "TESTONLY"}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return None, str(e)


res = {"url": URL, "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
c_code, c_body = _post(SECRET)
res["correct_secret"] = {"status": c_code, "body": c_body,
                          "verdict": "PASS (قُبل)" if c_code == 200 else f"UNEXPECTED {c_code}"}
w_code, w_body = _post("WRONG_SECRET_123")
res["wrong_secret"] = {"status": w_code, "body": w_body,
                        "verdict": "PASS (رُفض 403)" if w_code == 403 else f"FAIL توقعنا 403 وجاء {w_code}"}
json.dump(res, open(RN / "tv_selftest_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
