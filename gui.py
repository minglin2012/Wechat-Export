#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""微信聊天记录导出工具 — 图形界面"""

import os, sys, json, threading, datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from export import (
    load_key, extract_key, WCDB, load_config, should_skip,
    sanitize, export_one, KEY_FILE, CONFIG_FILE, OUTPUT_DIR, _detect_dd,
)

SELECTION_FILE = os.path.join(HERE, "session_selection.json")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("微信聊天记录导出 v3.0")
        self.root.geometry("1080x720")
        self.root.minsize(950, 620)

        self.db = None
        self.sessions = []
        self.nick_map = {}
        self.data_dir = ""
        self.checked_wxids = set()   # 打勾的 wxid 集合
        self._all_rows = []          # [(display, wxid, skip), ...]
        self._tree_items = {}        # wxid → tree item id
        self._init_selection_file()

        self._setup_ui()
        self._refresh_key_status()

    # ════════════ 选择持久化 ════════════

    def _init_selection_file(self):
        """首次运行时创建空文件"""
        if not os.path.exists(SELECTION_FILE):
            self._save_selection()

    def _load_selection(self, path: str = "") -> set:
        """从指定文件（默认 SELECTION_FILE）加载勾选的 wxid 集合"""
        p = path or SELECTION_FILE
        try:
            data = json.load(open(p, encoding="utf-8"))
            return set(data.get("wxids", []))
        except Exception:
            return set()

    def _save_selection(self, path: str = ""):
        """保存勾选的 wxid 到指定文件（默认 SELECTION_FILE）"""
        p = path or SELECTION_FILE
        try:
            json.dump({"wxids": sorted(self.checked_wxids),
                        "updated": datetime.datetime.now().isoformat()},
                      open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _auto_load_selection(self):
        """连接后自动恢复上次选择"""
        saved = self._load_selection()
        if not saved:
            return
        # 只恢复存在于当前会话中的 wxid
        current_wxids = {wxid for _, wxid, *_ in self._all_rows}
        restored = saved & current_wxids
        self.checked_wxids = restored
        if restored:
            self._log(f"✅ 自动恢复了 {len(restored)} 个上次勾选的会话")

    # ════════════ UI 框架 ════════════

    def _setup_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.page_key = ttk.Frame(nb)
        self.page_sessions = ttk.Frame(nb)
        self.page_export = ttk.Frame(nb)
        nb.add(self.page_key, text="  🔑 密钥  ")
        nb.add(self.page_sessions, text="  📋 会话  ")
        nb.add(self.page_export, text="  📤 导出  ")

        self._build_key_page()
        self._build_sessions_page()
        self._build_export_page()

        self.status = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _log(self, msg):
        self.status.config(text=str(msg)[:120])
        self.root.update_idletasks()

    def _on_close(self):
        self._save_selection()
        if self.db:
            try: self.db.stop()
            except Exception: pass
        self.root.destroy()

    # ════════════ 密钥页 ════════════

    def _build_key_page(self):
        f = ttk.Frame(self.page_key, padding=20)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="微信数据库密钥", font=("", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(f, text="密钥用于解密微信的加密数据库，一次获取后可重复使用。").pack(anchor=tk.W, pady=(5, 20))

        self.key_status_var = tk.StringVar(value="未检测")
        ttk.Label(f, textvariable=self.key_status_var, font=("Consolas", 11), foreground="gray").pack(anchor=tk.W)

        self.key_btn = ttk.Button(f, text="🔑 获取密钥", command=self._do_get_key, width=18)
        self.key_btn.pack(anchor=tk.W, pady=(15, 5))

        ttk.Label(f, text="操作步骤：", font=("", 10, "bold")).pack(anchor=tk.W, pady=(30, 5))
        for s in ["1. 关闭微信电脑端（右键系统托盘 → 退出）",
                  "2. 点击「获取密钥」按钮",
                  "3. 在弹出的管理员窗口中看到提示后，打开微信并登录",
                  "4. 程序自动捕获密钥并保存"]:
            ttk.Label(f, text="    " + s).pack(anchor=tk.W)

    def _refresh_key_status(self):
        k = load_key()
        if k:
            self.key_status_var.set(f"✅ 已有密钥: {k[:16]}...")
        else:
            self.key_status_var.set("❌ 未获取密钥")

    def _do_get_key(self):
        if not messagebox.askokcancel("获取密钥",
                                       "1. 关闭微信（右键托盘 → 退出）\n"
                                       "2. 点确定\n"
                                       "3. 在弹出窗口提示后打开微信并登录"):
            return
        self.key_btn.config(state=tk.DISABLED)
        self._log("正在获取密钥...")
        threading.Thread(target=self._get_key_thread, daemon=True).start()

    def _get_key_thread(self):
        try:
            k = extract_key()
            with open(KEY_FILE, "w") as f: f.write(k)
            self.root.after(0, self._refresh_key_status)
            self.root.after(0, lambda: self._log("密钥获取成功"))
            self.root.after(0, lambda: messagebox.showinfo("成功",
                f"密钥已保存到:\n{KEY_FILE}\n\n{k[:16]}..."))
        except Exception as e:
            self.root.after(0, lambda: self._log(f"获取失败: {e}"))
            self.root.after(0, lambda: messagebox.showerror("获取失败",
                f"{e}\n\n请确保:\n1. 完全关闭微信\n2. 在弹出的控制台窗口提示后打开微信登录\n3. 如果没弹出窗口，检查杀毒软件是否拦截"))
        finally:
            self.root.after(0, lambda: self.key_btn.config(state=tk.NORMAL))

    # ════════════ 会话页 ════════════

    def _build_sessions_page(self):
        f = ttk.Frame(self.page_sessions, padding=10)
        f.pack(fill=tk.BOTH, expand=True)

        # ── 顶部：数据目录 + 连接 ──
        top = ttk.Frame(f)
        top.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(top, text="数据目录:").pack(side=tk.LEFT)
        self.dir_var = tk.StringVar(value=_detect_dd())
        ttk.Entry(top, textvariable=self.dir_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(top, text="浏览", command=lambda: self.dir_var.set(
            filedialog.askdirectory(initialdir=self.dir_var.get()) or self.dir_var.get()
        )).pack(side=tk.LEFT, padx=2)
        self.connect_btn = ttk.Button(top, text="连接数据库", command=self._do_connect, width=12)
        self.connect_btn.pack(side=tk.LEFT, padx=10)

        # ── 搜索 + 快捷过滤 ──
        sf = ttk.Frame(f)
        sf.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(sf, text="🔍").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(sf, textvariable=self.search_var, width=25)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_sessions())

        # 快捷过滤
        ttk.Separator(sf, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        self.quick_filter = tk.StringVar(value="all")
        for label, val in [("全部","all"), ("好友","friends"), ("群聊","groups"),
                           ("有备注","named"), ("有聊天","active")]:
            ttk.Radiobutton(sf, text=label, variable=self.quick_filter,
                            value=val, command=self._filter_sessions).pack(side=tk.LEFT, padx=1)

        # 右侧操作按钮
        ttk.Button(sf, text="全选", command=lambda: self._check_all(True), width=6).pack(side=tk.RIGHT, padx=2)
        ttk.Button(sf, text="全不选", command=lambda: self._check_all(False), width=7).pack(side=tk.RIGHT, padx=2)
        ttk.Button(sf, text="反选", command=self._check_invert, width=6).pack(side=tk.RIGHT, padx=2)
        ttk.Separator(sf, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y, padx=4)
        ttk.Button(sf, text="💾 保存", command=self._save_and_notify, width=7).pack(side=tk.RIGHT, padx=2)
        ttk.Button(sf, text="📂 加载", command=self._load_and_notify, width=7).pack(side=tk.RIGHT, padx=2)

        # ── 会话列表 ──
        tree_frame = ttk.Frame(f)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("check", "name", "count", "wxid")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=20)
        self.tree.heading("check", text="☑")
        self.tree.heading("name", text="显示名 ▲", command=lambda: self._sort_by("name"))
        self.tree.heading("count", text="消息数", command=lambda: self._sort_by("count"))
        self.tree.heading("wxid", text="")
        self.tree.column("check", width=35, anchor=tk.CENTER)
        self.tree.column("name", width=320)
        self.tree.column("count", width=80, anchor=tk.CENTER)
        self.tree.column("wxid", width=0, stretch=False)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 点击：checkbox 列切换勾选，列头排序
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<space>", lambda e: self._toggle_selected())

        # 排序状态
        self._sort_col = "name"
        self._sort_asc = True

        # ── 信息栏 ──
        info_frame = ttk.Frame(f)
        info_frame.pack(fill=tk.X, pady=(5, 0))
        self.session_info = ttk.Label(info_frame, text="请先连接数据库", foreground="gray")
        self.session_info.pack(side=tk.LEFT)
        self.check_count_label = ttk.Label(info_frame, text="", foreground="green")
        self.check_count_label.pack(side=tk.RIGHT)

    def _on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item and col == "#1":  # checkbox column
            self._toggle_item(item)

    def _toggle_selected(self):
        sel = self.tree.selection()
        for item in sel:
            self._toggle_item(item)

    def _toggle_item(self, item):
        vals = self.tree.item(item)["values"]
        if len(vals) < 4:
            return
        wxid = str(vals[3])
        if wxid in self.checked_wxids:
            self.checked_wxids.discard(wxid)
            vals[0] = "☐"
        else:
            self.checked_wxids.add(wxid)
            vals[0] = "☑"
        self.tree.item(item, values=vals)
        self._update_check_count()
        self._save_selection()

    def _check_all(self, check: bool):
        for item in self.tree.get_children():
            vals = self.tree.item(item)["values"]
            if len(vals) < 4: continue
            wxid = str(vals[3])
            if check:
                self.checked_wxids.add(wxid)
                vals[0] = "☑"
            else:
                self.checked_wxids.discard(wxid)
                vals[0] = "☐"
            self.tree.item(item, values=vals)
        self._update_check_count()
        self._save_selection()

    def _check_invert(self):
        for item in self.tree.get_children():
            vals = self.tree.item(item)["values"]
            if len(vals) < 4: continue
            wxid = str(vals[3])
            if wxid in self.checked_wxids:
                self.checked_wxids.discard(wxid)
                vals[0] = "☐"
            else:
                self.checked_wxids.add(wxid)
                vals[0] = "☑"
            self.tree.item(item, values=vals)
        self._update_check_count()
        self._save_selection()

    def _save_and_notify(self):
        path = filedialog.asksaveasfilename(
            title="保存勾选列表",
            defaultextension=".json",
            initialdir=HERE,
            initialfile="session_selection.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._save_selection(path)
        self._log(f"已保存 {len(self.checked_wxids)} 个勾选 -> {os.path.basename(path)}")

    def _load_and_notify(self):
        path = filedialog.askopenfilename(
            title="加载勾选列表",
            initialdir=HERE,
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        saved = self._load_selection(path)
        current = {wxid for _, wxid, *_ in self._all_rows}
        restored = saved & current
        self.checked_wxids = restored
        self._filter_sessions()
        not_found = len(saved) - len(restored)
        msg = f"已加载 {len(restored)} 个勾选"
        if not_found > 0:
            msg += f" ({not_found} 个不在当前列表中)"
        msg += f" <- {os.path.basename(path)}"
        self._log(msg)

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = False if col == "count" else True  # 消息数默认降序
        self._filter_sessions()

    def _update_check_count(self):
        total = len(self.tree.get_children())
        if total > 0:
            self.check_count_label.config(
                text=f"☑ {len(self.checked_wxids)} / {total}")
        else:
            self.check_count_label.config(text="")

    # ── 数据库连接 ──

    def _do_connect(self):
        dd = self.dir_var.get().strip()
        if not dd:
            messagebox.showwarning("提示", "请选择微信数据目录")
            return
        self.data_dir = dd
        self.connect_btn.config(state=tk.DISABLED)
        self._log("正在连接...")
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        try:
            key = load_key()
            if not key:
                self.root.after(0, lambda: self._log("❌ 未找到密钥，请先获取"))
                self.root.after(0, lambda: self.connect_btn.config(state=tk.NORMAL))
                return
            db = WCDB()
            db.start(key, self.data_dir)
            sessions = db.sessions()
            all_u = [s.get("username", "") for s in sessions
                     if s.get("username", "") and not s.get("username", "").startswith("brand")]
            nm = {}
            if all_u:
                try: nm = db.names(all_u[:500])
                except Exception: pass
            self.db = db
            self.sessions = sessions
            self.nick_map = nm
            self.root.after(0, lambda: self._populate_sessions())
            self.root.after(0, lambda: self._log(f"✅ 已连接，{len(sessions)} 个会话"))
        except Exception as e:
            self.root.after(0, lambda: self._log(f"❌ {e}"))
            self.root.after(0, lambda: messagebox.showerror("连接失败", str(e)[:300]))
        finally:
            self.root.after(0, lambda: self.connect_btn.config(state=tk.NORMAL))

    def _populate_sessions(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_items.clear()
        self._all_rows = []
        cfg = load_config()
        for s in self.sessions:
            wxid = s.get("username", "")
            if not wxid: continue
            display = self.nick_map.get(wxid, wxid)
            skip = should_skip(wxid, display, cfg, skip_official=True, skip_groups=False)
            is_group = wxid.endswith("@chatroom")
            has_nick = display != wxid
            last_ts = s.get("last_timestamp", s.get("sort_timestamp", ""))
            has_msg = bool(last_ts) and int(last_ts or 0) > 0
            self._all_rows.append((display, wxid, skip, is_group, has_nick, has_msg, 0))

        self._auto_load_selection()
        self._filter_sessions()

        # 后台加载消息数
        self._log("后台加载消息数...")
        threading.Thread(target=self._load_counts, daemon=True).start()

    def _load_counts(self):
        """后台线程逐条加载消息数"""
        loaded = 0
        total = len(self._all_rows)
        for i, row in enumerate(self._all_rows):
            wxid = row[1]
            try:
                cnt = self.db.count(wxid)
                # 更新 _all_rows 中的 count（保持前 6 个字段，替换第 7 个）
                self._all_rows[i] = row[:6] + (cnt,)
                loaded += 1
            except Exception:
                pass
            # 每 50 条刷新一次视图
            if loaded % 50 == 0:
                self.root.after(0, self._filter_sessions)
                self.root.after(0, lambda c=loaded, t=total:
                                self._log(f"消息数加载中... {c}/{t}"))
        # 最终刷新
        self.root.after(0, self._filter_sessions)
        self.root.after(0, lambda: self._log(f"消息数加载完成 ({loaded}/{total})"))

    def _filter_sessions(self):
        kw = self.search_var.get().lower().strip()
        qf = self.quick_filter.get()
        self.tree.delete(*self.tree.get_children())
        self._tree_items.clear()

        # 收集过滤后的行
        filtered = []
        for row in self._all_rows:
            display, wxid, skip, is_group, has_nick, has_msg, count = row
            if kw and kw not in display.lower() and kw not in wxid.lower():
                continue
            if qf == "friends":
                if is_group or wxid.startswith("brand") or wxid.startswith("gh_"):
                    continue
            elif qf == "groups":
                if not is_group: continue
            elif qf == "named":
                if not has_nick or is_group or wxid.startswith(("brand","gh_")):
                    continue
            elif qf == "active":
                if not has_msg: continue
            filtered.append(row)

        # 排序
        if self._sort_col == "name":
            filtered.sort(key=lambda r: r[0].lower(), reverse=not self._sort_asc)
        elif self._sort_col == "count":
            filtered.sort(key=lambda r: r[6], reverse=not self._sort_asc)

        # 插入树
        showed = 0
        for display, wxid, skip, is_group, has_nick, has_msg, count in filtered:
            checked = "☑" if wxid in self.checked_wxids else "☐"
            prefix = "⏭ " if skip else ""
            cnt_str = f"{count}" if count > 0 else ("..." if has_msg else "0")
            item = self.tree.insert("", tk.END, values=(checked, prefix + display, cnt_str, wxid))
            self._tree_items[wxid] = item
            showed += 1

        total = len(self._all_rows)
        all_groups = sum(1 for r in self._all_rows if r[3])
        all_named = sum(1 for r in self._all_rows
                        if r[4] and not r[3] and not r[1].startswith(("brand","gh_")))
        all_active = sum(1 for r in self._all_rows if r[5])
        all_friends = total - all_groups - sum(1 for r in self._all_rows if r[1].startswith(("brand","gh_")))

        # 列头排序指示
        asc = " ▲" if self._sort_asc else " ▼"
        self.tree.heading("name", text="显示名" + (asc if self._sort_col == "name" else ""))
        self.tree.heading("count", text="消息数" + (asc if self._sort_col == "count" else ""))

        hint = f"好友:{all_friends} 群:{all_groups} 备注:{all_named} 活跃:{all_active} | "
        self.session_info.config(text=f"{hint}显示 {showed}/{total} 个会话")
        self._update_check_count()

    # ════════════ 导出页 ════════════

    def _on_tab_change(self, event):
        nb = event.widget
        if nb.tab(nb.select(), "text").strip() == "  📤 导出  ":
            self._update_export_info()

    def _get_checked_wxids(self):
        return sorted(self.checked_wxids)

    def _build_export_page(self):
        f = ttk.Frame(self.page_export, padding=20)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="导出设置", font=("", 16, "bold")).pack(anchor=tk.W)

        ff = ttk.Frame(f)
        ff.pack(fill=tk.X, pady=(15, 5))
        ttk.Label(ff, text="导出格式:", width=10).pack(side=tk.LEFT)
        self.fmt_var = tk.StringVar(value="html")
        self.fmt_combo = ttk.Combobox(ff, textvariable=self.fmt_var,
                                       values=["html","csv","xlsx","pdf","txt","json"],
                                       state="readonly", width=8)
        self.fmt_combo.pack(side=tk.LEFT)

        ttk.Label(ff, text="  上限:").pack(side=tk.LEFT, padx=(20, 0))
        self.limit_var = tk.StringVar(value="0")
        ttk.Spinbox(ff, from_=0, to=50000, increment=500,
                    textvariable=self.limit_var, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Label(ff, text="(0=全部)", foreground="gray").pack(side=tk.LEFT)

        of = ttk.Frame(f)
        of.pack(fill=tk.X, pady=5)
        self.img_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(of, text="导出图片", variable=self.img_var).pack(side=tk.LEFT)
        self.sg_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(of, text="跳过群聊", variable=self.sg_var).pack(side=tk.LEFT, padx=15)
        self.so_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(of, text="跳过公众号", variable=self.so_var).pack(side=tk.LEFT, padx=5)

        df = ttk.Frame(f)
        df.pack(fill=tk.X, pady=5)
        ttk.Label(df, text="输出目录:", width=10).pack(side=tk.LEFT)
        self.out_var = tk.StringVar(value=OUTPUT_DIR)
        ttk.Entry(df, textvariable=self.out_var, width=55).pack(side=tk.LEFT, padx=5)
        ttk.Button(df, text="浏览", command=lambda: self.out_var.set(
            filedialog.askdirectory(initialdir=self.out_var.get()) or self.out_var.get()
        )).pack(side=tk.LEFT)

        self.export_info = ttk.Label(f, text="请先在「会话」页 ☑ 勾选要导出的会话", foreground="gray")
        self.export_info.pack(anchor=tk.W, pady=(10, 0))

        pf = ttk.Frame(f)
        pf.pack(fill=tk.X, pady=(15, 5))
        self.prog_var = tk.IntVar(value=0)
        self.prog = ttk.Progressbar(pf, variable=self.prog_var, length=600)
        self.prog.pack(fill=tk.X)
        self.prog_label = ttk.Label(f, text="", foreground="gray")
        self.prog_label.pack(anchor=tk.W)

        bf = ttk.Frame(f)
        bf.pack(pady=(10, 0))
        self.export_btn = ttk.Button(bf, text="🚀 开始导出", command=self._do_export, width=20)
        self.export_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="📋 打开输出目录",
                   command=lambda: os.startfile(self.out_var.get()) if os.path.isdir(self.out_var.get()) else None
                   ).pack(side=tk.LEFT, padx=5)

    def _update_export_info(self):
        wxids = self._get_checked_wxids()
        if wxids:
            self.export_info.config(
                text=f"已勾选 {len(wxids)} 个会话（可在「会话」页用 ☑ 调整）", foreground="green")
        else:
            self.export_info.config(
                text="请先在「会话」页 ☑ 勾选要导出的会话", foreground="gray")

    def _do_export(self):
        if not self.db:
            messagebox.showwarning("提示", "请先在「会话」页连接数据库")
            return
        wxids = self._get_checked_wxids()
        if not wxids:
            messagebox.showwarning("提示", "请先在「会话」页 ☑ 勾选要导出的会话")
            return

        self._save_selection()  # 自动保存

        fmt = self.fmt_var.get()
        limit = int(self.limit_var.get() or "0")
        img = self.img_var.get()
        out_dir = self.out_var.get()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(out_dir, f"export_{ts}")
        os.makedirs(out_dir, exist_ok=True)

        my_wxid = ""
        dd = self.data_dir
        if dd and os.path.isdir(dd):
            for d in os.listdir(dd):
                if d.startswith("wxid_") and os.path.isdir(os.path.join(dd, d)):
                    my_wxid = "_".join(d.split("_")[:2])
                    break

        self.export_btn.config(state=tk.DISABLED)
        self.prog_var.set(0)
        self.prog_label.config(text="准备中...")

        threading.Thread(target=self._export_thread,
                         args=(wxids, fmt, limit, img, out_dir, my_wxid),
                         daemon=True).start()

    def _export_thread(self, wxids, fmt, limit, img, out_dir, my_wxid):
        total = len(wxids)
        ok, fail = 0, []
        self.prog["maximum"] = total

        for i, wxid in enumerate(wxids):
            display = self.nick_map.get(wxid, wxid)
            self.root.after(0, lambda d=display, n=i+1:
                            self.prog_label.config(text=f"[{n}/{total}] {d[:40]} ..."))
            self.root.after(0, self.prog_var.set, i)
            try:
                r_ok, r_path, counts = export_one(
                    self.db, wxid, display, out_dir, fmt, limit,
                    my_wxid=my_wxid, images=img, data_dir=self.data_dir)
                if r_ok: ok += 1
                else: fail.append((display, r_path))
            except Exception as e:
                fail.append((display, str(e)[:60]))
            self.root.after(0, self.prog_var.set, i + 1)

        self.root.after(0, self.prog_var.set, total)
        self.root.after(0, lambda: self.prog_label.config(
            text=f"✅ 成功: {ok}  ❌ 失败: {len(fail)}  📁 {out_dir}"))
        self.root.after(0, lambda: self.export_btn.config(state=tk.NORMAL))
        msg = f"导出完成！\n✅ 成功: {ok}\n❌ 失败: {len(fail)}\n\n📁 {out_dir}"
        if fail:
            msg += "\n\n失败列表:\n" + "\n".join(f"  {d[:30]}: {r}" for d, r in fail[:10])
        self.root.after(0, lambda: messagebox.showinfo("导出完成", msg))


def main():
    app = App()
    app.root.mainloop()


if __name__ == "__main__":
    main()
