"""The wf command line (Docs/Code/10_Workflow.md).

    python Tools/wf run <hero>/<series> [--flow flows/plate.toml]
    python Tools/wf status [<hero>/<series>]
    python Tools/wf review <hero>/<series>
    python Tools/wf verdict <hero>/<series> <review-id> <verdict.json> [--no-run]
    python Tools/wf redo <hero>/<series> <step | objects/<name>> [--reason ...]
    python Tools/wf unblock <hero>/<series> <step | objects/<name> | run> --reason ... [--more N]

Exit codes: 0 done, 10 waiting for a review (the line "REVIEW <target> <id> <request.json>"), 20 blocked (only the
user lifts it), 2 a refused verdict or a wrong command.
"""
import argparse
import glob
import json
import os
import sys

from wf.engine import BLOCKED, ERROR, WAIT, Run, art_work
from wf.flow import FlowError


def status(r):
    s = r.s
    est = r.flow.meta.get("estimate_min")
    print("%s  流程 %s  開始 %s  用了 %.0f 分鐘%s" % (r.target, s["flow"], s["started"], s["elapsed_min"],
                                                 "（預估 %d，超過 %d 就停）" % (est, 2 * est + s["bonus"].get("time", 0)) if est else ""))
    c = s["counts"]
    print("整張：物件重做 %d/%d、組裝輪數 %d/%d" % (c["plate_redos"], r.cap("plate_redos"), c["plate_rounds"], r.cap("plate_rounds")))
    if c["pack_redos"]:
        print("各包物件重做：%s" % "、".join("%s %d" % kv for kv in sorted(c["pack_redos"].items())))
    keys = [st["id"] for st in r.flow.steps]
    objs = sorted(k for k in s["steps"] if k.startswith("objects/"))
    for k in keys + objs:
        j = s["steps"].get(k, {"status": "pending", "attempts": 0})
        extra = j.get("why") or j.get("stale_because") or ("禁用 " + "、".join(j["banned"]) if j.get("banned") else "")
        cnt = r.counts_for(k, j)["object" if k.startswith("objects/") else "step"]
        print("  %-26s %-13s 執行 %-3d 重做 %-6s %-8s %s" % (("  " if k in objs else "") + k, j["status"], j.get("attempts", 0),
                                                       cnt, j.get("review") or "", extra or ""))
    if s["blocked"]:
        print("整張停住：%s" % s["blocked"])
    if s["manual"]:
        print("手動修改（manual，%d 次）：" % len(s["manual"]))
        for m in s["manual"]:
            print("  %s %s：%s" % (m["time"], m["item"], m["what"]))
    if s["open"]:
        r.say_review()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):   # a cp950 console can't show every character: replaced, not fatal
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="wf", description="流程程式：照 flows/plate.toml 跑一張立繪")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "status", "review", "verdict", "redo", "unblock"):
        p = sub.add_parser(name)
        p.add_argument("target", nargs="?" if name == "status" else None)
        p.add_argument("--flow", default=None)
        if name == "verdict":
            p.add_argument("review_id")
            p.add_argument("file")
            p.add_argument("--no-run", action="store_true")
        if name in ("redo", "unblock"):
            p.add_argument("step")
            p.add_argument("--reason", default="", required=name == "unblock")
        if name == "unblock":
            p.add_argument("--more", type=int, default=3)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status" and not a.target:
            found = sorted(glob.glob(os.path.join(art_work(), "live", "*", "*", "run.json")))
            for f in found:
                with open(f, encoding="utf-8") as fh:
                    s = json.load(fh)
                todo = [k for k, j in s["steps"].items() if j["status"] not in ("passed", "pending")]
                print("%-24s %s%s" % (s["target"], "停住：%s" % s["blocked"] if s["blocked"] else
                                      "等審查 %s" % s["open"]["id"] if s["open"] else "、".join(
                                          "%s %s" % (k, s["steps"][k]["status"]) for k in todo[:4]) or "沒有進行中的步驟", ""))
            if not found:
                print("還沒有任何 run.json（%s）" % os.path.join(art_work(), "live"))
            return 0
        r = Run(a.target, a.flow)
        if a.cmd == "run":
            return r.advance()
        if a.cmd == "status":
            status(r)
            return WAIT if r.s["open"] else BLOCKED if r.s["blocked"] else 0
        if a.cmd == "review":
            if not r.s["open"]:
                print("%s 現在沒有等審查的包" % r.target)
                return 0
            with open(os.path.join(r.dir, "reviews", r.s["open"]["id"], "request.json"), encoding="utf-8") as f:
                print(f.read())
            return r.say_review()
        if a.cmd == "verdict":
            return r.verdict(a.review_id, a.file, go=not a.no_run)
        if a.cmd == "redo":
            return r.redo(a.step, a.reason)
        return r.unblock(a.step, a.reason, a.more)
    except FlowError as e:
        print("ERROR %s" % e)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
