# -*- coding: utf-8 -*-
"""relocate_package.py —— 归类切换器（确定性，无 LLM）。

配套「归类开口」纪律：Agent 每次推断性归类都要回报
「当前归类为 X，如有异议可切换为 Y」——本脚本就是那个"切换"动作本身。
用户一句"换到 Y"，Agent 跑一条命令，包体连同全部事件 .md 原样搬家，
索引确定性刷新，跨包 linked 不受影响（关联按 id，不按路径）。

用法：
    python scripts/relocate_package.py <memory_root> <旧包相对路径> <新包相对路径>
    python scripts/relocate_package.py <memory_root> <源包相对路径> <目标包相对路径> --merge
例：
    python scripts/relocate_package.py memory "其他/哲学/有限空间必然趋同" "其他/科学/复杂系统/有限空间必然趋同"
    python scripts/relocate_package.py memory "其他/哲学/尼采2" "其他/哲学/尼采" --merge

行为（全部确定性）：
【relocate（默认，整包搬迁）】
1. 校验旧路径存在、新路径不存在（拒绝覆盖，防误并包）。
2. shutil.move 整棵目录（含嵌套子包）。
3. 索引删除旧 package_id 及其所有子孙行（前缀匹配）。
4. 对新位置整棵树逐包 install（重扫 front-matter 重插，1:1 铁律不破）。
5. 打印搬迁清单供 Agent 回报用户。
【merge（--merge，合并进已存在包）】
1. 校验源包存在、目标包已存在（合并须进已存在包，否则退化成 relocate）。
2. 把源包下所有事件 .md 移进目标包目录。
3. 索引删除源 package_id 行；目标包重新 install（重挂全部事件）。
4. 清理源包空目录及其空祖先。
5. 打印合并清单供 Agent 回报用户。
"""
import os
import sys
import shutil
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hma.hma_core import Memory  # noqa: E402


def relocate(memory_root, old_rel, new_rel):
    repo = os.path.abspath(memory_root)
    old_rel = old_rel.strip("/").replace("\\", "/")
    new_rel = new_rel.strip("/").replace("\\", "/")
    old_dir = os.path.join(repo, *old_rel.split("/"))
    new_dir = os.path.join(repo, *new_rel.split("/"))

    if not os.path.isdir(old_dir):
        raise SystemExit(f"[abort] 旧包不存在: {old_dir}")
    if os.path.exists(new_dir):
        raise SystemExit(f"[abort] 新路径已存在（拒绝覆盖，防误并包）: {new_dir}")
    if old_rel == new_rel:
        raise SystemExit("[abort] 新旧路径相同")

    # 1) 搬目录（含嵌套子包）
    os.makedirs(os.path.dirname(new_dir), exist_ok=True)
    shutil.move(old_dir, new_dir)
    print(f"[move] {old_rel} -> {new_rel}")

    # 1.5) 清理旧路径留下的空祖先目录（到 repo 为止）
    p = os.path.dirname(old_dir)
    while os.path.abspath(p) != repo and os.path.isdir(p) and not os.listdir(p):
        os.rmdir(p)
        print(f"[prune] 空目录 {os.path.relpath(p, repo)}")
        p = os.path.dirname(p)

    # 2) 索引：删旧 package_id 及子孙行
    db = os.path.join(repo, "index.db")
    cx = sqlite3.connect(db)
    n = cx.execute(
        "DELETE FROM events WHERE package_id=? OR package_id LIKE ?",
        (old_rel, old_rel + "/%")).rowcount
    cx.commit()
    cx.close()
    print(f"[index] 删除旧索引行: {n}")

    # 3) 新位置整棵树逐包 install
    g = Memory(repo)
    total = 0
    for dirpath, dirnames, filenames in os.walk(new_dir):
        mds = [f for f in filenames
               if f.endswith(".md") and not f.endswith(".tmp")]
        if not mds:
            continue
        cnt = g.install(dirpath)
        rel = os.path.relpath(dirpath, repo).replace(os.sep, "/")
        print(f"[install] {rel}: {cnt} 个事件包")
        total += cnt
    g.close()
    print(f"[done] 归类切换完成：{old_rel} -> {new_rel}（共 {total} 个事件包重挂索引）")


def merge(memory_root, src_rel, dst_rel):
    """把 src 包整体合并进已存在的 dst 包（事件 .md 移入 + 索引重挂）。"""
    repo = os.path.abspath(memory_root)
    src_rel = src_rel.strip("/").replace("\\", "/")
    dst_rel = dst_rel.strip("/").replace("\\", "/")
    src_dir = os.path.join(repo, *src_rel.split("/"))
    dst_dir = os.path.join(repo, *dst_rel.split("/"))

    if not os.path.isdir(src_dir):
        raise SystemExit(f"[abort] 源包不存在: {src_dir}")
    if not os.path.isdir(dst_dir):
        raise SystemExit(f"[abort] 目标包不存在（合并须进已存在包）: {dst_dir}")
    if src_rel == dst_rel:
        raise SystemExit("[abort] 源与目标相同")

    # 1) 源包下所有事件 .md 移进目标包
    os.makedirs(dst_dir, exist_ok=True)
    moved = 0
    for fn in sorted(os.listdir(src_dir)):
        if fn.endswith(".md") and not fn.endswith(".tmp"):
            shutil.move(os.path.join(src_dir, fn), os.path.join(dst_dir, fn))
            print(f"[move] {src_rel}/{fn} -> {dst_rel}/{fn}")
            moved += 1

    # 2) 索引：删源行，重挂目标
    db = os.path.join(repo, "index.db")
    cx = sqlite3.connect(db)
    n = cx.execute("DELETE FROM events WHERE package_id=?", (src_rel,)).rowcount
    cx.commit()
    cx.close()
    print(f"[index] 删除源索引行: {n}")

    g = Memory(repo)
    cnt = g.install(dst_dir)
    g.close()
    print(f"[install] {dst_rel}: {cnt} 个事件包")

    # 3) 清理源包空目录及空祖先
    if os.path.isdir(src_dir) and not os.listdir(src_dir):
        os.rmdir(src_dir)
        print(f"[prune] 空目录 {src_rel}")
        p = os.path.dirname(src_dir)
        while os.path.abspath(p) != repo and os.path.isdir(p) and not os.listdir(p):
            os.rmdir(p)
            print(f"[prune] 空目录 {os.path.relpath(p, repo)}")
            p = os.path.dirname(p)
    print(f"[done] 合并完成：{src_rel} -> {dst_rel}（移动 {moved} 个事件）")


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        raise SystemExit(2)
    if len(sys.argv) == 5 and sys.argv[4] == "--merge":
        merge(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        relocate(sys.argv[1], sys.argv[2], sys.argv[3])
