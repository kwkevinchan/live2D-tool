"""A flow file (flows/plate.toml, Docs/Design/23_Workflow.md section 1): the steps of one plate, their commands, the
files they read and write, their checkpoint, the pictures to look at, the points to watch and the menu of fixes.

    F = Flow("flows/plate.toml")
    F.steps, F.step("see_through"), F.fixes["reseed"], F.downstream("objects"), F.limit("per_object")
    command("python Tools/art/x.py {hero} --seed={seed}", vars)      -> argv (a token with an empty value is left out)
    expand("st/groups/parts_{1..6}.jpg", vars)                       -> six patterns
    focus("22b#L4", F)                                               -> the bullets of that checkpoint in 22b

Placeholders are {name}; values come from the run (hero, series, dir, ...), [flow.vars], the step's vars, its foreach
row and a verdict's params. A token whose placeholder renders empty is dropped whole, so optional flags are written
as one token: --weapon={pts}.
"""
import glob
import itertools
import os
import re
import shlex
import sys
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VAR = re.compile(r"\{(\w+)\}")
RANGE = re.compile(r"\{(\d+)\.\.(\d+)\}")
PROBLEMS = {"unrecognizable": "看不出是什麼", "incomplete": "不完整", "dirty": "有碎片、殘影或白洞",
            "misplaced": "位置或大小不對", "order": "前後錯", "style": "畫風不對"}
MANUAL = {"id": "manual", "kind": "manual", "params": {"what": "text"}, "note": "選單外的修法：先改好檔，what 寫改了什麼"}
LIMITS = {"per_object": 10, "per_pack_factor": 2, "per_pack_min": 6, "pack_rounds": 3, "plate_redos": 30,
          "plate_rounds": 3, "same_way_fails": 2, "step_redos": 3}


class FlowError(Exception):
    pass


def listify(x):
    return [] if x is None else list(x) if isinstance(x, (list, tuple)) else [x]


class Flow:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        with open(self.path, "rb") as f:
            d = tomllib.load(f)
        self.meta = d.get("flow", {})
        self.limits = dict(LIMITS, **d.get("limits", {}))
        self.checks = d.get("checks", {})
        self.fixes = {k: dict(v, id=k) for k, v in d.get("fix", {}).items()}
        self.fixes["manual"] = MANUAL
        self.steps = d.get("step", [])
        self.by_id = {s["id"]: s for s in self.steps}
        if len(self.by_id) != len(self.steps):
            raise FlowError("two steps with the same id")
        for s in self.steps:
            for a in listify(s.get("after")):
                if a not in self.by_id:
                    raise FlowError("%s: after %s, no such step" % (s["id"], a))
            for st in [s] + s.get("stage", []):
                for k in listify(st.get("fix")) + listify(st.get("pass_fix")):
                    if k not in self.fixes:
                        raise FlowError("%s: fix %s is not in [fix]" % (st["id"], k))

    def step(self, sid):
        return self.by_id[sid]

    def limit(self, name):
        return self.limits[name]

    def downstream(self, sid):
        """the steps that wait on sid, directly or through others, in flow order"""
        out = {sid}
        for s in self.steps:   # flow order: a step comes after what it waits on
            if out & set(listify(s.get("after"))):
                out.add(s["id"])
        return [s["id"] for s in self.steps if s["id"] in out and s["id"] != sid]

    def stages(self, sid):
        return self.by_id[sid].get("stage", [])

    def check_name(self, check):
        name = self.checks.get(check)
        if not name:
            for key, path in self.meta.get("docs", {}).items():
                name = doc_section(os.path.join(ROOT, path), check)[0] or name
        return "%s %s" % (check, name) if name else check


def rows(foreach):
    """foreach as a list of rows: [{pack: arms}, ...] as given, or {pack: [arms, legs]} crossed"""
    if not foreach:
        return [{}]
    if isinstance(foreach, list):
        return foreach
    keys = list(foreach)
    return [dict(zip(keys, combo)) for combo in itertools.product(*[listify(foreach[k]) for k in keys])]


def fill(text, v):
    def one(m):
        if m.group(1) not in v:
            raise FlowError("no value for {%s} in %r" % (m.group(1), text))
        return str(v[m.group(1)])
    return VAR.sub(one, text)


def resolve(v):
    """[flow.vars] may refer to each other and to the run's values: filled until nothing changes"""
    for _ in range(5):
        new = {k: fill(x, v) if isinstance(x, str) else x for k, x in v.items()}
        if new == v:
            break
        v = new
    return v


def expand(pattern, v):
    m = RANGE.search(pattern)
    if not m:
        return [fill(pattern, v)]
    return [p for i in range(int(m.group(1)), int(m.group(2)) + 1)
            for p in expand(pattern[:m.start()] + str(i) + pattern[m.end():], v)]


def files(wdir, patterns, v):
    """existing files for the patterns (relative to the work folder unless absolute; * allowed), sorted, no repeats"""
    out = []
    for p in listify(patterns):
        for q in expand(p, v):
            q = q if os.path.isabs(q) else os.path.join(wdir, q)
            for f in sorted(glob.glob(q)):
                if os.path.isfile(f) and os.path.normpath(f) not in out:
                    out.append(os.path.normpath(f))
    return out


def python():
    return os.environ.get("LIVE2D_PYTHON") or sys.executable


def command(tmpl, v, same=None):
    """a command line to argv: split first (a value with spaces stays one argument), then filled; {same} is the
    step's own command; a token with a placeholder that renders empty is left out; python = this Python"""
    out = []
    for tok in shlex.split(tmpl, posix=True):
        if tok == "{same}":
            out += command(same, v)
            continue
        names = VAR.findall(tok)
        if names and any(str(v.get(n, "")) == "" for n in names if n in v):
            continue
        out.append(fill(tok, v))
    if out and out[0] == "python":
        out[0] = python()
    return out


def doc_section(path, check):
    """(name, bullets) of a checkpoint's '**L4 name**' paragraph in 22b's points to watch"""
    if not os.path.exists(path):
        return None, []
    name, out, on = None, [], False
    with open(path, encoding="utf-8") as f:
        for ln in f.read().splitlines():
            m = re.match(r"\*\*(L\w+)\s+(.+?)\*\*\s*$", ln)
            if m or ln.startswith("**") or ln.startswith("#"):
                on = bool(m) and m.group(1) == check
                if on and name is None:
                    name = m.group(2)
                continue
            if on and ln.startswith("- "):
                out.append(ln[2:])
    return name, out


def focus(items, flow):
    """'22b#L4' expanded to that checkpoint's bullets (the doc read every time, so a changed 22b is followed);
    anything else kept as written"""
    out = []
    for it in listify(items):
        m = re.match(r"^(\w+)#(L\w+)$", it)
        doc = m and flow.meta.get("docs", {}).get(m.group(1))
        if doc:
            name, bullets = doc_section(os.path.join(ROOT, doc), m.group(2))
            out += ["%s（%s %s）" % (b, m.group(1), m.group(2)) for b in bullets] or ["（%s 找不到 %s）" % (doc, it)]
        else:
            out.append(it)
    return out
