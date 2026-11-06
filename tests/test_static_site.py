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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(HERE, "docs")
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


if __name__ == "__main__":
    unittest.main()
