#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微信聊天记录导出工具 v3.0 —— 独立版
=====================================
python export.py                          # 导出全部
python export.py -f csv                   # CSV 格式
python export.py --list                   # 列出所有会话
python export.py --images                 # 含图片
python export.py --whitelist "张三,李四"   # 白名单
python export.py key --force              # 获取密钥
python export.py --skip-groups            # 跳过群聊
"""

import os, sys, json, time, datetime, shutil, argparse, subprocess
import http.client, socket, threading, ctypes, hashlib, base64, re

# ---- 路径（一切相对于本脚本所在目录） ----
# PyInstaller 兼容：打包后文件在 sys._MEIPASS
if getattr(sys, "frozen", False):
    HERE = sys._MEIPASS
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")
RUNTIME = os.path.join(HERE, "runtime")
EXPORTERS = os.path.join(HERE, "exporters")
RESOURCES = os.path.join(HERE, "resources")
sys.path.insert(0, EXPORTERS)

# 数据和输出目录（软件目录下，便携设计）
DATA_DIR = os.path.join(HERE, "data")
OUTPUT_DIR = os.path.join(HERE, "output")
KEY_FILE = os.path.join(DATA_DIR, "key.txt")
CONFIG_FILE = os.path.join(HERE, "export_config.json")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 兼容旧版：从桌面 wx_export 迁移密钥
_OLD_OUT = os.path.join(os.environ.get("USERPROFILE", HERE), "Desktop", "wx_export")
_OLD_KEY = os.path.join(_OLD_OUT, "key.txt")
if os.path.exists(_OLD_KEY) and not os.path.exists(KEY_FILE):
    import shutil as _shutil
    _shutil.copy2(_OLD_KEY, KEY_FILE)
    try:
        _OLD_IMG = os.path.join(_OLD_OUT, "image_key.json")
        if os.path.exists(_OLD_IMG):
            _shutil.copy2(_OLD_IMG, os.path.join(DATA_DIR, "image_key.json"))
    except Exception:
        pass

# ---- 工具 ----
def sanitize(name):
    for ch in '<>:"/\\|?*': name = name.replace(ch, "_")
    return name.strip()[:50]

def find_node():
    """密钥捕获用：裸 Node.js"""
    # 1. 本地 runtime/node.exe
    local_n = os.path.join(RUNTIME, "node.exe")
    if os.path.exists(local_n): return local_n
    # 2. PATH 上的 node
    return shutil.which("node") or shutil.which("node.exe") or ""

def find_runtime():
    """WCDB 服务用：Electron（WCDB 需要 Electron 初始化）"""
    # 1. 本地 electron（项目自带）
    local_e = os.path.join(HERE, "electron", "electron.exe")
    if os.path.exists(local_e): return local_e
    # 2. 用户目录下的安装
    home = os.environ.get("USERPROFILE", "")
    for scan_root in [os.path.join(home, "Desktop"),
                      os.path.join(home, "Downloads"),
                      home]:
        if not os.path.isdir(scan_root): continue
        try:
            for root, dirs, _ in os.walk(scan_root):
                depth = root[len(scan_root):].count(os.sep)
                if depth > 3: dirs.clear(); continue
                ep = os.path.join(root, "electron", "electron.exe")
                if os.path.exists(ep): return ep
        except: pass
    # 3. 回退
    return find_node()

# ---- 密钥 ----
def load_key():
    if os.path.exists(KEY_FILE):
        k = open(KEY_FILE).read().strip()
        if len(k) == 64: return k
    return ""

def extract_key():
    """获取密钥，失败时抛 RuntimeError 而非 exit（兼容 GUI）"""
    print("\n" + "=" * 56)
    print("  获取微信数据库密钥")
    print("=" * 56)
    print("  1. 关闭微信 -> 2. 按回车 -> 3. 打开微信登录")
    print("  正在启动密钥捕获...")
    node = find_node()
    js = os.path.join(SCRIPTS, "get_key.js")
    if not node or not os.path.exists(js):
        raise RuntimeError(f"找不到运行时: node={node}, js={js}")
    sf = os.path.join(DATA_DIR, "key_status.txt")
    for f in [sf, KEY_FILE]:
        if os.path.exists(f): os.remove(f)
    print(f"  [*] {node}")
    # 用 cmd /c start 启动，确保弹出独立控制台窗口显示提示
    cmd = f'cmd /c start "WeChat Key Extraction" "{node}" "{js}"'
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe",
        f'/c start "WeChat Key" cmd /c "chcp 65001 >nul && \"{node}\" \"{js}\" \"{DATA_DIR}\" && pause"', None, 1)
    if ret <= 32:
        # 回退：普通权限运行
        subprocess.Popen([node, js], creationflags=subprocess.CREATE_NEW_CONSOLE)
    smap = {"started":"启动","dll_found":"找到DLL","dll_loaded":"DLL加载",
            "waiting_close":"等待微信关闭...","waiting_start":"等待微信启动 -- 现在打开微信登录！",
            "injecting":"注入Hook...","hook_ok":"Hook成功","polling":"等待密钥...",
            "captured":"已捕获!","dll_not_found":"找不到wx_key.dll",
            "hook_failed":"Hook失败","timeout_poll":"超时"}
    last = ""
    for i in range(150):
        if os.path.exists(KEY_FILE):
            k = open(KEY_FILE).read().strip()
            if len(k) == 64: print(f"\n  OK 密钥: {k[:16]}..."); return k
        if os.path.exists(sf):
            try:
                st = open(sf, encoding="utf-8").read().strip()
                pref = st.split(":")[0]
                msg = smap.get(pref, st)
                if msg != last: print(f"  [*] {msg}"); last = msg
            except: pass
        time.sleep(1)
    raise RuntimeError("获取密钥超时 (150s)")

# ---- WCDB 服务 ----
class WCDB:
    def __init__(self):
        self.proc = None; self.port = 0; self.out = []
    def start(self, key, data_dir=""):
        node = find_runtime()
        server = os.path.join(SCRIPTS, "wcdb_server.js")
        if not node: raise RuntimeError("找不到Node.js运行时")
        self.port = self._fp(); self.out = []
        print(f"  [*] {node}  :{self.port}")
        args = [node, server, key, str(self.port)]
        if data_dir: args.append(data_dir)
        self.proc = subprocess.Popen(args, cwd=SCRIPTS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=self._r, daemon=True).start()
        last = 0
        for _ in range(45):
            if self.proc.poll() is not None:
                time.sleep(0.5)
                raise RuntimeError(f"服务退出({self.proc.returncode})\n"+("\n".join(self.out[-20:]) or "(无输出)"))
            while last < len(self.out): print(f"  [wcdb] {self.out[last]}"); last += 1
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
                c.request("GET", "/ping")
                if c.getresponse().read().decode() == "pong": print("  OK 服务就绪"); return
            except: pass
            time.sleep(1)
        raise RuntimeError("启动超时\n"+("\n".join(self.out[-30:])))
    def stop(self):
        if self.proc:
            try: self.proc.terminate()
            except: pass
    def _get(self, p):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        c.request("GET","/"+p); d = c.getresponse().read().decode("utf-8"); c.close()
        return json.loads(d)
    def _post(self, p, data):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        b = json.dumps(data); c.request("POST","/"+p,b,{"Content-Type":"application/json"})
        d = c.getresponse().read().decode("utf-8"); c.close()
        return json.loads(d)
    def sessions(self): return self._get("sessions")
    def messages(self, wxid, limit=500, offset=0): return self._get(f"messages/{wxid}/{limit}/{offset}")
    def count(self, wxid): return int(self._get(f"count/{wxid}"))
    def names(self, wxids): return self._post("displaynames", wxids)
    def resolve_images(self, reqs): return self._post("resolve_image_batch", reqs)
    @staticmethod
    def _fp():
        s = socket.socket(); s.bind(("127.0.0.1",0)); p = s.getsockname()[1]; s.close(); return p
    def _r(self):
        try:
            for line in iter(self.proc.stdout.readline, b""):
                d = line.decode("utf-8",errors="replace").strip()
                if d: self.out.append(d)
        except: pass

# ---- 配置 ----
DEFAULT_CFG = {"blacklist":{"wxids":[],"names":[],"keywords":[],"skip_groups":True,"skip_official":True},
               "whitelist":{"wxids":[],"names":[],"keywords":[]}}

def load_config(path=""):
    p = path or CONFIG_FILE
    if os.path.exists(p):
        try: return {**DEFAULT_CFG, **json.load(open(p,encoding="utf-8"))}
        except: pass
    json.dump(DEFAULT_CFG, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    return dict(DEFAULT_CFG)

def should_skip(wxid, display, cfg, cli_wl=None, cli_bl=None, skip_groups=False, skip_official=True):
    wl = cfg.get("whitelist",{})
    if cli_wl or wl.get("wxids") or wl.get("names") or wl.get("keywords"):
        ids = (cli_wl or []) + wl.get("wxids", [])
        if wxid in ids or display in ids or display in wl.get("names",[]): return False
        if any(k.lower() in display.lower() for k in wl.get("keywords",[])): return False
        return True
    bl = cfg.get("blacklist",{})
    if wxid in (cli_bl or []) or wxid in bl.get("wxids",[]): return True
    if display in (cli_bl or []) or display in bl.get("names",[]): return True
    if any(k.lower() in display.lower() for k in bl.get("keywords",[])): return True
    if skip_official or bl.get("skip_official",True):
        if wxid.startswith("brand") or wxid.startswith("gh_"): return True
    if skip_groups or bl.get("skip_groups",False):
        if wxid.endswith("@chatroom"): return True
    return False

# ---- 导出 ----
def export_one(db, wxid, display, out_dir, fmt, limit, my_wxid="", images=False, data_dir=""):
    ext = {"html":".html","csv":".csv","xlsx":".xlsx","pdf":".pdf","txt":".txt","json":".json"}[fmt]
    total = db.count(wxid)
    if total == 0: return False, "无消息", {}
    rows = []
    if limit > 0:
        rows = db.messages(wxid, limit, 0)
    else:
        off = 0
        while off < total:
            chunk = db.messages(wxid, 500, off)
            if not chunk: break
            rows.extend(chunk); off += len(chunk)
            if len(chunk) < 500: break
    if not rows: return False, "获取失败", {}
    texts, imgs = [], []
    for m in rows:
        lt = int(m.get("local_type",0))
        if lt in (1, 244813135921): texts.append(m)
        elif lt == 3 and images: imgs.append(m)
    img_done = 0
    if imgs: img_done = _decrypt_imgs(db, imgs)
    all_msgs = texts + imgs
    all_msgs.sort(key=lambda m: int(m.get("create_time","0") or "0"))
    if not all_msgs: return False, "无内容", {}
    senders = list(set(m.get("sender_username","") for m in all_msgs if m.get("sender_username","")))
    if wxid not in senders: senders.append(wxid)
    nm = {}
    if senders:
        try: nm = db.names(senders)
        except: pass
    for m in all_msgs:
        sr = m.get("sender_username","")
        if sr in nm: m["sender_username"] = nm[sr]
        if sr == my_wxid: m["is_mine"] = 1
    safe = sanitize(display)
    path = os.path.join(out_dir, safe + ext)
    n = 1
    while os.path.exists(path): path = os.path.join(out_dir, f"{safe}_{n}{ext}"); n += 1
    if img_done > 0 and fmt == "html":
        img_dir = os.path.join(out_dir, f"{safe}_images")
        os.makedirs(img_dir, exist_ok=True)
        for i, im in enumerate(imgs):
            b64 = im.get("_image_data","")
            ex = im.get("_image_ext","jpg")
            if b64:
                try:
                    with open(os.path.join(img_dir, f"{i:04d}.{ex}"), "wb") as f:
                        f.write(base64.b64decode(b64))
                    im["_image_src"] = f"{safe}_images/{i:04d}.{ex}"
                except: pass
    if fmt in ("txt","json"): _write_text(open(path,"w",encoding="utf-8"), all_msgs, fmt)
    else: _write_ext(all_msgs, path, fmt, display)
    return True, path, {"text_count": len(texts), "img_count": img_done}

def _decrypt_imgs(db, imgs):
    try:
        from image_decoder import decrypt_dat
        from packed_info_parser import parse_image_info
    except ImportError: return 0
    for m in imgs:
        info = parse_image_info(m)
        m["_img_md5"] = info.get("md5","")
        m["_img_aeskey"] = info.get("aeskey","")
    md5s = [m.get("_img_md5") for m in imgs if m.get("_img_md5")]
    if not md5s: return 0
    try: resolved = db.resolve_images([{"md5":m} for m in md5s])
    except: resolved = []
    pmap = {r.get("md5",""): r.get("path","") for r in resolved if r.get("path")}
    ikf = os.path.join(DATA_DIR, "image_key.json")
    ik = {}
    if os.path.exists(ikf):
        try: ik = json.load(open(ikf,encoding="utf-8"))
        except: pass
    done = 0
    for m in imgs:
        md5 = m.get("_img_md5","")
        dp = pmap.get(md5,"")
        if not dp or not os.path.exists(dp): continue
        aeskey = m.get("_img_aeskey","")
        xk = 0
        for acct in ik.get("accounts",[]):
            for k in acct.get("keys",[]):
                c = k.get("code",0)
                if c:
                    xk = c & 0xFF
                    if not aeskey:
                        aeskey = hashlib.md5((str(c)+acct.get("wxid","")).encode()).hexdigest()[:16]
        try:
            ext, data = decrypt_dat(dp, xor_key=xk, aes_key=aeskey)
            if data and len(data) > 100:
                m["_image_data"] = base64.b64encode(data).decode("ascii")
                m["_image_ext"] = ext.lstrip(".") if ext else "jpg"
                done += 1
        except: pass
    return done

def _write_text(f, msgs, fmt):
    if fmt == "txt":
        for m in msgs:
            ts = m.get("create_time","")
            sr = m.get("sender_username","")
            name = "我" if m.get("is_mine") else sr
            if ts.isdigit(): ts = datetime.datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M")
            lt = int(m.get("local_type",0))
            if lt in (1,244813135921): f.write(f"[{ts}] {name}\n{m.get('message_content','') or ''}\n\n")
            elif lt == 3: f.write(f"[{ts}] {name}\n{m.get('_image_src','') or '[图片]'}\n\n")
    elif fmt == "json":
        out = []
        for m in msgs:
            ts = m.get("create_time","")
            if ts.isdigit(): ts = datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
            lt = int(m.get("local_type",0))
            e = {"time":ts,"sender":m.get("sender_username",""),"type":lt,"is_mine":m.get("is_mine",0)}
            if lt in (1,244813135921): e["content"] = m.get("message_content","")
            elif lt == 3: e["image"] = m.get("_image_src","")
            out.append(e)
        json.dump(out, f, ensure_ascii=False, indent=2)

def _write_ext(msgs, path, fmt, display):
    import importlib.util
    mm = {"html":"html","csv":"csv","xlsx":"excel","pdf":"pdf"}
    mn = mm[fmt]
    ep = os.path.join(EXPORTERS, f"{mn}_exporter.py")
    spec = importlib.util.spec_from_file_location(f"wx_{mn}", ep)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for m in msgs:
        if int(m.get("local_type",0)) == 3:
            s = m.get("_image_src","")
            m["message_content"] = f'<img src="{s}" style="max-width:400px;border-radius:8px">' if s else "[图片]"
            m["local_type"] = "1"
    mod.export(msgs, path, my_name="我", title=f"{display}聊天记录")

# ---- 列表 ----
def _detect_dd():
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None,5,None,0,buf)
        docs = buf.value
    except: docs = os.path.join(os.environ.get("USERPROFILE","C:"),"Documents")
    for base in {docs, os.path.join(os.environ.get("USERPROFILE",""),"Documents")}:
        for sub in ["xwechat_files","WeChat Files"]:
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                try:
                    for e in os.listdir(d):
                        if e.startswith("wxid_") and os.path.isdir(os.path.join(d,e)): return d
                except: pass
    return ""

def cmd_list(args):
    key = load_key()
    if not key: print("X 未找到密钥，先运行: python export.py key"); return
    dd = args.data_dir or _detect_dd()
    if not dd: print("X 未检测到数据目录，用 --data-dir 指定"); return
    db = WCDB()
    try: db.start(key, dd)
    except RuntimeError as e: print(f"X {e}"); return
    sessions = db.sessions()
    print(f"共 {len(sessions)} 个会话\n")
    all_u = [s.get("username","") for s in sessions if s.get("username","") and not s.get("username","").startswith("brand")]
    nm = {}
    if all_u:
        try: nm = db.names(all_u[:500])
        except: pass
    cfg = load_config(args.config)
    cli_wl = [x.strip() for x in args.whitelist.split(",") if x.strip()] if getattr(args,'whitelist',None) else None
    cli_bl = [x.strip() for x in args.blacklist.split(",") if x.strip()] if getattr(args,'blacklist',None) else None
    so = not getattr(args,'no_skip_official',False)
    entries = []
    for s in sessions:
        wxid = s.get("username","")
        if not wxid: continue
        d = nm.get(wxid, wxid)
        sk = should_skip(wxid, d, cfg, cli_wl, cli_bl, getattr(args,'skip_groups',False), so)
        entries.append({"wxid":wxid,"display":d,"skip":sk})
    entries.sort(key=lambda e: (e["skip"], e["display"].lower()))
    if args.filter:
        kw = args.filter.lower()
        entries = [e for e in entries if kw in e["wxid"].lower() or kw in e["display"].lower()]
    print(f"  {'':5s} {'消息数':>6s}  {'显示名':<35s}  wxid")
    print("  " + "-" * 85)
    exp = 0
    for e in entries:
        flag = "  SKIP" if e["skip"] else f" [{exp+1:3d}]"
        if not e["skip"]: exp += 1
        try: cnt = db.count(e["wxid"]); cs = f"{cnt:>6d}"
        except: cs = "     ?"
        print(f"  {flag:5s} {cs}  {e['display'][:33]:<35s}  {e['wxid'][:30]}")
        sys.stdout.flush()
    db.stop()
    skn = sum(1 for e in entries if e["skip"])
    print(f"\n  总计:{len(entries)} | 导出:{exp} | 跳过:{skn}")
    print(f"  编辑 export_config.json 调整过滤后运行: python export.py")

# ---- export 命令 ----
def cmd_export(args):
    print("=" * 56)
    print("  微信聊天记录导出 v3.0")
    print("=" * 56)
    key = None if getattr(args,'rekey',False) else load_key()
    if key: print(f"OK 密钥: {key[:16]}...")
    else: key = extract_key(); open(KEY_FILE,"w").write(key)
    dd = args.data_dir or _detect_dd()
    if not dd: print("X 未检测到数据目录"); return
    print(f"数据目录: {dd}")
    db = WCDB()
    try: db.start(key, dd)
    except RuntimeError as e: print(f"X {e}"); return
    sessions = db.sessions(); print(f"已连接 {len(sessions)} 个会话")
    all_u = [s.get("username","") for s in sessions if s.get("username","") and not s.get("username","").startswith("brand")]
    nm = {}
    if all_u:
        try: nm = db.names(all_u[:500])
        except: pass
    cfg = load_config(getattr(args,'config',''))
    cli_wl = [x.strip() for x in getattr(args,'whitelist','').split(",") if x.strip()] if getattr(args,'whitelist',None) else None
    cli_bl = [x.strip() for x in getattr(args,'blacklist','').split(",") if x.strip()] if getattr(args,'blacklist',None) else None
    so = not getattr(args,'no_skip_official',False); sg = getattr(args,'skip_groups',False)
    filtered = []; skn = 0
    for s in sessions:
        wxid = s.get("username",""); d = nm.get(wxid,wxid)
        if should_skip(wxid,d,cfg,cli_wl,cli_bl,sg,so): skn += 1
        else: filtered.append(s)
    if skn: print(f"过滤跳过: {skn} 个")
    if not filtered: print("无会话（全被过滤），先用 --list 查看"); db.stop(); return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.output or os.path.join(OUTPUT_DIR, f"export_{ts}")
    os.makedirs(out, exist_ok=True)
    my_wxid = ""
    if dd:
        for d in os.listdir(dd):
            if d.startswith("wxid_") and os.path.isdir(os.path.join(dd,d)):
                my_wxid = "_".join(d.split("_")[:2]); break
    fmt = args.format; lim = args.limit
    print(f"格式:{fmt} | {'全部' if lim==0 else f'上限{lim}条'} | 图片:{'是' if args.images else '否'}")
    print(f"输出: {out}\n")
    ok, fail = 0, []
    for i, s in enumerate(filtered):
        wxid = s.get("username",""); d = nm.get(wxid,wxid); cnt = db.count(wxid)
        print(f"  [{i+1}/{len(filtered)}] {d[:30]} ({cnt}条) ...", end="", flush=True)
        try:
            r_ok, r_path, counts = export_one(db, wxid, d, out, fmt, lim, my_wxid, args.images, dd)
            if r_ok:
                fn = os.path.basename(r_path); ps = [f"{counts.get('text_count',0)}条文字"]
                if counts.get('img_count',0): ps.append(f"{counts['img_count']}张图")
                print(f"\r  [{i+1}/{len(filtered)}] OK {d[:30]} -> {fn} ({', '.join(ps)})"); ok += 1
            else: print(f"\r  [{i+1}/{len(filtered)}] X {d[:30]} - {r_path}"); fail.append((d,r_path))
        except Exception as e:
            print(f"\r  [{i+1}/{len(filtered)}] X {d[:30]} - {e}"); fail.append((d,str(e)[:60]))
    db.stop()
    print(f"\n  OK:{ok}  SKIP:{skn}  FAIL:{len(fail)}")
    print(f"  {out}")

# ---- CLI ----
def main():
    p = argparse.ArgumentParser(description="微信聊天记录导出 v3.0")
    sub = p.add_subparsers(dest="cmd")
    pe = sub.add_parser("export", help="导出聊天记录")
    pe.add_argument("-f","--format",default="html",choices=["html","csv","xlsx","pdf","txt","json"])
    pe.add_argument("-o","--output",default="")
    pe.add_argument("-l","--limit",type=int,default=0,help="消息上限(0=全部)")
    pe.add_argument("--images",action="store_true",help="导出图片")
    pe.add_argument("--data-dir",default="")
    pe.add_argument("--filter",default="")
    pe.add_argument("--rekey",action="store_true")
    pe.add_argument("--config",default="")
    pe.add_argument("--skip-groups",action="store_true")
    pe.add_argument("--no-skip-official",action="store_true")
    pe.add_argument("--whitelist",default="")
    pe.add_argument("--blacklist",default="")
    pe.add_argument("-v","--verbose",action="store_true")
    pl = sub.add_parser("list", help="列出所有会话")
    pl.add_argument("--data-dir",default="")
    pl.add_argument("--config",default="")
    pl.add_argument("--filter",default="")
    pl.add_argument("--skip-groups",action="store_true")
    pl.add_argument("--no-skip-official",action="store_true")
    pl.add_argument("--whitelist",default="")
    pl.add_argument("--blacklist",default="")
    pg = sub.add_parser("gui", help="启动图形界面")
    pk = sub.add_parser("key", help="获取密钥")
    pk.add_argument("--force",action="store_true")
    args = p.parse_args()
    if args.cmd == "gui":
        from gui import main as gui_main
        gui_main()
    elif args.cmd == "export": cmd_export(args)
    elif args.cmd == "list": cmd_list(args)
    elif args.cmd == "key":
        k = load_key()
        if k and not getattr(args,'force',False): print(f"OK 已有密钥: {k[:16]}...")
        else: k = extract_key(); open(KEY_FILE,"w").write(k); print(f"OK 已保存")
    else:
        # 无子命令时默认启动 GUI
        from gui import main as gui_main
        gui_main()

if __name__ == "__main__":
    main()
