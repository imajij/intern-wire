import sqlite3
import unittest
from unittest.mock import patch

from app import db, picks
from app.scrapers import linkedin_posts


class LinkedInPostClassifierTests(unittest.TestCase):
    def test_accepts_a_hiring_post_with_an_application_route(self):
        text = (
            "Acme is hiring a Backend Engineering Intern. "
            "Apply by sending your resume to careers@acme.example."
        )

        self.assertTrue(linkedin_posts.is_internship_opening(text))

    def test_rejects_a_personal_internship_announcement_even_when_it_mentions_apply(self):
        text = (
            "Excited to share that I got selected as a summer intern. "
            "Apply these lessons to your next internship search."
        )

        self.assertFalse(linkedin_posts.is_internship_opening(text))

    def test_rejects_general_internship_discussion_without_an_application_route(self):
        text = "How to create compliant internships: a legal guide for employers hiring interns."

        self.assertFalse(linkedin_posts.is_internship_opening(text))

    @patch("app.scrapers.linkedin_posts.time.sleep")
    @patch("app.scrapers.linkedin_posts.DDGS")
    def test_scrape_keeps_only_the_qualifying_search_hit(self, ddgs_class, _sleep):
        ddgs = ddgs_class.return_value.__enter__.return_value
        ddgs.text.return_value = [
            {
                "href": "https://www.linkedin.com/posts/acme_hiring-intern-activity-1",
                "title": "Acme on LinkedIn: Hiring a Data Intern",
                "body": "Apply with your resume at careers@acme.example.",
            },
            {
                "href": "https://www.linkedin.com/posts/person_my-internship-activity-2",
                "title": "Person on LinkedIn: My internship experience",
                "body": "I am grateful for everything I learned.",
            },
        ]

        rows = linkedin_posts.scrape(["test query"], max_per_query=2)

        self.assertEqual([row["company"] for row in rows], ["Acme"])


class CuratedPickTests(unittest.TestCase):
    def test_file_picks_sync_as_manual_listings(self):
        expected_urls = {
            "https://lnkd.in/p/dMX7MJnT",
            "https://lnkd.in/p/dMXzzXz5",
            "https://lnkd.in/p/dCcT6gh3",
        }
        self.assertEqual({pick["url"] for pick in picks.load()}, expected_urls)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(db.SCHEMA)
            picks.sync_db(conn)
            rows = conn.execute(
                "SELECT source, url, title FROM internships ORDER BY url"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual({row["url"] for row in rows}, expected_urls)
        self.assertTrue(all(row["source"] == "manual" for row in rows))
        self.assertTrue(all(row["title"].strip() for row in rows))


if __name__ == "__main__":
    unittest.main()
