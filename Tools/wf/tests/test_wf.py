"""wf tests without GPU, ComfyUI or Godot: Tools/wf/tests/fake_flow.toml, whose commands are stub.py writing files in a
temporary work folder (ART_WORK). Run by Tools/run_tests.sh, or:

    python Tools/wf/tests/test_wf.py
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from wf.cli import main   # noqa: E402

FLOW = os.path.join(HERE, "fake_flow.toml")
T = "hero/-"


def ok(item, **kw):
    return dict(item=item, verdict="pass", reason="看過每一格，沒有問題", **kw)


def bad(item, pic, fix, problem="dirty", verdict="redo"):
    return dict(item=item, verdict=verdict, problem=problem, reason="%s 右下角有一塊碎片" % pic, fix=fix)


class WfTest(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings("ignore", category=ResourceWarning)   # Tools/art/config.py leaves its files open
        self.tmp = tempfile.mkdtemp(prefix="wf_test_")
        self.saved = os.environ.get("ART_WORK")
        os.environ["ART_WORK"] = self.tmp
        self.dir = os.path.join(self.tmp, "live", "hero", "-")

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("ART_WORK", None)
        else:
            os.environ["ART_WORK"] = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def wf(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(args) + ["--flow", FLOW])
        self.out = buf.getvalue()
        return code

    def state(self):
        with open(os.path.join(self.dir, "run.json"), encoding="utf-8") as f:
            return json.load(f)

    def edit_state(self, fn):
        s = self.state()
        fn(s)
        with open(os.path.join(self.dir, "run.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)

    def open_id(self):
        return self.state()["open"]["id"]

    def request(self, rid=None):
        with open(os.path.join(self.dir, "reviews", rid or self.open_id(), "request.json"), encoding="utf-8") as f:
            return json.load(f)

    def pic(self, rid=None):
        return self.request(rid)["images"][0]["file"]

    def answer(self, items, by="claude-code", confidence="high", rid=None, no_run=False):
        rid = rid or self.open_id()
        path = os.path.join(self.tmp, "v_%s.json" % rid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"review": rid, "items": items, "confidence": confidence, "by": by}, f, ensure_ascii=False)
        return self.wf("verdict", T, rid, path, *(["--no-run"] if no_run else []))

    def read(self, rel):
        with open(os.path.join(self.dir, rel), encoding="utf-8") as f:
            return f.read()

    def to_l4(self, l2_fix=None):
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.answer([ok("plate")], by="user"), 10)
        self.assertEqual(self.answer([ok("split", fix=l2_fix)] if l2_fix else [ok("split")]), 10)
        self.assertEqual(self.open_id(), "L4-1")

    def object_through(self, name):
        """one object: outline passes with a redraw, a candidate is picked and placed, the placing passes"""
        self.assertEqual(self.request()["item"], "objects/" + name)
        self.assertEqual(self.answer([ok("objects/" + name, fix={"id": "redraw", "params": {"instr": "draw the " + name}})]), 10)
        self.assertEqual(self.answer([ok("objects/" + name, pick="st/gen/%s_qf1.png" % name,
                                         fix={"id": "place_box", "params": {"box": [1, 2, 30, 40]}})]), 10)
        self.assertEqual(self.answer([ok("objects/" + name)]), 10)

    def to_end(self):
        self.to_l4(l2_fix={"id": "to_objects", "params": {"objects": ["hair"]}})
        self.assertEqual(self.answer([ok("face"), bad("eye", self.pic(), {"id": "to_objects"}), ok("hair")]), 10)
        self.object_through("hair")   # "hair" comes first in the flow's back-to-front order
        self.object_through("eye")
        self.assertEqual(self.open_id(), "L6-1")
        self.assertEqual(self.request()["items"], ["1_face", "2_hair"])
        self.assertEqual(self.answer([ok("1_face"), ok("2_hair")]), 10)
        self.assertEqual(self.open_id(), "L6b-1")
        self.assertEqual(self.answer([ok("arms"), ok("hair")]), 10)
        self.assertEqual(self.open_id(), "L14-1")
        return self.answer([ok("handover")], by="user")

    # ------------------------------------------------------------------ tests
    def test_whole_flow(self):
        self.assertEqual(self.wf("run", T), 10)
        self.assertIn("REVIEW hero/- L0-1", self.out)
        self.assertEqual(self.answer([ok("plate")]), 2)   # a human gate: only the user passes it
        self.assertIn("by: \"user\"", self.out)
        self.assertEqual(self.answer([ok("plate")], by="user"), 10)
        focus = self.request("L2-1")["focus"]
        self.assertIn("第一條注意重點。（fake L2）", focus)
        self.assertIn("this step's own point", focus)
        self.assertFalse(any("不該出現" in f for f in focus))
        self.tearDown()
        self.setUp()
        self.assertEqual(self.to_end(), 0)
        self.assertIn("DONE", self.out)
        s = self.state()
        self.assertTrue(all(s["steps"][k]["status"] == "passed" for k in s["steps"]))
        self.assertTrue(s["steps"]["objects/hair"]["frozen"])
        self.assertEqual(s["steps"]["groups"]["status"], "passed")   # parts rewritten later don't make it stale
        self.assertTrue(any("結束代碼 1" in h for h in self.request("L5c-1")["hints"]))   # '?' command: a hint only
        self.assertTrue(os.path.exists(os.path.join(self.dir, "_packs", "arms_nophys.txt")))
        self.assertFalse([f for f in os.listdir(os.path.join(self.dir, "_packs")) if f.startswith("hair_")])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "reviews", "L5b-1", "st_gen_hair_qf.jpg")))
        log = self.read("llm_checks.md")
        for text in ("## L0 選立繪", "## L2 拆圖層", "修法：`place_box`（box=1,2,30,40）", "挑 `st/gen/hair_qf1.png`",
                     "- 結論：**沒通過 → 重做**", "審查包：`reviews/L14-1`"):
            self.assertIn(text, log)

    def test_fix_then_pass(self):
        self.to_l4()
        self.wf("redo", T, "split")
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.open_id(), "L2-2")
        self.assertEqual(self.answer([bad("split", "split.txt", {"id": "reseed", "params": {"seed": 7}})]), 10)
        self.assertEqual(self.open_id(), "L2-3")
        self.assertEqual(self.read("split.txt"), "seed7")   # the fix ran; the step's own command did not overwrite it
        self.assertEqual(self.request()["history"][-1]["fix"][0]["id"], "reseed")
        self.assertEqual(self.answer([ok("split")]), 10)
        self.assertEqual(self.open_id(), "L4-2")

    def test_verdicts_checked(self):
        self.to_l4()
        p = self.pic()
        cases = [([ok("face"), ok("eye")], "少了：hair"),
                 ([ok("face"), ok("eye"), dict(bad("hair", p, None))], "一定要有 fix"),
                 ([ok("face"), ok("eye"), bad("hair", p, {"id": "reseed", "params": {"seed": 1}})], "不在選單裡"),
                 ([ok("face"), ok("eye"), dict(bad("hair", p, {"id": "to_objects"}), reason="不好")], "哪張圖"),
                 ([ok("face"), ok("eye"), bad("hair", p, {"id": "carve", "params": {"new": ["hair-l"], "box": [1, 2]}},
                                              verdict="split")], "box"),
                 ([ok("face"), ok("eye"), bad("hair", p, {"id": "to_objects"}, problem="ugly")], "problem"),
                 ([ok("face"), ok("eye"), bad("hair", p, {"id": "to_objects"}, verdict="split")], "拆法")]
        for items, text in cases:
            self.assertEqual(self.answer(items, rid="L4-1"), 2, text)
            self.assertIn(text, self.out)
        self.assertEqual(self.open_id(), "L4-1")
        self.assertEqual(self.answer([ok("face"), ok("eye"), bad("hair", p, {"id": "carve", "params": {"new": ["hair-l"]}},
                                                                    verdict="split")]), 10)
        self.assertEqual(self.open_id(), "L4-2")   # split ran, the packs were made again, looked at again
        self.assertIn("hair-l", self.request()["items"])

    def test_low_confidence_waits_for_user(self):
        self.to_l4()
        self.assertEqual(self.answer([ok("face"), ok("eye"), ok("hair")], confidence="low"), 10)
        self.assertIn("LOW", self.out)
        self.assertEqual(self.open_id(), "L4-1")
        self.assertEqual(self.answer([ok("face"), ok("eye"), ok("hair")]), 2)
        self.assertEqual(self.answer([ok("face"), ok("eye"), ok("hair")], by="user"), 10)
        self.assertEqual(self.open_id(), "L6-1")
        self.assertIn("使用者改判", self.read("llm_checks.md"))

    def test_object_cap_blocks(self):
        self.to_l4()
        self.assertEqual(self.answer([ok("face"), bad("eye", self.pic(), {"id": "to_objects"}), ok("hair")]), 10)
        for i, problem in enumerate(["dirty", "dirty", "incomplete"]):
            self.assertEqual(self.answer([bad("objects/eye", self.pic(), {"id": "marks", "params": {"drop": [i]}},
                                              problem=problem)]), 10)
        self.assertEqual(self.answer([bad("objects/eye", self.pic(), {"id": "marks"}, problem="order")]), 20)
        self.assertIn("BLOCKED", self.out)
        s = self.state()
        self.assertEqual(s["steps"]["objects/eye"]["status"], "blocked")
        self.assertIn("上限 3 次", s["steps"]["objects/eye"]["why"])
        self.assertEqual(self.wf("run", T), 20)
        self.assertEqual(self.wf("unblock", T, "objects/eye", "--reason", "使用者：再兩次", "--more", "2"), 0)
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.request()["counts"]["object"], "4/5")

    def test_same_way_banned(self):
        self.to_l4()
        self.assertEqual(self.answer([ok("face"), ok("eye"), bad("hair", self.pic(), {"id": "to_objects"})]), 10)
        self.assertEqual(self.answer([ok("objects/hair", fix={"id": "redraw", "params": {"instr": "draw the hair"}})]), 10)
        redraw = {"id": "redraw", "params": {"instr": "draw the hair, red"}}
        self.assertEqual(self.answer([bad("objects/hair", self.pic(), redraw, problem="style")]), 10)
        self.assertEqual(self.answer([bad("objects/hair", self.pic(), redraw, problem="style")]), 2)
        self.assertIn("禁用", self.out)
        slow = {"id": "redraw_slow", "params": {"instr": "draw the hair"}}
        self.assertEqual(self.answer([bad("objects/hair", self.pic(), slow, problem="style")]), 10)
        self.assertIn("redraw:style", self.request()["banned"])
        self.assertEqual(self.answer([bad("objects/hair", self.pic(), redraw, problem="style")]), 2)
        self.assertEqual(self.answer([bad("objects/hair", self.pic(), redraw, problem="misplaced")]), 10)   # other problem

    def test_stale_after_input_change(self):
        self.assertEqual(self.to_end(), 0)
        with open(os.path.join(self.dir, "full.png"), "w") as f:
            f.write("another plate")
        self.assertEqual(self.wf("run", T), 10)
        s = self.state()
        self.assertEqual(s["open"]["id"], "L2-2")
        self.assertIn("full.png", s["steps"]["split"]["stale_because"])
        for k in ("groups", "objects", "rig", "motion", "handover"):
            self.assertEqual(s["steps"][k]["status"], "pending", k)
        self.assertEqual(s["steps"]["objects/hair"]["status"], "passed")   # frozen objects stay

    def test_resume_after_interruption(self):
        self.to_l4()

        def crashed(s):   # as if the machine stopped while groups' command ran
            s["open"] = None
            s["steps"]["groups"]["status"] = "running"
        self.edit_state(crashed)
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.open_id(), "L4-2")
        self.assertEqual(self.read("wf_logs/groups.log").count("\n$ "), 2)

    def test_time_limit(self):
        self.to_l4()
        self.assertEqual(self.answer([ok("face"), ok("eye"), ok("hair")], no_run=True), 0)
        self.edit_state(lambda s: s.update(elapsed_min=121.0))
        self.assertEqual(self.wf("run", T), 20)
        self.assertIn("時限", self.out)
        self.assertEqual(self.wf("unblock", T, "run", "--reason", "使用者：再給 30 分鐘", "--more", "30"), 0)
        self.assertEqual(self.wf("run", T), 10)

    def test_frozen_and_reopen(self):
        self.assertEqual(self.to_end(), 0)
        self.assertEqual(self.wf("redo", T, "motion"), 0)
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.open_id(), "L6b-2")
        self.assertEqual(self.answer([ok("arms"), bad("hair", self.pic(), {"id": "to_objects", "params": {"objects": ["hair"]}})]), 10)
        s = self.state()   # named by a pack check: the frozen object reopens, everything after the loop waits
        self.assertEqual(s["open"]["key"], "objects/hair")
        self.assertEqual(s["counts"]["pack_rounds"]["hair"], 1)
        self.assertEqual(s["steps"]["rig"]["status"], "pending")
        self.wf("redo", T, "groups")
        self.assertEqual(self.wf("run", T), 10)
        self.assertEqual(self.open_id(), "L4-2")
        self.assertEqual(self.answer([ok("face"), bad("eye", self.pic(), {"id": "to_objects"}), ok("hair")]), 2)
        self.assertIn("凍結", self.out)   # the first parts check may not reopen a passed object
        self.assertEqual(self.wf("redo", T, "objects/eye"), 2)   # by hand: only with a reason
        self.assertEqual(self.wf("redo", T, "objects/eye", "--reason", "使用者要重做"), 0)

    def test_real_flow_renders(self):
        """flows/plate.toml: every command, fix and focus resolves (nothing is run)"""
        from wf.engine import Run
        from wf.flow import command, focus, listify, rows
        r = Run("freya/-")
        self.assertEqual(r.flow.downstream("inx_rig")[:2], ["pack_motion", "shots"])
        checks = set()
        for s in r.flow.steps:
            v = dict(r.vars_for(s), part="headwear", pack=1, pick="x.png")
            for owner in [s] + s.get("stage", []):
                checks.add(owner.get("check"))
                for c in listify(owner.get("cmd")) + listify(owner.get("then")):
                    for row in rows(s.get("foreach")):
                        self.assertTrue(command(c.lstrip("? "), dict(v, **row), "x"), c)
                self.assertFalse([f for f in focus(owner.get("focus"), r.flow) if "找不到" in f], owner["id"])
        for i in ("L0", "L1", "L2", "L3", "L4", "L5a", "L5b", "L5c", "L6", "L6b", "L7", "L8", "L9", "L10", "L11", "L12", "L14"):
            self.assertIn(i, checks)
        for fid, f in r.flow.fixes.items():
            fv = dict(v, **{k: "1" for k in f.get("params", {})})
            for c in listify(f.get("cmd")):
                self.assertTrue(command(c.lstrip("? "), fv, "python x.py"), fid)


if __name__ == "__main__":
    unittest.main(verbosity=1)
