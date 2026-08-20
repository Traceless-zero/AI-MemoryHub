import os, re, json, glob

MEM = r"E:/BaiduNetdiskDownload/项目/AIMH/memory"
rows = []
for path in glob.glob(os.path.join(MEM, "**", "*.md"), recursive=True):
    rel = os.path.relpath(path, MEM)
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        rows.append((rel, "NO_FM", "", "", ""))
        continue
    fm = m.group(1)
    # id
    mid = re.search(r"^id:\s*(.+)$", fm, re.M)
    fid = mid.group(1).strip() if mid else "?"
    # features
    has_feat = "features:" in fm
    # tags
    mt = re.search(r"^tags:\s*\[?(.*?)\]?$", fm, re.M | re.S)
    tags = ""
    if mt:
        tags = mt.group(1).strip()
    # anchors
    ma = re.search(r"^anchors:\s*(.*)$", fm, re.M)
    atype = "none"
    acount = 0
    if ma:
        val = ma.group(1).strip()
        if val.startswith("["):
            try:
                arr = json.loads(val)
                atype = "json_obj" if isinstance(arr[0], dict) else "json_str"
                acount = len(arr)
            except Exception:
                atype = "json_parse_err:" + val[:40]
        else:
            atype = "inline:" + val[:30]
    rows.append((rel, fid, "Y" if has_feat else "-", tags[:80], f"{atype}({acount})"))

for r in sorted(rows):
    print(f"{r[0]:<55} id={r[1]:<22} feat={r[2]} tags={r[3]:<40} anc={r[4]}")
