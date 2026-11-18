import unittest
from unittest import mock

from src.weekly import chinese_forum as forum


def _row(tid, code, author_em, last_em):
    return (f'<tbody id="normalthread_{tid}"><tr><th>'
            f'<a href="thread-{tid}-1-1.html" class="s xst">[{code}] 标题</a></th>'
            f'<td class="by"><cite><a href="space-uid-1.html">u</a></cite><em>{author_em}</em></td>'
            f'<td class="num"><a>1</a><em>2</em></td>'
            f'<td class="by"><cite><a>u</a></cite><em>{last_em}</em></td></tr></tbody>')


class ForumListPostDateTests(unittest.TestCase):
    # 2026-11-19 抓的 forum-103 第 25 页：一周前的帖子作者列是纯文本日期，最后回复列可能带「昨天」的 title。
    def test_post_date_comes_from_the_author_column(self):
        html = (_row(1, "SNOS-279", '<span><span title="2026-11-16">3&nbsp;天前</span></span>',
                     '<a href="x"><span title="2026-11-18 20:16">昨天&nbsp;20:16</span></a>')
                + _row(2, "ABF-001", '<span>2026-10-05</span>',
                       '<a href="x"><span title="2026-11-18 20:16">昨天&nbsp;20:16</span></a>')
                + _row(3, "ABF-002", '<span>2026-8-9</span>', '<a href="x">2026-11-04 23:02</a>'))
        items, _ = forum.parse_list_html(html, base="https://example.invalid", purpose="chinese", fid="103")
        self.assertEqual([i["postDate"] for i in items], ["2026-11-16", "2026-10-05", "2026-08-09"])

    def test_backfill_stops_at_the_post_date(self):
        pages = {1: _row(1, "AAA-001", "<span>2026-08-20</span>", "<a>2026-11-18 10:00</a>"),
                 2: _row(2, "AAA-002", "<span>2026-08-10</span>", "<a>2026-11-18 10:00</a>")}
        client = mock.Mock(_safe_ok=True, fid="103", base="https://example.invalid")
        client.fetch_list_page.side_effect = lambda page: pages.get(page, pages[2])
        with mock.patch.object(forum.time, "sleep"):
            items = forum.get_list_until(stop_date="2026-08-13", client=client)
        self.assertEqual([i["id"] for i in items], ["AAA-001"])
        self.assertEqual(client.fetch_list_page.call_count, 2)

    def test_repeated_last_page_stops_the_listing(self):
        # 翻过最后一页时站点重复返回最后一页；日期解析不出来也不能无限翻。
        last = _row(9, "ZZZ-009", "", "")
        client = mock.Mock(_safe_ok=True, fid="103", base="https://example.invalid")
        client.fetch_list_page.side_effect = lambda page: last
        with mock.patch.object(forum.time, "sleep"):
            items = forum.get_list_until(stop_date="2026-08-13", client=client)
        self.assertEqual([i["id"] for i in items], ["ZZZ-009"])
        self.assertEqual(client.fetch_list_page.call_count, 4)


if __name__ == "__main__":
    unittest.main()
