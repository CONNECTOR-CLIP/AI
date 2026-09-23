import unittest

from cot5.cutoff import filter_by_date


class CutoffTests(unittest.TestCase):
    def test_no_cutoff_keeps_everything(self):
        papers = [{"title": "a", "year": 2030}]
        kept, dropped = filter_by_date(papers, None)
        self.assertEqual(kept, papers)
        self.assertEqual(dropped, [])

    def test_drops_paper_published_after_cutoff_by_publicationDate(self):
        papers = [{"title": "leaked", "publicationDate": "2027-01-01"}]
        kept, dropped = filter_by_date(papers, "2026-08-18")
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_keeps_paper_published_before_cutoff(self):
        papers = [{"title": "old", "publicationDate": "2020-01-01"}]
        kept, dropped = filter_by_date(papers, "2026-08-18")
        self.assertEqual(kept, papers)
        self.assertEqual(dropped, [])

    def test_year_only_paper_in_cutoff_year_is_kept_conservatively(self):
        # cutoff이 2026-08-18일 때, year=2026인 논문은 "그 해 안의 알 수 없는 날짜"이므로
        # 12월 31일로 보수적으로 취급해 cutoff 이후로 걸러진다(연도만으로는 판단 불가하니 과감히
        # 통과시키기보다 걸러내는 쪽을 택함).
        papers = [{"title": "same-year", "year": 2026}]
        kept, dropped = filter_by_date(papers, "2026-08-18")
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_unknown_date_is_kept_not_dropped(self):
        papers = [{"title": "no-date"}]
        kept, dropped = filter_by_date(papers, "2026-08-18")
        self.assertEqual(kept, papers)
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
