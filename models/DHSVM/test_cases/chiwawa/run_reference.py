#!/usr/bin/env python3
"""Run the official DHSVM Chiwawa test case (TestCase/Chiwawa, DHSVM 3.2) and check expected.json.

Foundation case for the DHSVM KI. The input data (3.66 GB, mostly Livneh gridded forcing)
is NOT in git: it lives in the versioned Netdisk pack DHSVM/chiwawa_v1, listed file by file
(bytes + sha256) in manifest.json["pack"]["files"].

Pack lookup: --pack-dir -> $DHSVM_PACK_DIR -> server copy -> cache dir
($KISS_PACK_CACHE or ~/.cache/kiss_packs)/DHSVM/chiwawa_v1 -> automatic download from the
Baidu share link in manifest.json into that cache dir. Every file is checked (bytes + sha256)
before the run; any problem -> exit 3 "MISSING/BAD DATA ... NOT run."
--no-server-pack (or KISS_NO_SERVER_PACK=1) skips the server copy; --no-download turns
the download off.

Run: the official config INPUT.Chiwawa.Baseline is used unchanged. It names its files as
../../TestCase/Chiwawa/..., so the temp dir is laid out as <tmp>/TestCase/Chiwawa/ (input/
and modelstate/ copied, LivnehForcing/ linked read-only to the pack) and the config sits in
<tmp>/run/case/, two levels down. The empty output/ folder is made first (the repo does not
ship it). DHSVM is run through the KI tool tools/run_dhsvm.py (it runs in the config's folder).

Exit 0 PASS, 2 checks failed, 3 engine or data missing/bad.
Binary lookup: --dhsvm-bin -> $DHSVM_BIN -> `which DHSVM` -> server default.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAN = json.loads((HERE / "manifest.json").read_text())
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_dhsvm.py"
_DEF_BIN = "/mnt/disk1/Hydrocraft_server/models/DHSVM/source/repo/build/DHSVM/sourcecode/DHSVM"
CONFIG = "INPUT.Chiwawa.Baseline"

# ---------------------------------------------------------------------------
# Data pack: find it, or download it from the Baidu Netdisk share link, then
# check EVERY file (bytes + sha256) against manifest.json before any run.
# Same block in every KISS case whose data lives in a Netdisk pack.
# ---------------------------------------------------------------------------
import hashlib, http.cookiejar as _cj, json as _json, os as _os, sys as _sys, time as _time
import urllib.parse as _up, urllib.request as _ur
from pathlib import Path as _P

_UA_WEB = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120 Safari/537.36")
_UA_DL = "pan.baidu.com"   # Baidu CDN refuses some client UAs (error 31326)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def file_ok(root, rel, meta):
    p = _P(root) / rel
    return p.is_file() and p.stat().st_size == meta["bytes"] and _sha256(p) == meta["sha256"]


def verify_pack(root, files):
    """Return list of problems ([] = every file present with right bytes + sha256)."""
    bad = []
    for rel, meta in files.items():
        p = _P(root) / rel
        if not p.is_file():
            bad.append(f"missing {rel}")
        elif p.stat().st_size != meta["bytes"]:
            bad.append(f"size {rel}: {p.stat().st_size} != {meta['bytes']}")
        elif _sha256(p) != meta["sha256"]:
            bad.append(f"sha256 {rel}")
    return bad


def _baidu_cookies():
    """BDUSS + STOKEN of a logged-in Baidu account (needed to download a share).
    1) $KISS_BAIDU_COOKIES = "BDUSS=...; STOKEN=..."   2) the BaiduPCS-Py account store."""
    env = _os.environ.get("KISS_BAIDU_COOKIES", "").strip()
    if env:
        return env
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from baidupcs_py.app.account import AccountManager
        from baidupcs_py.commands.env import ACCOUNT_DATA_PATH
        ck = AccountManager.load_data(ACCOUNT_DATA_PATH).who().pcsapi()._baidupcs.cookies
        if ck.get("BDUSS") and ck.get("STOKEN"):
            return f"BDUSS={ck['BDUSS']}; STOKEN={ck['STOKEN']}"
    except Exception:
        pass
    return ""


class _Share:
    """Minimal Baidu share-link reader: verify code -> list tree -> per-file dlink."""

    def __init__(self, url, pwd, cookies):
        # Baidu is a domestic service: go DIRECT, never through an http(s)_proxy.
        # A cookie jar keeps the cookies Baidu sets during verify (needed by sharedownload).
        self.jar = _cj.CookieJar()
        for part in cookies.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                self.jar.set_cookie(_cj.Cookie(0, k, v, None, False, ".baidu.com", True, True, "/",
                                               True, True, None, False, None, None, {}))
        self.op = _ur.build_opener(_ur.ProxyHandler({}), _ur.HTTPCookieProcessor(self.jar))
        self.surl = _up.urlparse(url).path.rstrip("/").split("/")[-1]   # "1xxxx"
        self.pwd = pwd
        self._refresh()
        root = self._list(None)
        self.share_id, self.uk = root["share_id"], root["uk"]
        self.root_items = root["list"]

    def _refresh(self):
        """(Re)check the share code and get a fresh sign/timestamp (Baidu's expire after ~10 min)."""
        v = self._json("POST", "https://pan.baidu.com/share/verify",
                       {"surl": self.surl[1:], "t": str(int(_time.time() * 1000)),
                        "channel": "chunlei", "web": "1", "clienttype": "0"},
                       {"pwd": self.pwd, "vcode": "", "vcode_str": ""})
        if v.get("errno") != 0:
            raise RuntimeError(f"share verify failed: {v}")
        self.randsk = v["randsk"]
        self.jar.set_cookie(_cj.Cookie(0, "BDCLND", self.randsk, None, False, ".baidu.com", True, True,
                                       "/", True, True, None, False, None, None, {}))
        t = self._json("GET", "https://pan.baidu.com/share/tplconfig",
                       {"surl": self.surl, "fields": "sign,timestamp", "view_mode": "1",
                        "channel": "chunlei", "web": "1", "app_id": "250528", "clienttype": "0"})
        if t.get("errno") != 0:
            raise RuntimeError(f"share tplconfig failed (login cookies ok?): {t}")
        self.sign, self.ts = t["data"]["sign"], t["data"]["timestamp"]
        self.t_sign = _time.time()

    def _json(self, method, url, params, data=None, referer=None):
        q = url + "?" + _up.urlencode(params)
        body = _up.urlencode(data).encode() if data is not None else None
        req = _ur.Request(q, data=body, method=method, headers={
            "User-Agent": _UA_WEB,
            "Referer": referer or "https://pan.baidu.com/s/" + self.surl})
        with self.op.open(req, timeout=60) as r:
            return _json.loads(r.read().decode())

    def _list(self, d, page=1):
        p = {"shorturl": self.surl[1:], "page": str(page), "num": "100", "web": "1",
             "channel": "chunlei", "clienttype": "0", "order": "name"}
        if d is None:
            p["root"] = "1"
        else:
            p["dir"] = d
        r = self._json("GET", "https://pan.baidu.com/share/list", p)
        if r.get("errno") != 0:
            raise RuntimeError(f"share list failed for {d}: {r}")
        return r

    def walk(self, remote_root):
        """{relative path: (fs_id, size)} for every file under the shared folder."""
        out, todo = {}, [i["path"] for i in self.root_items if str(i["isdir"]) == "1"]
        for i in self.root_items:
            if str(i["isdir"]) != "1":
                out[_os.path.relpath(i["path"], remote_root)] = (int(i["fs_id"]), int(i["size"]))
        while todo:
            d, page = todo.pop(), 1
            while True:
                items = self._list(d, page).get("list", [])
                for i in items:
                    if str(i["isdir"]) == "1":
                        todo.append(i["path"])
                    else:
                        out[_os.path.relpath(i["path"], remote_root)] = (int(i["fs_id"]), int(i["size"]))
                if len(items) < 100:
                    break
                page += 1
        return out

    def dlinks(self, fs_ids):
        if _time.time() - self.t_sign > 300:
            self._refresh()
        for attempt in range(5):
            r = self._json("POST", "https://pan.baidu.com/api/sharedownload",
                           {"sign": self.sign, "timestamp": self.ts, "channel": "chunlei",
                            "web": "1", "app_id": "250528", "clienttype": "0"},
                           {"encrypt": "0", "extra": _json.dumps({"sekey": _up.unquote(self.randsk)}),
                            "fid_list": _json.dumps(fs_ids), "primaryid": str(self.share_id),
                            "uk": str(self.uk), "product": "share", "type": "nolimit"})
            # 112 = sign expired; -20 = Baidu wants a captcha after many quick requests.
            # Both clear after a pause + fresh verify/sign: back off and ask again.
            if r.get("errno") in (112, -20) and attempt < 4:
                _time.sleep(0 if r.get("errno") == 112 else 30 * (attempt + 1))
                self._refresh()
                continue
            break
        if r.get("errno") != 0:
            raise RuntimeError(f"sharedownload failed: {r}")
        if not isinstance(r.get("list"), list):
            return {}   # Baidu gives no plain link (seen for files > ~50 MB): caller uses fallback
        return {int(i["fs_id"]): i["dlink"] for i in r["list"]}

    def transfer(self, fs_id, remote_dir):
        """Save one shared file into the logged-in account's own netdisk (remote_dir)."""
        t = self._json("GET", "https://pan.baidu.com/api/gettemplatevariable",
                       {"fields": '["bdstoken"]', "channel": "chunlei", "web": "1", "clienttype": "0"})
        tok = t["result"]["bdstoken"]
        self._json("POST", "https://pan.baidu.com/api/create",
                   {"a": "commit", "bdstoken": tok, "channel": "chunlei", "web": "1", "clienttype": "0"},
                   {"path": remote_dir, "isdir": "1", "block_list": "[]"})
        r = self._json("POST", "https://pan.baidu.com/share/transfer",
                       {"shareid": str(self.share_id), "from": str(self.uk), "bdstoken": tok,
                        "channel": "chunlei", "web": "1", "clienttype": "0"},
                       {"fsidlist": _json.dumps([fs_id]), "path": remote_dir})
        return r

    def fetch(self, dlink, dest):
        req = _ur.Request(dlink, headers={"User-Agent": _UA_DL})
        tmp = _P(str(dest) + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with self.op.open(req, timeout=120) as r, open(tmp, "wb") as fo:
            for b in iter(lambda: r.read(1 << 20), b""):
                fo.write(b)
        tmp.replace(dest)


def _pcs_bin():
    import shutil as _sh
    for c in (_os.environ.get("BAIDUPCS_BIN"), _sh.which("BaiduPCS-Py"),
              "/mnt/disk1/Hydrocraft_server/python_env/bin/BaiduPCS-Py"):
        if c and _os.path.isfile(c) and _os.access(c, _os.X_OK):
            return c
    return None


def _pcs(args, timeout=3600):
    import subprocess as _sp
    env = {k: v for k, v in _os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}   # Baidu = direct
    return _sp.run([_pcs_bin()] + args, env=env, capture_output=True, text=True, timeout=timeout)


def _pcs_get(remote_file, dest):
    """Download one file of the logged-in account's own netdisk with BaiduPCS-Py."""
    import shutil as _sh, tempfile as _tf
    tmpd = _P(_tf.mkdtemp(prefix="kiss_pcs_", dir=str(_P(dest).parent)))
    try:
        p = _pcs(["download", remote_file, "-o", str(tmpd)])
        got = [q for q in tmpd.rglob(_P(remote_file).name) if q.is_file()]
        if not got:
            raise RuntimeError(f"BaiduPCS-Py download gave no file: {(p.stdout + p.stderr)[-300:]}")
        _sh.move(str(got[0]), str(dest))
    finally:
        _sh.rmtree(tmpd, ignore_errors=True)


def _fetch_big(sh, pack, rel, fs_id, size, dest):
    """Fallback for a file the share gives no plain link for (large files).
    (a) the account already holds the pack at remote_path (e.g. the owner) -> download that copy;
    (b) otherwise save the file from the share into /_kiss_pack_tmp/ of the account, download it,
        then delete the temp copy. Both need BaiduPCS-Py logged in to the same account."""
    if not _pcs_bin():
        raise RuntimeError(f"{rel}: Baidu gives no direct share link for this file and BaiduPCS-Py "
                           f"is not installed (needed for large files)")
    own = pack["remote_path"].rstrip("/") + "/" + rel
    try:
        lst = sh._json("GET", "https://pan.baidu.com/api/list",
                       {"dir": str(_P(own).parent), "web": "1", "app_id": "250528", "clienttype": "0",
                        "limit": "10000"}, referer="https://pan.baidu.com/disk/home").get("list", [])
    except Exception:
        lst = []
    if any(i.get("server_filename") == _P(own).name and int(i.get("size", -1)) == size for i in lst):
        print(f"[pack]   {rel}: large file, using the account's own copy at {own}", flush=True)
        _pcs_get(own, dest)
        return
    tmp_remote = f"/_kiss_pack_tmp/{pack['name']}_{int(_time.time())}"
    r = sh.transfer(fs_id, tmp_remote)
    if r.get("errno") != 0:
        raise RuntimeError(f"{rel}: could not save it from the share into your netdisk: {r}")
    try:
        print(f"[pack]   {rel}: large file, saved from the share to {tmp_remote}, downloading", flush=True)
        _pcs_get(tmp_remote + "/" + _P(rel).name, dest)
    finally:
        _pcs(["remove", tmp_remote], timeout=300)


def download_pack(pack, dest):
    """Download every manifest file of the pack from its share link into dest."""
    ck = _baidu_cookies()
    if not ck:
        raise RuntimeError("no Baidu login cookies: set KISS_BAIDU_COOKIES='BDUSS=...; STOKEN=...' "
                           "(from a browser logged in to pan.baidu.com) or log in BaiduPCS-Py")
    t0 = _time.time()
    sh = _Share(pack["share_url"], pack["share_pwd"], ck)
    remote = sh.walk(pack["remote_path"])
    files = pack["files"]
    todo = [rel for rel, m in files.items() if not file_ok(dest, rel, m)]
    lost = [rel for rel in todo if rel not in remote]
    if lost:
        raise RuntimeError(f"{len(lost)} manifest files not in the share, e.g. {lost[:3]}")
    print(f"[pack] downloading {len(todo)} of {len(files)} files from {pack['share_url']} "
          f"-> {dest}", flush=True)
    done_b = 0
    # One file per sharedownload call: Baidu asks for a captcha (errno -20) on multi-file
    # requests once an account has downloaded a lot, while single-file requests still work.
    for k, rel in enumerate(todo, 1):
        fid = remote[rel][0]
        link = sh.dlinks([fid]).get(fid)
        if link is None:   # no plain share link (big file): BaiduPCS-Py fallback
            _fetch_big(sh, pack, rel, fid, files[rel]["bytes"], _P(dest) / rel)
        else:
            for attempt in range(6):
                try:
                    sh.fetch(link, _P(dest) / rel)
                    break
                except Exception as e:
                    if attempt == 5:
                        raise RuntimeError(f"download failed for {rel}: {e}")
                    _time.sleep(5 * (attempt + 1))
                    try:  # a used/expired dlink can give 403: ask for a fresh one
                        link = sh.dlinks([fid]).get(fid, link)
                    except Exception:
                        pass
        done_b += files[rel]["bytes"]
        if k % 20 == 0 or k == len(todo):
            print(f"[pack]   {k}/{len(todo)} files, {done_b / 1e6:.0f} MB, "
                  f"{_time.time() - t0:.0f} s", flush=True)
    print(f"[pack] download finished in {_time.time() - t0:.0f} s", flush=True)


def resolve_pack(pack, ki, pack_dir_arg, cache_arg, no_server, no_download):
    """Lookup: --pack-dir -> $<KI>_PACK_DIR -> server default copy -> cache dir ->
    auto-download into cache dir. Returns a verified pack dir, or exits 3."""
    name = f"{ki}/{pack['name']}"
    explicit = pack_dir_arg or _os.environ.get(f"{ki.upper()}_PACK_DIR")
    no_server = no_server or _os.environ.get("KISS_NO_SERVER_PACK") == "1"
    cache_root = cache_arg or _os.environ.get("KISS_PACK_CACHE") or str(_P.home() / ".cache" / "kiss_packs")
    cache = _P(cache_root) / ki / pack["name"]

    def bad_exit(where, problems):
        print(f"MISSING/BAD DATA: pack {name} at {where}: {len(problems)} problem(s), e.g. "
              f"{problems[:3]}. NOT run.", file=_sys.stderr)
        _sys.exit(3)

    def how_to():
        return (f"Get it from Baidu Netdisk: {pack['share_url']} (code {pack['share_pwd']}), "
                f"folder {pack['remote_path']} ; then pass --pack-dir <folder> "
                f"or set {ki.upper()}_PACK_DIR.")

    if explicit:
        if not _P(explicit).is_dir():
            print(f"MISSING/BAD DATA: pack dir {explicit} does not exist. {how_to()} NOT run.",
                  file=_sys.stderr)
            _sys.exit(3)
        b = verify_pack(explicit, pack["files"])
        if b:
            bad_exit(explicit, b)
        print(f"[pack] using {explicit} (all {len(pack['files'])} files verified)")
        return explicit
    if not no_server and _P(pack["server_default"]).is_dir():
        b = verify_pack(pack["server_default"], pack["files"])
        if b:
            bad_exit(pack["server_default"], b)
        print(f"[pack] using server copy {pack['server_default']} "
              f"(all {len(pack['files'])} files verified)")
        return pack["server_default"]
    if cache.is_dir() and not verify_pack(cache, pack["files"]):
        print(f"[pack] using cache {cache} (all {len(pack['files'])} files verified)")
        return str(cache)
    if no_download:
        print(f"MISSING/BAD DATA: pack {name} not found locally and download is off. "
              f"{how_to()} NOT run.", file=_sys.stderr)
        _sys.exit(3)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        download_pack(pack, cache)
    except Exception as e:
        print(f"MISSING/BAD DATA: could not download pack {name}: {e}. Files already fetched stay "
              f"in {cache} and a re-run resumes. {how_to()} NOT run.", file=_sys.stderr)
        _sys.exit(3)
    b = verify_pack(cache, pack["files"])
    if b:
        bad_exit(cache, b)
    print(f"[pack] downloaded pack verified: all {len(pack['files'])} files match manifest.json")
    return str(cache)
# ---------------------------------------------------------------------------


def find_bin(arg):
    for c in (arg, os.environ.get("DHSVM_BIN"), shutil.which("DHSVM"), _DEF_BIN):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)   # the run starts in a temp dir
    return None


def mass_final(fp):
    """Mass.Final.Balance -> {label: value (mm)}."""
    out = {}
    for line in open(fp):
        m = re.match(r"\s*([A-Za-z/ ()]+?)\s*\.{3,}\s*([-+0-9.eE]+)\s*$", line)
        if m:
            out[m.group(1).strip()] = float(m.group(2))
    return out


def measure(out_dir, report):
    o = Path(out_dir)
    mb = mass_final(o / "Mass.Final.Balance")
    q = [float(l.split()[1]) for l in open(o / "Streamflow.Only")
         if len(l.split()) == 2 and l[:1].isdigit()]
    agg = [l.split() for l in open(o / "Aggregated.Values")][1:]
    swq = [float(r[8]) for r in agg if len(r) > 8]
    bad = 0
    for f in o.iterdir():
        if f.is_file():
            bad += len(re.findall(r"(?i)(?<![a-z])(nan|inf)(?![a-z])", f.read_text(errors="replace")))
    return {
        "returncode": report.get("returncode"),
        "end_of_model_run": int("END OF MODEL RUN" in (report.get("stdout_tail", "") +
                                                     report.get("stdout_head", ""))),
        "n_streamflow_steps": len(q),
        "n_aggregated_steps": len(swq),
        "flow_mean_m3_per_step": sum(q) / len(q) if q else None,
        "flow_max_m3_per_step": max(q) if q else None,
        "flow_last_m3_per_step": q[-1] if q else None,
        "swq_max_basin_mean_m": max(swq) if swq else None,
        "mb_total_inflow_mm": mb.get("Total Inflow"),
        "mb_precip_mm": mb.get("Precip/Inflow"),
        "mb_total_outflow_mm": mb.get("Total Outflow"),
        "mb_et_mm": mb.get("ET"),
        "mb_channel_int_mm": mb.get("ChannelInt"),
        "mb_storage_change_mm": mb.get("Storage Change"),
        "mb_final_swq_mm": mb.get("Final SWQ"),
        "mb_final_soil_moisture_mm": mb.get("Final Soil Moisture"),
        "mb_mass_error_mm": mb.get("Mass Error (mm)"),
        "nan_inf_tokens_in_outputs": bad,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dhsvm-bin")
    ap.add_argument("--pack-dir", help="local copy of the DHSVM/chiwawa_v1 pack")
    ap.add_argument("--cache-dir", help="where a downloaded pack is kept (default ~/.cache/kiss_packs)")
    ap.add_argument("--no-server-pack", action="store_true", help="skip the server's own copy")
    ap.add_argument("--no-download", action="store_true", help="never download; exit 3 if no pack")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    binp = find_bin(a.dhsvm_bin)
    if not binp:
        print("MISSING DEPENDENCY: DHSVM binary not found (use --dhsvm-bin or $DHSVM_BIN). NOT run.",
              file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL} not found. NOT run.", file=sys.stderr)
        return 3
    pack = resolve_pack(MAN["pack"], "DHSVM", a.pack_dir, a.cache_dir, a.no_server_pack, a.no_download)

    tmp = Path(tempfile.mkdtemp(prefix="dhsvm_chiwawa_"))
    try:
        case = tmp / "TestCase" / "Chiwawa"
        case.mkdir(parents=True)
        shutil.copytree(Path(pack) / "input", case / "input")
        shutil.copytree(Path(pack) / "modelstate", case / "modelstate")
        os.symlink(Path(pack).resolve() / "LivnehForcing", case / "LivnehForcing")
        (case / "output").mkdir()
        rdir = tmp / "run" / "case"
        rdir.mkdir(parents=True)
        shutil.copy(Path(pack) / CONFIG, rdir / CONFIG)
        rep = tmp / "run_report.json"
        t0 = time.time()
        p = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", binp,
                            "--config", str(rdir / CONFIG), "--timeout", "2400",
                            "--output", str(rep)], cwd=tmp, capture_output=True, text=True)
        el = time.time() - t0
        if not rep.is_file():
            print(p.stdout[-2000:], p.stderr[-2000:], sep="\n")
            print("FAIL: KI run tool wrote no report", file=sys.stderr)
            return 2
        report = json.loads(rep.read_text())
        print(f"[run] KI tool status={report.get('status')} returncode={report.get('returncode')} "
              f"elapsed={el:.0f} s")
        if report.get("detected_errors"):
            print(f"[run] KI tool text scan flags (see README 'Known KI gaps'): {report['detected_errors']}")
        try:
            got = measure(case / "output", report)
        except Exception as e:
            print(f"FAIL: could not read DHSVM outputs: {e}", file=sys.stderr)
            return 2
        fails = []
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            ok = v is not None and abs(v - c["expected"]) <= c["tol"]
            print(f"  {'ok  ' if ok else 'FAIL'} {c['name']}: got {v} expected {c['expected']} tol {c['tol']}")
            if not ok:
                fails.append(c["name"])
        if fails:
            print(f"FAIL: {len(fails)} check(s) failed: {fails}")
            return 2
        print(f"PASS: all {len(EXP['numeric_checks'])} checks match expected.json "
              f"(DHSVM Chiwawa 10/01/1970-10/01/1971, run {el:.0f} s)")
        return 0
    finally:
        if a.keep:
            print(f"[run] kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
