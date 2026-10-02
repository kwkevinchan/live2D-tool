"""Review packets and verdicts (Docs/Design/23_Workflow.md section 4): reviews/<check>-<n>/request.json with copies of
the pictures as they were, the reviewer's verdict.json checked strictly, and one entry per verdict appended to the
work folder's llm_checks.md.

    write_packet(folder, request, pictures)   -> the request with the copied file names
    validate(request, verdict, wdir)          -> [errors]; fixes' params rendered into fix["args"]
    append_log(path, title, request, verdict, counts)
"""
import json
import os
import re
import shutil
import time

from wf.flow import PROBLEMS, listify

VERDICTS = ("pass", "redo", "split")
NAME = re.compile(r"^[a-z][a-z0-9_\-]*$")


def write_packet(folder, request, pictures):
    os.makedirs(folder, exist_ok=True)
    shown = []
    for src in pictures:   # copies: the packet keeps what was looked at even after the files change
        rel = os.path.relpath(src, request["dir"]).replace("\\", "/")
        name = rel.replace("/", "_") if not rel.startswith("..") else os.path.basename(src)
        shutil.copy2(src, os.path.join(folder, name))
        shown.append({"file": name, "from": rel})
    request["images"] = shown
    tmp = os.path.join(folder, "request.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(request, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, "request.json"))
    return request


# ------------------------------------------------------------------ parameter types (a "?" suffix: may be left out)
def _ints(v, n=None):
    xs = v if isinstance(v, list) else [x for x in re.split(r"[,\s]+", str(v)) if x]
    out = [int(x) for x in xs if not isinstance(x, bool)]
    if len(out) != len(xs) or (n and len(out) != n):
        raise ValueError("要 %s個整數" % ("%d " % n if n else ""))
    return out


def _box(v, d):
    x0, y0, x1, y1 = _ints(v, 4)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("框要 x0,y0,x1,y1，x1>x0、y1>y0")
    return "%d,%d,%d,%d" % (x0, y0, x1, y1)


def _points(v, d):
    pts = v if isinstance(v, list) else [p.split(",") for p in str(v).split(";") if p.strip()]
    pts = [_ints(p, 2) for p in pts]
    if not pts:
        raise ValueError("要至少一個點 [[x,y], ...]")
    return ";".join("%d,%d" % tuple(p) for p in pts)


def _layer(v, d):
    if not isinstance(v, str) or not os.path.exists(os.path.join(d, "st", "part_%s.png" % v)):
        raise ValueError("沒有這個圖層 st/part_%s.png" % v)
    return v


def _names(v, d):
    xs = v if isinstance(v, list) else str(v).split(",")
    if not xs or not all(isinstance(x, str) and NAME.match(x) for x in xs):
        raise ValueError("名字只能是小寫英文、數字、_、-")
    return ",".join(xs)


def _file(v, d):
    p = os.path.normpath(os.path.join(d, str(v)))
    if not p.startswith(os.path.normpath(d)) or not os.path.isfile(p):
        raise ValueError("工作資料夾裡沒有這個檔 %s" % v)
    return p


def _text(v, d):
    if not isinstance(v, str) or not v.strip():
        raise ValueError("要一段文字")
    return v


def _int(v, d):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("要整數")
    return str(v)


def _float(v, d):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("要數字")
    return str(v)


def _flag(v, d):
    if not isinstance(v, bool):
        raise ValueError("要 true 或 false")
    return v


TYPES = {"int": _int, "ints": lambda v, d: ",".join(map(str, _ints(v))), "float": _float, "text": _text,
         "box": _box, "points": _points, "layer": _layer, "layers": lambda v, d: ",".join(_layer(x, d) for x in
         (v if isinstance(v, list) else str(v).split(","))), "name": _names, "names": _names, "file": _file,
         "flag": _flag}


def check_params(spec, given, wdir):
    errs, out = [], {}
    if not isinstance(given, dict):
        return ["params 要是物件"], out
    for k in given:
        if k not in spec:
            errs.append("多了參數 %s（只能用 %s）" % (k, ", ".join(spec) or "無"))
    for k, t in spec.items():
        opt, t = t.endswith("?"), t.rstrip("?")
        v = given.get(k)
        if v is None or v == "" or v == []:
            if not opt:
                errs.append("少了參數 %s（%s）" % (k, t))
            out[k] = ""
            continue
        try:
            out[k] = TYPES[t](v, wdir)
        except (ValueError, TypeError) as e:
            errs.append("參數 %s=%r：%s" % (k, v, e))
            continue
        if t == "flag":
            out[k] = "--" + k.replace("_", "-") if v else ""
    return errs, out


def validate(req, v, wdir, awaiting_user=False):
    """everything a verdict must be (23 section 4); the fixes get their rendered params as fix["args"]"""
    errs = []
    if not isinstance(v, dict):
        return ["verdict.json 要是一個物件"]
    if v.get("review") != req["review"]:
        errs.append("review 要是 %s" % req["review"])
    if v.get("confidence") not in ("high", "low"):
        errs.append("confidence 只能是 high 或 low")
    by = v.get("by")
    if not isinstance(by, str) or not by:
        errs.append("by 要寫是誰審的")
    elif (req.get("gate") == "human" or awaiting_user) and by != "user":
        errs.append("這個審查包要使用者點頭（by: \"user\"）" + ("；上一個結論信心低" if awaiting_user else ""))
    items = v.get("items")
    if not isinstance(items, list) or not items:
        return errs + ["items 要是一串，至少一筆"]
    menu = {m["id"]: m for m in req["menu"]}
    pmenu = {m["id"]: m for m in req.get("pass_menu", [])}
    shown = [i["file"] for i in req.get("images", [])]
    limit = req.get("same_way_fails", 2)
    seen = set()
    for it in items:
        name = it.get("item") if isinstance(it, dict) else None
        tag = "%s：" % name
        if name not in req["items"]:
            errs.append("%s不是這個審查包要的（要：%s）" % (tag, "、".join(req["items"])))
            continue
        if name in seen:
            errs.append("%s寫了兩筆" % tag)
        seen.add(name)
        verdict, problem, reason = it.get("verdict"), it.get("problem"), it.get("reason")
        if verdict not in VERDICTS:
            errs.append("%sverdict 只能是 pass、redo、split" % tag)
            continue
        if not isinstance(reason, str) or not reason.strip():
            errs.append("%s要寫 reason" % tag)
        elif verdict != "pass" and shown and not any(s in reason or os.path.splitext(s)[0] in reason for s in shown):
            errs.append("%sreason 要寫在哪張圖的哪裡（提到 %s 其中一張）" % (tag, "、".join(shown)))
        if verdict != "pass" and problem not in PROBLEMS:
            errs.append("%sproblem 要是 %s 其中一種" % (tag, "、".join(PROBLEMS)))
        fixes = listify(it.get("fix"))
        if verdict == "pass":
            allowed = pmenu
            if req.get("pass_needs_fix") and not fixes:
                errs.append("%s通過時要從 pass_menu 挑下一步的做法" % tag)
            if req.get("pick") and not (isinstance(it.get("pick"), str) and _ok(_file, it["pick"], wdir)):
                errs.append("%s要用 pick 挑一張候選（工作資料夾裡的相對路徑）" % tag)
        else:
            allowed = menu
            if not fixes:
                errs.append("%s%s 一定要有 fix" % (tag, verdict))
        banned = set(req.get("banned", []))
        if verdict != "pass" and req.get("last_fix"):   # this verdict may be the second failure of the same way
            key = "%s:%s" % (req["last_fix"], problem)
            if req.get("fails", {}).get(key, 0) + 1 >= limit:
                banned.add(key)
        kinds = []
        for f in fixes:
            if not isinstance(f, dict) or f.get("id") not in allowed:
                errs.append("%sfix %r 不在%s選單裡（%s）" % (tag, f.get("id") if isinstance(f, dict) else f,
                            "通過的" if verdict == "pass" else "", "、".join(allowed) or "無"))
                continue
            if "%s:%s" % (f["id"], problem) in banned:
                errs.append("%s%s 對「%s」已經失敗 %d 次，禁用（換一種做法）" % (tag, f["id"], problem, limit))
            perrs, f["args"] = check_params(allowed[f["id"]].get("params", {}), f.get("params", {}), wdir)
            errs += [tag + e for e in perrs]
            if allowed[f["id"]].get("kind") == "opens":
                for o in (f["args"].get("objects") or name).split(","):
                    if o in req.get("frozen", []) and not req.get("reopens"):
                        errs.append("%s%s 已通過、凍結；只有 L6、L6b、L9 這類組裝檢查能點名重開" % (tag, o))
            kinds.append(allowed[f["id"]].get("kind"))
        if verdict == "split" and "split" not in kinds:
            errs.append("%ssplit 要有一個拆法（%s）" % (tag, "、".join(k for k, m in menu.items() if m.get("kind") == "split") or "這一步沒有"))
        if verdict == "redo" and "split" in kinds:
            errs.append("%s拆法要用 verdict: split" % tag)
    missing = [i for i in req["items"] if i not in seen]
    if missing:
        errs.append("每一個都要有一筆，少了：%s" % "、".join(missing))
    return errs


def _ok(fn, v, d):
    try:
        fn(v, d)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ llm_checks.md
WORD = {"pass": "通過", "redo": "重做", "split": "要再拆"}


def append_log(path, title, req, v, counts):
    """one entry in the style of the hand-written llm_checks.md"""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# %s LLM 檢查紀錄\n\n每一筆由流程程式 `wf` 照審查包的結論寫入（Docs/Design/23_Workflow.md）。\n" % req["target"])
    items = v["items"]
    bad = [i for i in items if i["verdict"] != "pass"]
    lines = ["", "## %s（%s）" % (title, time.strftime("%Y-%m-%d %H:%M")), "",
             "- 審查包：`reviews/%s`（%s；%s，信心 %s）" % (req["review"], req["item"],
                                                     "使用者" if v["by"] == "user" else v["by"], v["confidence"]),
             "- 看了：%s。" % ("、".join(i["file"] for i in req.get("images", [])) or "（沒有圖）"),
             "- 結論：**%s**" % ("通過" if not bad else "沒通過 → " + "、".join(sorted({WORD[i["verdict"]] for i in bad})))]
    passed = [i["item"] for i in items if i["verdict"] == "pass"]
    if bad and passed:
        lines.append("  - 通過：%s" % "、".join(passed))
    for i in items:
        if i["verdict"] == "pass" and (bad or len(items) > 1) and not i.get("fix") and not i.get("pick"):
            continue
        s = "  - %s：%s" % (i["item"], WORD[i["verdict"]])
        if i["verdict"] != "pass":
            s += "（%s）" % PROBLEMS[i["problem"]]
        s += "：%s" % i["reason"].strip()
        if i.get("pick"):
            s += "。挑 `%s`" % i["pick"]
        for f in listify(i.get("fix")):
            ps = "，".join("%s=%s" % (k, x if k not in f.get("args", {}) or isinstance(x, str) else f["args"][k])
                          for k, x in f.get("params", {}).items() if x not in (None, "", []))
            s += "。修法：`%s`%s%s" % (f["id"], "（%s）" % ps if ps else "", "：" + f["why"] if f.get("why") else "")
        lines.append(s)
    if v["by"] == "user" and req.get("earlier_by"):
        lines.append("- **使用者改判**（原本：%s）" % req["earlier_by"])
    if counts:
        lines.append("- 次數：%s。" % "、".join("%s %s" % kv for kv in counts.items()))
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
