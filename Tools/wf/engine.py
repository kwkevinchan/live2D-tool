"""One plate's run through a flow (Docs/Design/23_Workflow.md sections 2-4): the engine decides the next step, runs
the tools, counts redos, refuses banned ways, and stops at every checkpoint with a review packet; the reviewer only
looks at the pictures and picks from the menu.

    r = Run("freya/-")              # flows/plate.toml; state in <work>/live/freya/-/run.json
    r.advance()                     -> 0 done, 10 waiting for a review (REVIEW line), 20 blocked (BLOCKED line)
    r.verdict("L4-2", "verdict.json")
    r.redo("objects/headwear", reason), r.unblock("objects/headwear", reason, more)

Jobs (run.json "steps"): one per flow step, and one per object in the object loop ("objects/<name>"). Statuses:
pending, running, needs_review, passed, rejected (a fix is queued), blocked (only the user lifts it).
"""
import json
import os
import shutil
import subprocess
import sys
import time

from wf import review as R
from wf.flow import ROOT, Flow, FlowError, command, files, focus, listify, resolve, rows

sys.path.insert(0, os.path.join(ROOT, "Tools", "art"))
DONE, WAIT, BLOCKED, ERROR = 0, 10, 20, 2
REVIEW_CAP_MIN = 20     # a review's waiting time counts toward the time limit up to this many minutes
LABEL = {"object": "物件", "pack": "包", "plate": "整張", "step": "這一步", "rounds": "組裝輪數"}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return "sha256:" + h.hexdigest()[:16]


def art_work():
    if os.environ.get("ART_WORK"):
        return os.path.normpath(os.environ["ART_WORK"])
    import config   # Tools/art/config.py: live2d.toml [paths] work
    return config.WORK


