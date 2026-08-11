#!/usr/bin/env python3
"""Unit tests for javdatabase/DMM artwork resolution (no network)."""
import unittest

from src.weekly import chinese_forum, dmm, javdatabase, mgs
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
        <p class="mb-1"><b>Release Date: </b>2026-07-17</p>
        <p class="mb-1"><b>Runtime: </b>150 min.</p>
        <p class="mb-1"><b>Genre(s): </b><a>Athlete</a> <a>Big Tits</a></p>
        <p class="mb-1"><b>Idol(s)/Actress(es): </b><a>Mana Mochida</a></p>
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
        meta = javdatabase.parse_metadata(html, "TENN-049")
        self.assertEqual(meta["actresses"], ["Mana Mochida"])
        self.assertEqual(meta["genres"], ["Athlete", "Big Tits"])
        self.assertEqual(meta["duration"], "150分钟")
        self.assertEqual(meta["releaseDate"], "2026-07-17")

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

    def test_all_search_filters_to_exact_code(self):
        html = """
        <a href="/mono/dvd/-/detail/=/cid=140gs2143/"><img src="other.jpg"></a>
        <a href="https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=140gs2144/"><img src="exact.jpg"></a>
        <a href="/mono/dvd/-/detail/=/cid=140gs21440/"><img src="similar.jpg"></a>
        """
        products = dmm.parse_all_search_products(html, "GS-2144")
        self.assertEqual([item["cid"] for item in products], ["140gs2144"])

    def test_all_search_accepts_redirect_and_zero_padded_cid(self):
        url = "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=h_173spsf00027/"
        products = dmm.parse_all_search_products("", "SPSF-27", url)
        self.assertEqual([item["cid"] for item in products], ["h_173spsf00027"])

    def test_all_search_accepts_amateur_product_cover(self):
        html = """
        <a href="https://video.dmm.co.jp/amateur/content/?id=peep180&amp;i3_ref=search">
          <img src="https://pics.dmm.co.jp/digital/amateur/peep180/peep180jp.jpg">
        </a>
        """
        products = dmm.parse_all_search_products(html, "PEEP-180")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["kind"], "digital")
        self.assertEqual(products[0]["cid"], "peep180")
        self.assertIn("peep180jp.jpg", products[0]["cover"])

    def test_cover_only_prefers_all_category_result(self):
        original_search = dmm.search_all_products
        original_first = dmm._first_real
        original_candidates = dmm.cid_candidates
        try:
            product = {
                "kind": "digital",
                "cid": "peep180",
                "page": "https://video.dmm.co.jp/amateur/content/?id=peep180",
                "cover": "https://pics.dmm.co.jp/digital/amateur/peep180/peep180jp.jpg",
            }
            dmm.search_all_products = lambda code, with_status=False: (
                ([product], True) if with_status else [product]
            )
            dmm._first_real = lambda urls, timeout=12: (urls[0], b"real")
            dmm.cid_candidates = lambda code: self.fail("heuristics should not run after search hit")
            art = dmm.fetch_cover_only("PEEP-180")
            self.assertEqual(art["cid"], "peep180")
            self.assertIn("peep180jp.jpg", art["cover"])
        finally:
            dmm.search_all_products = original_search
            dmm._first_real = original_first
            dmm.cid_candidates = original_candidates

    def test_digital_search_uses_graphql_samples(self):
        original_search = dmm.search_all_products
        original_detail = dmm._fetch_digital_metadata
        original_first = dmm._first_real
        try:
            product = {
                "kind": "digital",
                "cid": "peep180",
                "page": "https://video.dmm.co.jp/amateur/content/?id=peep180",
                "cover": "https://example.test/search-cover.jpg",
            }
            dmm.search_all_products = lambda code, with_status=False: (
                ([product], True) if with_status else [product]
            )
            dmm._fetch_digital_metadata = lambda cid, code="", page="": {
                "cover": "https://example.test/graphql-cover.jpg",
                "samples": [
                    "https://example.test/jp-001.jpg",
                    "https://example.test/jp-002.jpg",
                ],
            }
            dmm._first_real = lambda urls, timeout=12: (urls[0], b"real")
            art = dmm.fetch_artwork("PEEP-180", samples=True)
            self.assertEqual(art["cover"], "https://example.test/graphql-cover.jpg")
            self.assertEqual(art["samples"], [
                "https://example.test/jp-001.jpg",
                "https://example.test/jp-002.jpg",
            ])
        finally:
            dmm.search_all_products = original_search
            dmm._fetch_digital_metadata = original_detail
            dmm._first_real = original_first

    def test_metadata_falls_back_to_verified_cid_candidates(self):
        original_search = dmm.search_all_products
        original_candidates = dmm.cid_candidates
        original_digital = dmm.fetch_digital_metadata_candidates
        try:
            dmm.search_all_products = lambda code, with_status=False: []
            dmm.cid_candidates = lambda code: ["pred00880", "pred880"]
            dmm.fetch_digital_metadata_candidates = lambda code, cids, page="": {
                "cid": "pred00880",
                "actresses": ["音無鈴"],
                "genres": ["中出し"],
                "duration": "116分钟",
                "releaseDate": "2026-07-21",
            }
            meta = dmm.fetch_metadata("PRED-880")
            self.assertEqual(meta["cid"], "pred00880")
            self.assertEqual(meta["actresses"], ["音無鈴"])
        finally:
            dmm.search_all_products = original_search
            dmm.cid_candidates = original_candidates
            dmm.fetch_digital_metadata_candidates = original_digital

    def test_successful_empty_search_uses_verified_graphql_not_cdn_bruteforce(self):
        original_search = dmm.search_all_products
        original_candidates = dmm.cid_candidates
        original_digital = dmm.fetch_digital_metadata_candidates
        original_probe = dmm.probe_cid
        try:
            dmm.search_all_products = lambda code, with_status=False: (
                ([], True) if with_status else []
            )
            dmm.cid_candidates = lambda code: ["none00999"]
            dmm.fetch_digital_metadata_candidates = lambda code, cids, page="": None
            dmm.probe_cid = lambda *args, **kwargs: self.fail("blind CDN probing must stay disabled")
            self.assertIsNone(dmm.fetch_cover_only("NONE-999"))
        finally:
            dmm.search_all_products = original_search
            dmm.cid_candidates = original_candidates
            dmm.fetch_digital_metadata_candidates = original_digital
            dmm.probe_cid = original_probe


