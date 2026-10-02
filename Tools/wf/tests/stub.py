"""Stand-in for the real tools in the wf tests (no GPU, no ComfyUI, no Godot): writes small files in a work folder.

    python stub.py <dir> write <file>[=<text>] ...     each file gets its text (default: the call itself)
    python stub.py <dir> groups <pack>:<part>,<part> ...   st/groups/groups.json like split_groups.py; parts that
                                                       exist as st/part_*.png but are listed nowhere go to "other"
    python stub.py <dir> layer <name>[,<name>...]      new st/part_<name>.png (a carve)
    python stub.py <dir> fail                          exit 1
"""
import glob
import json
import os
import sys


def put(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def main(d, what, args):
    if what == "fail":
        return 1
    if what == "write":
        for a in args:
            rel, _, text = a.partition("=")
            put(d, rel, text or " ".join(sys.argv[2:]))
    elif what == "layer":
        for n in ",".join(args).split(","):
            put(d, "st/part_%s.png" % n, n)
    elif what == "groups":
        packs, listed = [], set()
        for a in args:
            pack, _, parts = a.partition(":")
            packs.append({"pack": pack, "parts": parts.split(",")})
            listed.update(packs[-1]["parts"])
        for p in packs:
            for n in p["parts"]:
                if not os.path.exists(os.path.join(d, "st", "part_%s.png" % n)):
                    put(d, "st/part_%s.png" % n, n)
        extra = sorted(os.path.basename(f)[5:-4] for f in glob.glob(os.path.join(d, "st", "part_*.png")))
        extra = [n for n in extra if n not in listed]
        if extra:
            packs.append({"pack": "other", "parts": extra})
        put(d, "st/groups/groups.json", json.dumps({"packs": packs, "warnings": []}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