class Run:
    def __init__(self, target, flow_path=None):
        if "/" not in target:
            raise FlowError("要寫 <hero>/<series>（主設計的 series 是 -）")
        self.target = target
        self.hero, self.series = target.split("/", 1)
        self.flow = Flow(flow_path or os.path.join(ROOT, "flows", "plate.toml"))
        self.dir = os.path.normpath(self.base_vars()["dir"])
        self.path = os.path.join(self.dir, "run.json")
        self.s = None
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.s = json.load(f)
            if not flow_path and self.s.get("flow_file") and os.path.exists(self.s["flow_file"]):
                self.flow = Flow(self.s["flow_file"])
        if self.s is None:
            self.s = {"flow": self.flow.meta.get("name"), "flow_file": self.flow.path, "target": target,
                      "started": now(), "elapsed_min": 0.0, "blocked": None, "open": None,
                      "counts": {"plate_redos": 0, "plate_rounds": 0, "pack_redos": {}, "pack_rounds": {}, "reviews": {}},
                      "bonus": {}, "steps": {}, "manual": [], "log": []}
        self.objects_id = next((s["id"] for s in self.flow.steps if s.get("kind") == "each_object"), None)

    # ------------------------------------------------------------------ state
    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.s, f, ensure_ascii=False, indent=1)
        os.replace(self.path + ".tmp", self.path)

    def job(self, key):
        return self.s["steps"].setdefault(key, {"status": "pending", "attempts": 0})

    def note(self, text):
        self.s["log"].append("%s %s" % (now(), text))
        print("  " + text, flush=True)

    def cap(self, name, key=""):
        return self.flow.limit(name) + self.s["bonus"].get("%s:%s" % (name, key) if key else name, 0)

    def block(self, job, why, cap=None):
        job.update(status="blocked", why=why, cap=cap)
        self.save()

    def base_vars(self):
        import config
        series_dir = "default" if self.series in ("-", "") else self.series
        v = {"hero": self.hero, "series": self.series, "art_work": art_work(), "name": "%s_%s" % (self.hero, series_dir),
             "godot": os.environ.get("GODOT") or config.GODOT, "mv_python": config.MV.get("python", ""), "repo": ROOT}
        v["live"] = os.path.join(v["art_work"], "live")
        v["dir"] = os.path.normpath(resolve(dict(v, _w=self.flow.meta.get("work", "{live}/{hero}/{series}")))["_w"])
        v["plate_dir"] = v["dir"] if self.series.startswith("pose_") else config.plate_dir(self.hero, self.series)
        return resolve(dict(self.flow.meta.get("vars", {}), **v))

    def vars_for(self, step, key=None):
        v = resolve(dict(self.base_vars(), **step.get("vars", {})))
        if key and key.startswith("objects/"):
            o = self.job(key)
            v["part"] = key.split("/", 1)[1]
            v["pack"] = self.pack_of(v["part"])[0]
            v["pick"] = os.path.join(self.dir, o["pick"]) if o.get("pick") else ""
        return v

    def groups(self):
        p = os.path.join(self.dir, "st", "groups", "groups.json")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("packs", [])

    def pack_of(self, part):
        """(pack number, "<n>_<pack>", parts in it) from split_groups' groups.json"""
        for i, g in enumerate(self.groups()):
            if part in g.get("parts", []):
                return i + 1, "%d_%s" % (i + 1, g["pack"]), len(g["parts"])
        return 6, "?", 1

    # ------------------------------------------------------------------ the loop
    def advance(self):
        os.makedirs(self.dir, exist_ok=True)
        self.refresh_stale()
        while True:
            if self.s["open"]:
                return self.say_review()
            if self.s["blocked"]:
                print("BLOCKED %s run: %s" % (self.target, self.s["blocked"]))
                return BLOCKED
            est = self.flow.meta.get("estimate_min")
            if est and self.s["elapsed_min"] > 2 * est + self.s["bonus"].get("time", 0):
                self.s.update(blocked="時限：已用 %.0f 分鐘，超過預估 %d 分鐘的兩倍" % (self.s["elapsed_min"], est), blocked_cap="time")
                self.save()
                continue
            step = self.next_step()
            if step is None:
                print("DONE %s：每一步都通過了" % self.target)
                return DONE
            job = self.job(step["id"])
            if job["status"] == "blocked":
                print("BLOCKED %s %s: %s" % (self.target, step["id"], job.get("why")))
                return BLOCKED
            print("== %s" % step["id"], flush=True)
            (self.work_objects if step.get("kind") == "each_object" else self.work)(step, job)

    def next_step(self):
        for s in self.flow.steps:
            j = self.job(s["id"])
            if s.get("skip") and j["status"] != "passed":
                j.update(status="passed", skipped=s["skip"])
                self.note("%s 跳過：%s" % (s["id"], s["skip"]))
            if j["status"] != "passed" and all(self.job(a)["status"] == "passed" for a in listify(s.get("after"))):
                return s
        return None

    def run_cmds(self, key, job, cmds, owner, v):
        """each command once per foreach row it differs in; '?' in front: its exit code is only a hint"""
        same = listify(owner.get("cmd"))[0] if owner.get("cmd") else None
        done = []
        for tmpl in listify(cmds):
            hint = tmpl.startswith("?")
            for row in rows(owner.get("foreach")):
                argv = command(tmpl.lstrip("? "), dict(v, **row), same)
                if argv in done:
                    continue
                done.append(argv)
                if not self.call(key, job, argv, hint):
                    return False
        return True

    def call(self, key, job, argv, hint=False):
        logs = os.path.join(self.dir, "wf_logs")
        os.makedirs(logs, exist_ok=True)
        log = os.path.join(logs, key.replace("/", "_") + ".log")
        line = " ".join(a if " " not in a else '"%s"' % a for a in argv)
        t0 = time.time()
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n$ %s   (%s)\n" % (line, now()))
            f.flush()
            try:
                rc = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode
            except OSError as e:
                f.write("%s\n" % e)
                rc = -1
        dt = time.time() - t0
        self.s["elapsed_min"] += dt / 60
        print("  $ %s  -> exit %d (%.0f s)" % (line[:150], rc, dt), flush=True)
        if rc and hint:   # check tools return 1 when they flag something: a hint for the reviewer, not a verdict
            job.setdefault("hints", []).append("%s 結束代碼 %d（紀錄 wf_logs/%s）" % (line[:120], rc, os.path.basename(log)))
        elif rc:
            self.block(job, "指令失敗（結束代碼 %d）：%s；紀錄 %s" % (rc, line, log))
            return False
        self.save()
        return True

    def work(self, step, job):
        v = self.vars_for(step)
        job.update(status="running", hints=[], started=job.get("started") or now())
        self.save()
        rerun = True
        if job.get("queue"):
            if not self.run_queue(step["id"], job, step, v):
                return
            rerun = step.get("after_fix", "then") == "cmd"
        if rerun:
            job["attempts"] += 1
            if not self.run_cmds(step["id"], job, step.get("cmd"), step, v):
                return
        if not self.run_cmds(step["id"], job, step.get("then"), step, v):
            return
        missing = [p for p in listify(step.get("outputs"))
                   if not any(files(self.dir, [p], dict(v, **r)) for r in rows(step.get("foreach")))]
        if missing:
            return self.block(job, "沒有產出：%s" % "、".join(missing))
        if step.get("check"):
            self.open_review(step, job, v)
        else:
            self.pass_step(step, job, v)

    def run_queue(self, key, job, owner, v):
        """the fixes a verdict chose, in order; each leaves the queue only once it has run"""
        while job.get("queue"):
            f = job["queue"][0]
            fdef = self.flow.fixes[f["id"]]
            if fdef.get("kind") == "manual":
                self.s["manual"].append({"time": now(), "item": key, "review": job.get("review"), "what": f["args"]["what"]})
                self.note("%s 手動修改（manual）：%s" % (key, f["args"]["what"]))
            fv = dict(v, **fdef.get("defaults", {}))   # a param left out keeps the default, or the run's own value
            fv.update({k: x for k, x in f.get("args", {}).items() if x != "" or k not in fv})
            if f.get("item") and "part" not in fv:   # a per-object check: the fix works on that item's layer
                fv["part"] = f["item"]
            for tmpl in listify(fdef.get("cmd")):
                hint = tmpl.startswith("?")
                if not self.call(key, job, command(tmpl.lstrip("? "), fv, listify(owner.get("cmd") or [""])[0]), hint):
                    return False
            if fdef.get("kind") == "split":
                for n in f["args"].get("new", "").split(","):
                    if n:
                        self.open_object(n, why="%s 拆出來的" % key)
                if key.startswith("objects/"):
                    job.update(stage=None, rerun=True, images=None)
            elif fdef.get("stage"):
                job.update(stage=fdef["stage"], images=fdef.get("images"))
            elif fdef.get("images"):
                job["images"] = fdef["images"]
            job["last_fix"] = f["id"]
            job["attempts"] = job.get("attempts", 0) + 1
            job["queue"].pop(0)
            self.save()
        return True

    def pass_step(self, step, job, v):
        job.update(status="passed", ended=now(), fp=self.fingerprint(step, v))
        job.pop("stale_because", None)
        self.save()
        print("  passed %s" % step["id"])

    # ------------------------------------------------------------------ fingerprints and staleness
    def fingerprint(self, step, v):
        """the step's input files (sha256), less those a later step writes: the last writer counts"""
        later = set()
        for d in self.flow.downstream(step["id"]):
            ds = self.flow.step(d)
            for r in rows(ds.get("foreach")):
                later.update(files(self.dir, ds.get("outputs"), dict(self.vars_for(ds), **r)))
        ins = [f for r in rows(step.get("foreach")) for f in files(self.dir, step.get("inputs"), dict(v, **r))]
        return {os.path.relpath(f, self.dir).replace("\\", "/"): sha(f) for f in sorted(set(ins)) if f not in later}

    def refresh_stale(self):
        for s in self.flow.steps:
            j = self.s["steps"].get(s["id"])
            if not j or j["status"] != "passed" or "fp" not in j or s.get("skip"):
                continue
            fp = self.fingerprint(s, self.vars_for(s))
            if fp != j["fp"]:
                changed = sorted(set(fp.items()) ^ set(j["fp"].items()))[0][0]
                self.reset(s["id"], "上游改了：%s" % changed)

    def reset(self, sid, why):
        """a step and everything after it back to pending"""
        for k in [sid] + self.flow.downstream(sid):
            j = self.job(k)
            if j["status"] == "blocked" and k != sid:
                continue
            if j["status"] != "pending" or k == sid:
                j.update(status="pending", queue=[], stale_because=why if k == sid else "%s 要重做" % sid)
            if self.s["open"] and self.s["open"]["step"] == k:
                self.s["open"] = None
        self.note("%s 改回 pending：%s" % (sid, why))
        self.save()

    # ------------------------------------------------------------------ the object loop
    def work_objects(self, step, job):
        if job["status"] in ("pending", "rejected"):
            job["status"] = "running"
        if job.get("queue"):   # a fix chosen at the assembly check (manual)
            v = self.vars_for(step)
            if self.run_queue(step["id"], job, step, v) and self.run_cmds(step["id"], job, step.get("then"), step, v):
                self.open_review(step, job, v)
            return
        jobs = {k: j for k, j in self.s["steps"].items() if k.startswith("objects/")}
        todo = [k for k, j in jobs.items() if j["status"] not in ("passed", "blocked")]
        if todo:
            return self.work_object(step, min(todo, key=lambda k: self.order_of(step, k)))
        stuck = [k for k, j in jobs.items() if j["status"] == "blocked"]
        if stuck:
            return self.block(job, "物件停住了：%s" % "、".join(stuck))
        v = self.vars_for(step)
        if not self.run_cmds(step["id"], job, step.get("then"), step, v):
            return
        self.open_review(step, job, v)

    def order_of(self, step, key):
        """back to front (22b): the order list's first matching prefix"""
        name = key.split("/", 1)[1]
        order = step.get("order", [])
        return next((i for i, p in enumerate(order) if name.startswith(p)), len(order)), key

    def stage(self, step, sid):
        stages = self.flow.stages(step["id"])
        return next((s for s in stages if s["id"] == sid), stages[0])

    def work_object(self, step, key):
        o = self.job(key)
        if not os.path.exists(os.path.join(self.dir, "st", "part_%s.png" % key.split("/", 1)[1])):
            o.update(status="passed", frozen=True, queue=[], gone=True)   # dropped since it was opened (character_only)
            self.note("%s 跳過：圖層已經不在（被拿掉了）" % key)
            self.save()
            return
        st = self.stage(step, o.get("stage"))
        o.update(status="running", hints=[], stage=st["id"])
        self.save()
        v = self.vars_for(step, key)
        fixed = bool(o.get("queue"))
        if fixed:
            if not self.run_queue(key, o, st, v):
                return
            st = self.stage(step, o.get("stage"))
            o["stage"] = st["id"]
        # the stage's own command: a new or reopened object, the next stage after a pass, or after a split
        if o.pop("rerun", False) or (not fixed and o.get("fresh", True)):
            if not st.get("cmd"):
                return self.block(o, "「%s」沒有預設指令，要由上一個結論挑做法" % st["id"])
            o["attempts"] += 1
            o["images"] = None
            if not self.run_cmds(key, o, st["cmd"], st, v):
                return
        o["fresh"] = False
        v = self.vars_for(step, key)   # split_groups may have moved it to another pack
        if not self.run_cmds(key, o, st.get("then"), st, v):
            return
        self.open_review(step, o, v, st, key)

    def open_object(self, name, reopen=False, why=""):
        key = "objects/" + name
        o = self.s["steps"].get(key)
        if o:   # guard 3: a passed (frozen) object reopens only when an assembly check names it
            if o["status"] == "passed" and reopen:
                o.update(status="pending", stage=None, frozen=False, queue=[], fresh=True, images=None,
                         reopened=o.get("reopened", 0) + 1)
                self.note("%s 重開：%s" % (key, why))
            return o["status"] != "passed"
        if not os.path.exists(os.path.join(self.dir, "st", "part_%s.png" % name)):   # a pack's name for a piece of
            self.note("%s 不開：沒有這個圖層（%s）" % (key, why))                    # another layer (leftover-head)
            return False
        self.s["steps"][key] = {"status": "pending", "attempts": 0, "redos": 0, "tries": [], "fails": {}, "banned": [],
                                "fresh": True, "opened": now(), "why": why}
        self.note("%s 進物件迴圈：%s" % (key, why))
        return True

    def reopen_objects(self, why):
        if not self.objects_id:
            return
        oj = self.job(self.objects_id)
        oj.update(status="running", review=None)
        for d in self.flow.downstream(self.objects_id):
            j = self.job(d)
            if j["status"] != "blocked":
                j.update(status="pending", queue=[], stale_because=why)
            if self.s["open"] and self.s["open"]["step"] == d:
                self.s["open"] = None

    # ------------------------------------------------------------------ reviews
    def items_for(self, st, key):
        spec = st.get("items")
        if key.startswith("objects/") or not st.get("per_item"):
            return [key]
        if isinstance(spec, list):
            return spec
        if spec == "groups:parts":
            return [p for g in self.groups() for p in g.get("parts", [])]
        if spec == "groups:packs":
            return ["%d_%s" % (i + 1, g["pack"]) for i, g in enumerate(self.groups())]
        if isinstance(spec, str) and spec.startswith("foreach:"):
            return [str(r[spec[8:]]) for r in rows(st.get("foreach"))]
        raise FlowError("%s: items %r" % (st["id"], spec))

    def menu(self, ids):
        out = []
        for i in listify(ids):
            f = self.flow.fixes[i]
            out.append({k: f[k] for k in ("id", "kind", "params", "note", "stage") if k in f})
        return out

    def counts_for(self, key, job):
        c, f = self.s["counts"], self.flow
        if key.startswith("objects/"):
            n, pk, size = self.pack_of(key.split("/", 1)[1])
            pcap = max(f.limit("per_pack_min"), f.limit("per_pack_factor") * size) + self.s["bonus"].get("per_pack:" + pk, 0)
            return {"object": "%d/%d" % (job.get("redos", 0), self.cap("per_object", key)),
                    "pack": "%s %d/%d" % (pk, c["pack_redos"].get(pk, 0), pcap),
                    "plate": "%d/%d" % (c["plate_redos"], self.cap("plate_redos"))}
        return {"step": "%d/%d" % (job.get("redos", 0), self.cap("step_redos", key)),
                "rounds": "%d/%d" % (c["plate_rounds"], self.cap("plate_rounds")),
                "plate": "%d/%d" % (c["plate_redos"], self.cap("plate_redos"))}

    def open_review(self, step, job, v, stage=None, key=None):
        st, key = stage or step, key or step["id"]
        check = st["check"]
        n = self.s["counts"]["reviews"].get(check, 0) + 1
        rid = "%s-%d" % (check, n)
        folder = os.path.join(self.dir, "reviews", rid)
        pats = job.get("images") or st.get("images") if stage else st.get("images")
        pics, missing = [], []
        for p in listify(pats):
            got = [x for r in rows(st.get("foreach")) for x in files(self.dir, [p], dict(v, **r))]
            pics += [x for x in got if x not in pics]
            if not got:
                missing.append(p)
        nxt = None
        if stage:
            stages = self.flow.stages(step["id"])
            i = [s["id"] for s in stages].index(stage["id"])
            nxt = stages[i + 1] if i + 1 < len(stages) else None
        single = not st.get("per_item") or bool(stage)
        verdict_path = os.path.join(folder, "verdict.json")
        items = self.items_for(st, key)
        req = {"review": rid, "check": check, "title": self.flow.check_name(check), "target": self.target, "dir": self.dir,
               "step": step["id"], "item": key, "items": items, "per_item": None if stage else st.get("per_item"),
               "gate": step.get("gate"), "pick": bool(st.get("pick")), "pass_needs_fix": bool(nxt and not nxt.get("cmd")),
               "focus": focus(st.get("focus"), self.flow), "history": job.get("tries", [])[-10:],
               "counts": self.counts_for(key, job), "menu": self.menu(listify(st.get("fix")) + ["manual"]),
               "pass_menu": self.menu(st.get("pass_fix")), "banned": job.get("banned", []) if single else [],
               "last_fix": job.get("last_fix") if single else None, "fails": job.get("fails", {}) if single else {},
               "same_way_fails": self.flow.limit("same_way_fails"), "reopens": bool(step.get("reopens")),
               "frozen": [k.split("/", 1)[1] for k, j in self.s["steps"].items() if k.startswith("objects/") and j.get("frozen")],
               "hints": job.get("hints", []), "missing_images": missing,
               "answer_with": "python Tools/wf verdict %s %s %s" % (self.target, rid, verdict_path),
               "verdict_template": {"review": rid, "items": [{"item": i, "verdict": "pass|redo|split", "problem": None,
                                    "reason": "", "fix": None} for i in items], "confidence": "high", "by": "claude-code"}}
        R.write_packet(folder, req, pics)
        self.s["counts"]["reviews"][check] = n
        self.s["open"] = {"id": rid, "step": step["id"], "key": key, "stage": stage and stage["id"], "since": now(),
                          "since_t": time.time()}
        job.update(status="needs_review", review=rid)
        self.save()

    def say_review(self):
        op = self.s["open"]
        path = os.path.join(self.dir, "reviews", op["id"], "request.json")
        who = "（等使用者：上一個結論信心低）" if op.get("awaiting") == "user" else ""
        print("REVIEW %s %s %s%s" % (self.target, op["id"], path, who), flush=True)
        return WAIT

    # ------------------------------------------------------------------ verdicts
    def verdict(self, rid, path, go=True):
        op = self.s["open"]
        if not op or op["id"] != rid:
            print("ERROR 現在等審查的不是 %s（%s）" % (rid, op and op["id"]))
            return ERROR
        folder = os.path.join(self.dir, "reviews", rid)
        with open(os.path.join(folder, "request.json"), encoding="utf-8") as f:
            req = json.load(f)
        try:
            with open(path, encoding="utf-8") as f:
                v = json.load(f)
        except (OSError, ValueError) as e:
            print("REJECTED %s：讀不了 %s（%s）" % (rid, path, e))
            return ERROR
        errs = R.validate(req, v, self.dir, op.get("awaiting") == "user")
        if errs:
            print("REJECTED %s：結論不合格式，沒有執行" % rid)
            for e in errs:
                print("  - " + e)
            return ERROR
        keep = os.path.join(folder, "verdict.json" if v["by"] != "user" or not op.get("awaiting") else "verdict_user.json")
        if os.path.abspath(path) != os.path.abspath(keep):
            shutil.copy2(path, keep)
        self.s["elapsed_min"] += min(REVIEW_CAP_MIN, (time.time() - op.get("since_t", time.time())) / 60)
        if v["confidence"] == "low" and v["by"] != "user":
            op.update(awaiting="user", earlier_by=v["by"], since_t=time.time())
            self.save()
            print("LOW %s：信心低，先不執行；等使用者看過再交一次（by: user）" % rid)
            return self.say_review()
        step = self.flow.step(op["step"])
        key, job = op["key"], self.job(op["key"])
        stage = self.stage(step, op["stage"]) if op["stage"] else None
        req["earlier_by"] = op.get("earlier_by")
        self.s["open"] = None
        counts = (self.object_verdict(step, stage, key, job, req, v["items"][0]) if stage
                  else self.step_verdict(step, key, job, req, v["items"]))
        R.append_log(os.path.join(self.dir, "llm_checks.md"), req["title"], req, v,
                     {LABEL.get(k, k): x for k, x in counts.items()})
        self.save()
        print("ACCEPTED %s" % rid, flush=True)
        return self.advance() if go else DONE

    def tried(self, job, req, it):
        job.setdefault("tries", []).append({"n": len(job["tries"]) + 1, "review": req["review"], "item": it["item"],
                                            "verdict": it["verdict"], "problem": it.get("problem"), "reason": it["reason"],
                                            "after": job.get("last_fix"), "fix": [{"id": f["id"], "params": f.get("params", {})}
                                                                                 for f in listify(it.get("fix"))]})

    def count_fail(self, key, job, problem):
        """guard 2: the fix that made what was looked at failed on this problem; twice and it is banned"""
        lf = job.get("last_fix")
        if lf:
            k = "%s:%s" % (lf, problem)
            fails = job.setdefault("fails", {})   # (a step job may not have it yet: the right side is read first)
            fails[k] = fails.get(k, 0) + 1
            if job["fails"][k] >= self.flow.limit("same_way_fails") and k not in job.setdefault("banned", []):
                job["banned"].append(k)
                self.note("%s：%s 禁用（同一個問題失敗 %d 次）" % (key, k, job["fails"][k]))

    def object_verdict(self, step, stage, key, o, req, it):
        self.tried(o, req, it)
        stages = [s["id"] for s in self.flow.stages(step["id"])]
        fixes = listify(it.get("fix"))
        if it["verdict"] == "pass":
            if it.get("pick"):
                o["pick"] = it["pick"]
            if stage["id"] == stages[-1]:   # guard 3: a passed object is frozen
                o.update(status="passed", frozen=True, stage=None, ended=now())
                self.note("%s 通過（凍結）" % key)
            elif fixes:
                o.update(status="running", queue=fixes)
            else:
                o.update(status="running", stage=stages[stages.index(stage["id"]) + 1], rerun=True)
            return self.counts_for(key, o)
        self.count_fail(key, o, it["problem"])
        c = self.s["counts"]
        _, pk, size = self.pack_of(key.split("/", 1)[1])
        o["redos"] = o.get("redos", 0) + 1
        c["pack_redos"][pk] = c["pack_redos"].get(pk, 0) + 1
        c["plate_redos"] += 1
        o.update(status="rejected", queue=fixes)
        pcap = max(self.flow.limit("per_pack_min"), self.flow.limit("per_pack_factor") * size) + \
            self.s["bonus"].get("per_pack:" + pk, 0)
        if o["redos"] > self.cap("per_object", key):   # guard 1: the caps
            self.block(o, "這個物件重做到了上限 %d 次" % self.cap("per_object", key), "per_object:" + key)
        elif c["pack_redos"][pk] > pcap:
            self.block(o, "%s 這一包的物件重做到了上限 %d 次" % (pk, pcap), "per_pack:" + pk)
        elif c["plate_redos"] > self.cap("plate_redos"):
            self.s.update(blocked="整張立繪的物件重做到了上限 %d 次" % self.cap("plate_redos"), blocked_cap="plate_redos")
        return self.counts_for(key, o)

    def step_verdict(self, step, key, job, req, items):
        single = items[0]["item"] == key and len(items) == 1
        opened, queued, redo = [], [], []
        for it in items:
            self.tried(job, req, it)
            if it["verdict"] != "pass":
                redo.append(it["item"])
                if single:
                    self.count_fail(key, job, it["problem"])
            for f in listify(it.get("fix")):
                if self.flow.fixes[f["id"]].get("kind") == "opens":
                    opened += [n for n in (f["args"].get("objects") or it["item"]).split(",") if n]
                else:
                    queued.append(dict(f, item=it["item"]))
        c = self.s["counts"]
        if redo and step.get("rounds"):   # the assembly checks: rounds per pack and for the plate
            c["plate_rounds"] += 1
            if step["rounds"] == "pack":
                for p in redo:
                    c["pack_rounds"][p] = c["pack_rounds"].get(p, 0) + 1
                    if c["pack_rounds"][p] > self.cap("pack_rounds", p):
                        self.block(job, "%s 的組裝檢查到了 %d 輪" % (p, self.cap("pack_rounds", p)), "pack_rounds:" + p)
                        return self.counts_for(key, job)
            if c["plate_rounds"] > self.cap("plate_rounds"):
                self.s.update(blocked="整張立繪的組裝檢查到了 %d 輪" % self.cap("plate_rounds"), blocked_cap="plate_rounds")
                return self.counts_for(key, job)
        for n in opened:
            self.open_object(n, reopen=bool(step.get("reopens")), why="%s 點名" % req["review"])
        later = self.objects_id and (step["id"] == self.objects_id or step["id"] in self.flow.downstream(self.objects_id))
        if opened and later:
            self.reopen_objects("%s 重開了物件" % req["review"])
            if queued:
                self.note("物件重開，後面的步驟會重跑；這次的其他修法不執行：%s" % "、".join(f["id"] for f in queued))
        elif queued:
            job["redos"] = job.get("redos", 0) + 1
            job.update(status="rejected", queue=queued)
            if job["redos"] > self.cap("step_redos", key):
                self.block(job, "這一步重做到了上限 %d 次" % self.cap("step_redos", key), "step_redos:" + key)
        else:
            self.pass_step(step, job, self.vars_for(step))
        return self.counts_for(key, job)

    # ------------------------------------------------------------------ by hand
    def redo(self, key, reason=""):
        if key.startswith("objects/"):
            o = self.s["steps"].get(key)
            if o is None:
                print("ERROR 沒有 %s" % key)
                return ERROR
            if o.get("frozen") and not reason:
                print("ERROR %s 已通過、凍結：重開要加 --reason" % key)
                return ERROR
            o.update(status="passed")
            self.open_object(key.split("/", 1)[1], reopen=True, why="wf redo：%s" % (reason or "（沒寫理由）"))
            self.reopen_objects("wf redo %s" % key)
        elif key in self.flow.by_id:
            self.reset(key, "wf redo%s" % ("：" + reason if reason else ""))
        else:
            print("ERROR 流程裡沒有 %s" % key)
            return ERROR
        self.save()
        return DONE

    def unblock(self, key, reason, more):
        """only the user lifts a block: the cap that stopped it grows by `more` (minutes for the time limit)"""
        if key == "run":
            if not self.s["blocked"]:
                print("ERROR 整張沒有停住")
                return ERROR
            capname = self.s.pop("blocked_cap", None) or "time"
            self.s["bonus"][capname] = self.s["bonus"].get(capname, 0) + more
            self.s["blocked"] = None
        else:
            j = self.s["steps"].get(key)
            if not j or j["status"] != "blocked":
                print("ERROR %s 沒有停住" % key)
                return ERROR
            if j.get("cap"):
                self.s["bonus"][j["cap"]] = self.s["bonus"].get(j["cap"], 0) + more
            j.update(status="rejected" if j.get("queue") else "pending" if not key.startswith("objects/") else "running",
                     why=None, cap=None)
            if key.startswith("objects/") and self.objects_id and self.job(self.objects_id)["status"] == "blocked":
                self.job(self.objects_id).update(status="running", why=None)
        self.note("使用者解開 %s（多給 %d）：%s" % (key, more, reason))
        self.save()
        return DONE