class TestForumArtwork(unittest.TestCase):
    def test_weekly_list_canonicalizes_v_variant(self):
        html = """
        <tbody id="normalthread_3654606">
          <a href="thread-3654606-1-1.html" class="xst">
            START-612V 【特典版】人生初のナマ中出し解禁
          </a>
        </tbody>
        """
        items, stats = chinese_forum.parse_list_html(
            html, purpose="weekly", fid="37"
        )
        self.assertEqual(stats["with_id"], 1)
        self.assertEqual(items[0]["id"], "START-612")
        self.assertTrue(items[0]["title"].startswith("START-612 "))

    def test_extracts_full_first_post_images(self):
        html = """
        <td class="t_f" id="postmessage_1">
        <img src="static/image/common/none.gif"
             zoomfile="https://img.example.test/cover.jpg"
             file="https://img.example.test/cover.jpg" inpost="1">
        <img src="static/image/common/none.gif"
             zoomfile="/attachments/sample.jpg" inpost="1">
        </td>
        <td class="t_f" id="postmessage_2">
        <img zoomfile="https://img.example.test/reply.jpg" inpost="1">
        </td>
        <img src="/static/image/avatar.png">
        """
        self.assertEqual(
            chinese_forum.extract_thread_images(html, "https://forum.example.test/thread-1.html"),
            [
                "https://img.example.test/cover.jpg",
                "https://forum.example.test/attachments/sample.jpg",
            ],
        )


class TestPreferOrder(unittest.TestCase):
    def test_cover_only_prefers_mgs_before_dmm(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_mgs = mgs.fetch_artwork
        orig_mgs_quality = mgs.cover_meets_min_size
        orig_dmm = dmm.fetch_artwork

        try:
            javdatabase.fetch_artwork = lambda code: None
            mgs.fetch_artwork = lambda code: {
                "source": "mgs",
                "cover": "https://image.mgstage.com/example/pb_e.jpg",
                "samples": [],
            }
            mgs.cover_meets_min_size = lambda url: True
            dmm.fetch_artwork = lambda code, samples=True: self.fail(
                "DMM should not run after MGS cover hit"
            )
            cover, samples, src = prefer_urls("MGS-001", cover_only=True)
            self.assertIn("mgstage.com", cover)
            self.assertEqual(samples, [])
            self.assertEqual(src, "mgs")
        finally:
            javdatabase.fetch_artwork = orig_jdb
            mgs.fetch_artwork = orig_mgs
            mgs.cover_meets_min_size = orig_mgs_quality
            dmm.fetch_artwork = orig_dmm

    def test_low_res_mgs_cover_falls_through_to_dmm(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_mgs = mgs.fetch_artwork
        orig_mgs_quality = mgs.cover_meets_min_size
        orig_dmm = dmm.fetch_artwork

        try:
            javdatabase.fetch_artwork = lambda code: None
            mgs.fetch_artwork = lambda code: {
                "source": "mgs",
                "cover": "https://image.mgstage.com/example/pf_o1.jpg",
                "samples": [],
            }
            mgs.cover_meets_min_size = lambda url: False

            def fake_dmm(code, samples=True):
                self.assertFalse(samples)
                return {
                    "source": "dmm",
                    "cover": "https://pics.dmm.co.jp/example/large.jpg",
                    "samples": [],
                }

            dmm.fetch_artwork = fake_dmm
            cover, samples, src = prefer_urls("LOW-001", cover_only=True)
            self.assertIn("large.jpg", cover)
            self.assertEqual(samples, [])
            self.assertEqual(src, "mgs+dmm")
        finally:
            javdatabase.fetch_artwork = orig_jdb
            mgs.fetch_artwork = orig_mgs
            mgs.cover_meets_min_size = orig_mgs_quality
            dmm.fetch_artwork = orig_dmm

    def test_cover_only_dmm_does_not_probe_samples(self):
        orig_jdb = javdatabase.fetch_artwork
        orig_mgs = mgs.fetch_artwork
        orig_dmm = dmm.fetch_artwork

        try:
            javdatabase.fetch_artwork = lambda code: None
            mgs.fetch_artwork = lambda code: None

            def fake_dmm(code, samples=True):
                self.assertFalse(samples)
                return {
                    "source": "dmm",
                    "cover": "https://pics.dmm.co.jp/mono/movie/adult/140gs2144/140gs2144pl.jpg",
                    "samples": [],
                }

            dmm.fetch_artwork = fake_dmm
            cover, samples, src = prefer_urls("GS-2144", cover_only=True)
            self.assertIn("140gs2144", cover)
            self.assertEqual(samples, [])
            self.assertEqual(src, "dmm")
        finally:
            javdatabase.fetch_artwork = orig_jdb
            mgs.fetch_artwork = orig_mgs
            dmm.fetch_artwork = orig_dmm

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
