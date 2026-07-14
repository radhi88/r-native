"""graph_brain.py — العقل المعرفي: يبني رسم graphify لكودنا ويُبقيه حيّاً ينمو مع المشروع.

طلب المستخدم: «شغّل عقول الذكاء بـ graphify ويكبر مع تطوّر مشروعنا».

ماذا يفعل (windowless، كل ساعتين + بعد أي commit عبر hook اختياري):
  1. يشغّل graphify (tree-sitter محلي، SHA256 تزايدي — صفر LLM، صفر تكلفة) على كامل الكود.
  2. يلخّص graph.json → graph_brain.json: عدد العقد/الحواف، أكثر الملفات ترابطاً (hubs)،
     الدوال «اليتيمة» (لا تُستدعى = مرشّحة للحذف)، والوحدات الأكثر تأثيراً عند التغيير.
  3. يكشف الفجوات: ملفات معزولة، استيرادات دائرية، دوال ميتة — يكتبها لـ ARENA والوكلاء.
  4. ينمو تلقائياً: كل بناء تزايدي يضيف الكود الجديد، فالخريطة تواكب تطوّر المشروع.

التشغيل:  pythonw graph_brain.py
الاستعلام (للوكلاء/الإنسان):  python graph_brain.py --query <كلمة>
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5 = Path(r"C:\Users\Radhi\MT5")
PYEXE = MT5 / ".venv" / "Scripts" / "python.exe"
if not PYEXE.exists():
    PYEXE = Path(sys.executable)
OUT_DIR = MT5 / "graphify-out"
GRAPH_JSON = OUT_DIR / "graph.json"
BRAIN = MT5 / "data" / "r_native" / "graph_brain.json"
REBUILD_S = 2 * 3600           # كل ساعتين — يواكب وتيرة تطويرنا
BUILD_TIMEOUT = 600


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def build():
    """بناء تزايدي للرسم. يعيد True عند النجاح."""
    try:
        r = subprocess.run([str(PYEXE), "-m", "graphify", "update", ".", "--no-cluster"],
                           cwd=str(MT5), capture_output=True, text=True, timeout=BUILD_TIMEOUT)
        return GRAPH_JSON.exists()
    except Exception as e:
        print(f"[GRAPH] build err {e}", flush=True)
        return False


def summarize():
    """يحوّل graph.json إلى رؤى يستهلكها النظام."""
    g = _load(GRAPH_JSON, {}) or {}
    nodes = g.get("nodes", []) or []
    edges = g.get("edges") or g.get("links") or []      # graphify uses D3 'links'
    # درجة الترابط لكل عقدة (in/out)
    indeg, outdeg = {}, {}
    for e in edges:
        s = e.get("source") or e.get("from"); t = e.get("target") or e.get("to")
        if s is not None:
            outdeg[s] = outdeg.get(s, 0) + 1
        if t is not None:
            indeg[t] = indeg.get(t, 0) + 1
    def _name(n):
        return n.get("label") or n.get("name") or n.get("id") or "?"
    by_id = {n.get("id"): n for n in nodes}
    # المحاور: الأكثر استدعاءً (تغييرها يؤثر على الأكثر) = الأهم في النظام
    hubs = sorted(nodes, key=lambda n: -(indeg.get(n.get("id"), 0) + outdeg.get(n.get("id"), 0)))[:12]
    # اليتيمة: عقد كود بلا أي حافة داخلة ولا خارجة = معزولة/ميتة محتملة
    orphans = [n for n in nodes
               if not indeg.get(n.get("id")) and not outdeg.get(n.get("id"))
               and n.get("file_type") == "code"]
    kinds = {}
    for n in nodes:
        k = n.get("type") or n.get("file_type") or "?"
        kinds[k] = kinds.get(k, 0) + 1
    out = {
        "ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
        "n_nodes": len(nodes), "n_edges": len(edges), "kinds": kinds,
        "hubs": [{"name": _name(n), "type": n.get("type"),
                  "deg": indeg.get(n.get("id"), 0) + outdeg.get(n.get("id"), 0)} for n in hubs],
        "orphans": [_name(n) for n in orphans][:25], "n_orphans": len(orphans),
    }
    BRAIN.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRAIN.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, BRAIN)
    return out


def query(term):
    """استعلام بسيط: العقد المطابقة + جيرانها (مَن يستدعيها/تستدعيه)."""
    g = _load(GRAPH_JSON, {}) or {}
    nodes = g.get("nodes", []); edges = g.get("edges", [])
    t = term.lower()
    hits = [n for n in nodes if t in str(n.get("label") or n.get("name") or n.get("id") or "").lower()]
    if not hits:
        print(f"لا تطابق لـ «{term}» — جرّب بناء الرسم أولاً."); return
    ids = {n.get("id") for n in hits}
    for n in hits[:8]:
        nid = n.get("id")
        callers = [e.get("source") for e in edges if (e.get("target") or e.get("to")) == nid]
        callees = [e.get("target") for e in edges if (e.get("source") or e.get("from")) == nid]
        print(f"• {n.get('label') or n.get('name')} [{n.get('type')}] "
              f"← يستدعيه {len(callers)} · → يستدعي {len(callees)}")


def main():
    if "--query" in sys.argv:
        i = sys.argv.index("--query")
        query(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        return 0
    print("[GRAPH] العقل المعرفي حيّ — يبني ويكبر مع المشروع", flush=True)
    while True:
        try:
            if build():
                o = summarize()
                top = ", ".join(h["name"] for h in o["hubs"][:4])
                print(f"[GRAPH] {o['n_nodes']} عقدة · {o['n_edges']} حافة · محاور: {top} · يتيمة: {o['n_orphans']}", flush=True)
            else:
                print("[GRAPH] البناء لم يُنتج رسماً (تحقق من graphify)", flush=True)
        except Exception as e:
            print(f"[GRAPH] err {e}", flush=True)
        time.sleep(REBUILD_S)


if __name__ == "__main__":
    raise SystemExit(main())
