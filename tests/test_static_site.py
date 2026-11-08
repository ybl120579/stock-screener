# -*- coding: utf-8 -*-
"""静态站点自检：推上 GitHub Pages 之前，确保相对路径、数据文件都正常。

这些检查对应真实踩过的坑：
- 用了 `/api/...` 或 `src="/icon.png"` 这种绝对路径 → 部署到 /stock-screener/ 子路径后 404；
- history.json 里有某天但 archive 缺文件 → 点历史日期白屏；
- list.json 缺 rejects → 手机端“为什么没入选”失效。
"""
import io
import json
import os
import re
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(HERE, "docs")
DOCS_P = Path(DOCS)
DATA = os.path.join(DOCS, "data")

ABSOLUTE = re.compile(r'''(?:href|src|action)\s*=\s*["']/''', re.I)


def read(name):
    path = os.path.join(DOCS, name)
    if not os.path.exists(path):
        raise unittest.SkipTest("还没构建 docs/")
    return io.open(path, encoding="utf-8").read()


class TestStaticSite(unittest.TestCase):

    def test_html_uses_relative_paths(self):
        html = read("index.html")
        self.assertIsNone(ABSOLUTE.search(html), "index.html 里有以 / 开头的路径")

    def test_app_js_uses_base_prefix(self):
        js = read("app.js")
        self.assertIn("const BASE", js)
        # 逻辑路径（api('/api/list')）是对的，会被 apiStatic/apiLive 分发；
        # 真正危险的是直接 fetch 绝对路径 —— 部署到子路径后会 404。
        pat = re.compile("fetch\\(\\s*[\"'`]/(api|data)/")
        for m in pat.finditer(js):
            self.fail(f"app.js 直接 fetch 了绝对路径：{m.group(0)}")
        self.assertIn("apiStatic", js)
        self.assertIn("apiLive", js)

    def test_service_worker_shell_relative(self):
        sw = read("sw.js")
        shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S)
        self.assertIsNotNone(shell, "sw.js 里找不到 SHELL 列表")
        for url in re.findall(r"'([^']+)'", shell.group(1)):
            self.assertTrue(url.startswith("./"), f"SHELL 里有非相对路径：{url}")

    def test_manifest_relative(self):
        mf = json.loads(read("manifest.webmanifest"))
        self.assertTrue(mf.get("start_url", "").startswith("."))
        for icon in mf.get("icons", []):
            self.assertFalse(icon["src"].startswith("/"), icon)

    def test_list_json_shape(self):
        d = json.loads(io.open(os.path.join(DATA, "list.json"), encoding="utf-8").read())
        for k in ("trade_date", "count", "rows", "funnel", "weights", "rejects"):
            self.assertIn(k, d)
        self.assertEqual(len(d["rows"]), d["count"])
        if d["rows"]:
            self.assertIn("score", d["rows"][0])
            self.assertIn("spark", d["rows"][0])
        for r in d.get("rejects") or []:
            self.assertTrue(r.get("reason"), f"{r.get('code')} 没有原因")
            self.assertIn(r.get("stage"), d["funnel"])

    def test_history_matches_archive_files(self):
        hist = json.loads(io.open(os.path.join(DATA, "history.json"),
                                  encoding="utf-8").read())
        arch = os.path.join(DATA, "archive")
        for it in hist.get("items", []):
            self.assertTrue(os.path.exists(os.path.join(arch, it["date"] + ".json")),
                            f"history 有 {it['date']} 但 archive 缺文件")

    def test_copy_code_feature(self):
        """一键复制代码：卡片与详情页都有按钮，且点击优先于打开详情。"""
        js = io.open(os.path.join(DOCS, "app.js"), encoding="utf-8").read()
        self.assertIn("function copyText(", js, "缺少 copyText 实现")
        self.assertIn("data-copy", js, "卡片/详情缺少 data-copy 按钮")
        # 复制按钮必须排在 .card 开详情之前，否则点代码会误开详情
        i_copy = js.find("closest('[data-copy]')")
        i_card = js.find("closest('.card')")
        self.assertGreater(i_copy, -1, "点击委托里没有处理 [data-copy]")
        self.assertLess(i_copy, i_card, "[data-copy] 必须在 .card 之前拦截")
        css = io.open(os.path.join(DOCS, "style.css"), encoding="utf-8").read()
        self.assertIn("button.code", css, "缺少复制按钮样式")

    def test_status_has_next_run(self):
        st = json.loads(io.open(os.path.join(DATA, "status.json"),
                                encoding="utf-8").read())
        self.assertTrue(st.get("trade_date"))
        self.assertTrue(st.get("next_run"), "status.json 缺 next_run")
        self.assertGreater(st["next_run"], st["trade_date"], "next_run 应该晚于数据日期")


