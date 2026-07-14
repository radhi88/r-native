# -*- coding: utf-8 -*-
"""monitor.py — الوكيل المراقب للرسم: كل دورة يبني الطوبولوجيا، يقارنها بالسابقة، ويبلّغ:
الجديد (عُقَد/وصلات)، الفجوات (غير متّصل/محرّك ميت/ملفّ متقادم)، وما اختفى. يكتب graph_report.json
(يقرؤه كلود/الواجهة) + سجلّاً. قراءة-فقط. windowless تحت الوصيّ."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RN = ROOT / "data" / "r_native"
REPORT = RN / "graph_report.json"
LOG = RN / "graph_monitor.log"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import importlib.util
_spec = importlib.util.spec_from_file_location("sysgraph", HERE / "graph.py")
graph = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(graph)

POLL_S = 60.0


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def main():
    _log("graph monitor start — يراقب طوبولوجيا المنظومة")
    prev_nodes, prev_edges, prev_gaps = set(), set(), {}
    while True:
        try:
            g = graph.build()
            cur_nodes = {n["id"] for n in g["nodes"]}
            cur_edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
            gaps = g["gaps"]
            new_nodes = sorted(cur_nodes - prev_nodes) if prev_nodes else []
            gone_nodes = sorted(prev_nodes - cur_nodes) if prev_nodes else []
            new_edges = sorted([f"{s}→{t}" for s, t, k in (cur_edges - prev_edges)]) if prev_edges else []
            # تنبيهات الفجوات الجديدة
            new_disc = sorted(set(gaps.get("disconnected", [])) - set(prev_gaps.get("disconnected", [])))
            new_dead = sorted(set(gaps.get("dead_engines", [])) - set(prev_gaps.get("dead_engines", [])))
            new_stale = sorted(set(gaps.get("stale_files", [])) - set(prev_gaps.get("stale_files", [])))
            report = {"ts": time.time(), "iso": g["iso"], "gaps": gaps,
                      "changes": {"new_nodes": new_nodes, "gone_nodes": gone_nodes, "new_edges": new_edges,
                                  "new_disconnected": new_disc, "new_dead_engines": new_dead, "new_stale": new_stale},
                      "health": ("HEALTHY" if not (gaps.get("disconnected") or gaps.get("dead_engines")) else "GAPS")}
            tmp = REPORT.with_suffix(".json.tmp")
            json.dump(report, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            tmp.replace(REPORT)
            for tag, items in (("🆕 عُقَد جديدة", new_nodes), ("⚠️ انقطع", new_disc),
                               ("💀 محرّك مات", new_dead), ("🕑 تقادم", new_stale), ("❌ اختفى", gone_nodes)):
                if items:
                    _log(f"{tag}: {', '.join(items)}")
            prev_nodes, prev_edges, prev_gaps = cur_nodes, cur_edges, gaps
        except Exception as e:
            _log(f"err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
