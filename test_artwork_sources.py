#!/usr/bin/env python3
"""Unit tests for javdatabase/DMM artwork resolution (no network)."""
import unittest

from src.weekly import dmm, javdatabase, mgs
from src.weekly.artwork import prefer_urls, resolve


class TestMgsParse(unittest.TestCase):
    def test_parse_siro_product_html(self):
        html = """
        <html><title>SIRO-5711 test</title>
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/pb_e_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/pf_o1_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/cap_e_0_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/cap_e_2_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/shirouto/siro/5711/cap_t1_0_siro-5711.jpg">
        <img src="https://image.mgstage.com/images/prestige/abf/371/pb_e_abf-371.jpg">
        </html>
        """
        art = mgs.parse_artwork(html, "SIRO-5711")
        self.assertIsNotNone(art)
        self.assertEqual(art["source"], "mgs")
        self.assertIn("pb_e_siro-5711.jpg", art["cover"])
        self.assertEqual(len(art["samples"]), 2)
        self.assertIn("cap_e_0", art["samples"][0])
        self.assertIn("cap_e_2", art["samples"][1])

    def test_parse_empty_product(self):
        html = "<html><title>エロ動画</title><body>no match</body></html>"
        self.assertIsNone(mgs.parse_artwork(html, "ATID-677"))

    def test_protocol_relative_urls(self):
        html = '<img src="//image.mgstage.com/images/prestige/abf/371/pb_e_abf-371.jpg">'
        art = mgs.parse_artwork(html, "ABF-371")
        self.assertIsNotNone(art)
        self.assertTrue(art["cover"].startswith("https://"))