class TestTwoStores(unittest.TestCase):
    """两套系统的胶囊入口：主页要有切换条，docs/trend/ 要有自己的页面。"""

    def test_main_page_has_store_pills(self):
        html = (DOCS_P / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="stores"', html)
        self.assertIn("首板冷度", html)
        self.assertIn("强趋势", html)
        self.assertIn('href="trend/"', html)

    def test_trend_page_exists_and_links_back(self):
        page = DOCS_P / "trend" / "index.html"
        self.assertTrue(page.exists(), "docs/trend/index.html 不存在")
        html = page.read_text(encoding="utf-8")
        self.assertIn('href="../"', html)
        self.assertIn("强趋势", html)
        self.assertIn("强趋势", html)

    def test_trend_data_shape(self):
        data = json.loads((DOCS_P / "trend" / "data.json").read_text(encoding="utf-8"))
        for k in ("asof", "rows", "funnel", "market", "schedule"):
            self.assertIn(k, data)
        self.assertEqual(data["schedule"], "11:00")
        fun = data["funnel"]
        self.assertTrue(fun)
        first = fun[0]
        self.assertIsInstance(first, dict)
        self.assertIn("value", first)
        for r in data["rows"]:
            for k in ("code", "name", "price", "score", "stop", "target"):
                self.assertIn(k, r)
            self.assertLess(r["stop"], r["price"])
            self.assertGreater(r["target"], r["price"])


if __name__ == "__main__":
    unittest.main()

class TestTrendPage(unittest.TestCase):
    """强趋势页面的数据与静态资源（和首板页对齐到同一套能力）。"""

    def test_assets_copied(self):
        t = DOCS_P / "trend"
        for fn in ("index.html", "app.js", "style.css", "manifest.webmanifest", "sw.js"):
            self.assertTrue((t / fn).exists(), f"缺 {fn}")

    def test_app_has_core_features(self):
        js = (DOCS_P / "trend" / "app.js").read_text(encoding="utf-8")
        for feat in ("openSheet", "openFunnel", "openInfo", "copyText", "drawSpark", "drawKline", "whyLookup"):
            self.assertIn(f"function {feat}", js)
        self.assertIn("data-copy", js)

    def test_data_fields(self):
        d = json.loads((DOCS_P / "trend" / "data.json").read_text(encoding="utf-8"))
        for k in ("asof", "rows", "funnel", "stages", "rejects_list", "schedule"):
            self.assertIn(k, d)
        self.assertEqual(d["schedule"], "11:00")
        self.assertTrue(d["rows"], "名单为空")
        r = d["rows"][0]
        for k in ("code", "name", "score", "stop", "target", "bars", "spark", "pct"):
            self.assertIn(k, r)
        self.assertGreaterEqual(len(r["bars"]), 30)
        self.assertLess(r["stop"], r["price"])
        self.assertGreater(r["target"], r["price"])

class TestServiceWorker(unittest.TestCase):
    """外壳必须「网络优先」，否则新功能会被旧缓存挡住（真实踩过的坑）。"""

    def sw(self, rel):
        return (DOCS_P / rel / "sw.js").read_text(encoding="utf-8")

    def test_shell_is_network_first(self):
        for rel in ("", "trend"):
            src = self.sw(rel)
            self.assertIn("req.mode === 'navigate'", src, f"{rel}/sw.js 没有网络优先逻辑")
            # 外壳分支必须是「先 fetch，失败才 catch 回退」，而不是先读缓存
            self.assertIn("e.respondWith(fetch(req)", src, f"{rel}/sw.js 外壳不是网络优先")
            self.assertIn("c.navigate(c.url)", src, f"{rel}/sw.js 没有强制刷新旧页面")

    def test_version_is_stamped_at_build(self):
        import re
        main = re.search(r"const V = '([^']+)';", self.sw("")).group(1)
        trend = re.search(r"const V = '([^']+)';", self.sw("trend")).group(1)
        self.assertRegex(main, r"^sbcd-\d{14}$", "主页 sw.js 版本号没被构建改写")
        self.assertRegex(trend, r"^trend-\d{14}$", "趋势页 sw.js 版本号没被构建改写")

    def test_copy_prefers_sync_exec_command(self):
        """复制要先用同步 execCommand：http 局域网下 Clipboard API 不可用，
        之前的顺序会让手机浏览器直接报「复制失败」。"""
        for rel in ("", "trend"):
            src = (DOCS_P / rel / "app.js").read_text(encoding="utf-8")
            i_exec = src.index("document.execCommand('copy')")
            i_api = src.index("navigator.clipboard.writeText")
            self.assertLess(i_exec, i_api, f"{rel}/app.js 复制顺序不对")