class TestJavdatabaseParse(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(javdatabase.slug_for("TENN-049"), "tenn-049")
        self.assertEqual(javdatabase.slug_for(" oftr-011 "), "oftr-011")

    def test_parse_detail_html(self):
        html = """
        <html><head>
        <title>TENN-049 - Mana Mochida - JAV Database</title>
        <meta property="og:image" content="https://pics.dmm.co.jp/digital/video/h_491tenn00049/h_491tenn00049pl.jpg" />
        <link rel="preload" href="https://www.javdatabase.com/covers/full/h_/h_491tenn00049pl.webp" as="image" />
        </head><body>
        <p class="mb-1"><b>DVD ID: </b>TENN-049</p>
        <p class="mb-1"><b>Content ID: </b>h_491tenn00049</p>
        <div data-image-src="https://pics.dmm.co.jp/digital/video/h_491tenn00049/h_491tenn00049jp-2.jpg"></div>
        <div data-image-src="https://pics.dmm.co.jp/digital/video/h_491tenn00049/h_491tenn00049jp-1.jpg"></div>
        </body></html>
        """
        art = javdatabase.parse_artwork(html, "TENN-049")
        self.assertIsNotNone(art)
        self.assertEqual(art["source"], "javdatabase")
        self.assertIn("h_491tenn00049pl.jpg", art["cover"])
        self.assertEqual(art["cid"], "h_491tenn00049")
        self.assertEqual(len(art["samples"]), 2)
        self.assertIn("jp-1", art["samples"][0])
        self.assertIn("jp-2", art["samples"][1])

    def test_parse_404_template(self):
        html = "<html><title>Page Not Found - JAV Database</title><body>" + ("x" * 600) + "</body></html>"
        self.assertIsNone(javdatabase.parse_artwork(html, "ABF-371"))


class TestDmmCid(unittest.TestCase):
    def test_abf_cids(self):
        cids = dmm.cid_candidates("ABF-371")
        self.assertIn("abf00371", cids)
        self.assertIn("1abf00371", cids)
        self.assertIn("118abf371", cids)

    def test_iesp_prefix(self):
        cids = dmm.cid_candidates("IESP-762")
        self.assertTrue(any(c.startswith("1iesp") or c.startswith("iesp") for c in cids))

    def test_fc2_empty(self):
        self.assertEqual(dmm.cid_candidates("FC2-1234567"), [])

    def test_is_real_image_rejects_tiny(self):
        self.assertFalse(dmm.is_real_image(b"\xff\xd8\xff" + b"\x00" * 100))


class TestPreferOrder(unittest.TestCase):
    def test_prefer_javdatabase_over_dmm(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_dmm = dmm.fetch_artwork

        def fake_jdb(code):
            return {
                "source": "javdatabase",
                "cover": "https://pics.dmm.co.jp/digital/video/h_491tenn00049/h_491tenn00049pl.jpg",
                "samples": [
                    "https://pics.dmm.co.jp/digital/video/h_491tenn00049/h_491tenn00049jp-1.jpg"
                ],
            }

        def fake_dmm(code, samples=True):
            self.fail("DMM should not be called when javdatabase has cover+samples")

        try:
            javdatabase.fetch_artwork = fake_jdb
            dmm.fetch_artwork = fake_dmm
            cover, samples, src = prefer_urls(
                "TENN-049",
                cover="https://example.com/old.jpg",
                fanarts=["https://example.com/old-s.jpg"],
            )
            self.assertEqual(src, "javdatabase")
            self.assertIn("h_491tenn00049pl", cover)
            self.assertEqual(len(samples), 1)
        finally:
            javdatabase.fetch_artwork = orig_jdb
            dmm.fetch_artwork = orig_dmm

    def test_fallback_dmm_when_javdatabase_miss(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_dmm = dmm.fetch_artwork

        def fake_jdb(code):
            return None

        def fake_dmm(code, samples=True):
            return {
                "source": "dmm",
                "cover": "https://pics.dmm.com/digital/video/1iesp762/1iesp762pl.jpg",
                "samples": ["https://pics.dmm.com/digital/video/1iesp762/1iesp762jp-1.jpg"],
            }

        try:
            javdatabase.fetch_artwork = fake_jdb
            dmm.fetch_artwork = fake_dmm
            cover, samples, src = prefer_urls("IESP-762", cover="", fanarts=[])
            self.assertEqual(src, "dmm")
            self.assertIn("1iesp762", cover)
            self.assertEqual(len(samples), 1)
        finally:
            javdatabase.fetch_artwork = orig_jdb
            dmm.fetch_artwork = orig_dmm

    def test_fallback_caller_urls(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_dmm = dmm.fetch_artwork
        try:
            javdatabase.fetch_artwork = lambda code: None
            dmm.fetch_artwork = lambda code, samples=True: None
            cover, samples, src = prefer_urls(
                "UNKNOWN-1",
                cover="https://javbus.example/cover.jpg",
                fanarts=["https://javbus.example/s1.jpg"],
            )
            self.assertEqual(src, "")
            self.assertEqual(cover, "https://javbus.example/cover.jpg")
            self.assertEqual(samples, ["https://javbus.example/s1.jpg"])
        finally:
            javdatabase.fetch_artwork = orig_jdb
            dmm.fetch_artwork = orig_dmm

    def test_jdb_cover_only_merges_dmm_samples(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_dmm = dmm.fetch_artwork

        def fake_jdb(code):
            return {
                "source": "javdatabase",
                "cover": "https://pics.dmm.co.jp/digital/video/x/xpl.jpg",
                "samples": [],
            }

        def fake_dmm(code, samples=True):
            if not samples:
                return None
            return {
                "source": "dmm",
                "cover": "https://pics.dmm.com/digital/video/y/ypl.jpg",
                "samples": ["https://pics.dmm.com/digital/video/y/yjp-1.jpg"],
            }

        try:
            javdatabase.fetch_artwork = fake_jdb
            dmm.fetch_artwork = fake_dmm
            cover, samples, src = prefer_urls("X-1", cover="", fanarts=[])
            self.assertEqual(src, "javdatabase+dmm")
            self.assertIn("/x/xpl.jpg", cover)
            self.assertEqual(len(samples), 1)
        finally:
            javdatabase.fetch_artwork = orig_jdb
            dmm.fetch_artwork = orig_dmm


if __name__ == "__main__":
    unittest.main()
