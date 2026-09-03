#!/usr/bin/env python3
"""Tests for the checker. Run: python3 test_agent_readable.py

Every case here is a shape this tool got WRONG at some point during its first
hour, or a shape that would silently produce a confident false answer. That is
the only kind of test worth writing for a tool whose failure mode is looking
correct.
"""
import unittest

import agent_readable as ar

CRAWLERS = ar.load_crawlers()


def check_text(text, content_type="text/plain", path="/"):
    """Run the verdict logic over a literal robots.txt, with no network."""
    genuine, why = ar.looks_like_robots(text, content_type)
    if not genuine:
        return {"verdict": "undecided", "reason": why}
    groups = ar.parse_robots(text)
    out = {"blocked_retrieval": [], "blocked_training": []}
    for kind in ("retrieval", "training"):
        for agent in CRAWLERS[kind]["agents"]:
            if not ar.decide(groups, agent, path)[0]:
                out["blocked_" + kind].append(agent)
    out["blocks_everything"] = not ar.decide(groups, "nobody-names-this", path)[0]
    if out["blocks_everything"] or out["blocked_retrieval"]:
        out["verdict"] = "not-readable"
    else:
        out["verdict"] = "readable"
    return out


class ParsingTest(unittest.TestCase):
    def test_consecutive_user_agent_lines_share_the_following_rules(self):
        """The defect naive parsers have: a group headed by three agents applies
        to all three, and attributing the rules to only the last silently clears
        the other two."""
        groups = ar.parse_robots(
            "User-agent: GPTBot\nUser-agent: CCBot\nUser-agent: ClaudeBot\nDisallow: /\n")
        for agent in ("gptbot", "ccbot", "claudebot"):
            self.assertEqual([("disallow", "/")], groups[agent], agent)

    def test_a_new_group_starts_a_fresh_agent_list(self):
        groups = ar.parse_robots(
            "User-agent: GPTBot\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n")
        self.assertEqual([("disallow", "/")], groups["gptbot"])
        self.assertEqual([("allow", "/")], groups["googlebot"])

    def test_prefix_matching_per_rfc_9309(self):
        """`User-agent: Yandex` governs YandexBot."""
        groups = ar.parse_robots("User-agent: Yandex\nDisallow: /\n")
        allowed, group, _ = ar.decide(groups, "YandexBot", "/")
        self.assertFalse(allowed)
        self.assertEqual("yandex", group)

    def test_the_most_specific_prefix_wins(self):
        groups = ar.parse_robots(
            "User-agent: Googlebot\nDisallow: /\n\nUser-agent: Googlebot-News\nAllow: /\n")
        self.assertTrue(ar.decide(groups, "Googlebot-News", "/")[0])
        self.assertFalse(ar.decide(groups, "Googlebot", "/")[0])

    def test_empty_disallow_means_allow_everything(self):
        groups = ar.parse_robots("User-agent: *\nDisallow:\n")
        self.assertTrue(ar.decide(groups, "GPTBot", "/")[0])

    def test_longest_match_wins_and_allow_breaks_a_tie(self):
        groups = ar.parse_robots("User-agent: *\nDisallow: /\nAllow: /blog/\n")
        self.assertFalse(ar.decide(groups, "GPTBot", "/")[0])
        self.assertTrue(ar.decide(groups, "GPTBot", "/blog/post")[0])

    def test_wildcards_and_end_anchors(self):
        groups = ar.parse_robots("User-agent: *\nDisallow: /*.pdf$\n")
        self.assertFalse(ar.decide(groups, "GPTBot", "/files/report.pdf")[0])
        self.assertTrue(ar.decide(groups, "GPTBot", "/files/report.pdf.html")[0])

    def test_comments_are_stripped(self):
        groups = ar.parse_robots("User-agent: GPTBot # our policy\nDisallow: / # everything\n")
        self.assertFalse(ar.decide(groups, "GPTBot", "/")[0])


class GuardTest(unittest.TestCase):
    """A 200 that is not robots.txt must never read as a clean bill of health."""

    def test_an_html_challenge_page_is_undecided_not_readable(self):
        """MEASURED, NOT IMAGINED. linkedin.com/robots.txt answers HTTP 200 with
        a Google reCAPTCHA challenge page. Before this guard the parser found
        zero groups, every crawler fell through to 'no group applies', and the
        tool reported LinkedIn — which carries Disallow: / for every agent it
        does not name — as READABLE with nothing refused."""
        html = ('<!doctype html><html lang="en-US"><head><base '
                'href="https://www.google.com/recaptcha/challengepage/">')
        self.assertEqual("undecided", check_text(html, "text/html; charset=utf-8")["verdict"])
        self.assertEqual("undecided", check_text(html, "text/plain")["verdict"])

    def test_an_empty_robots_is_readable_not_undecided(self):
        """Distinct from the above and must not be swept in with it: an empty or
        comment-only file is valid and means no rules at all."""
        self.assertEqual("readable", check_text("")["verdict"])
        self.assertEqual("readable", check_text("# nothing to declare\n")["verdict"])

    def test_prose_with_no_directives_is_undecided(self):
        self.assertEqual("undecided", check_text("Sorry, this page has moved elsewhere")["verdict"])


class VerdictTest(unittest.TestCase):
    def test_training_only_blocks_are_not_a_defect(self):
        """The 19x overstatement this tool exists to prevent."""
        result = check_text(
            "User-agent: GPTBot\nUser-agent: CCBot\nUser-agent: Google-Extended\nDisallow: /\n")
        self.assertEqual("readable", result["verdict"])
        self.assertEqual([], result["blocked_retrieval"])
        self.assertEqual(3, len(result["blocked_training"]))

    def test_one_retrieval_block_flips_the_verdict(self):
        result = check_text("User-agent: ChatGPT-User\nDisallow: /\n")
        self.assertEqual("not-readable", result["verdict"])
        self.assertEqual(["ChatGPT-User"], result["blocked_retrieval"])

    def test_a_blanket_refusal_is_caught_even_though_no_ai_agent_is_named(self):
        result = check_text("User-agent: *\nDisallow: /\n")
        self.assertEqual("not-readable", result["verdict"])
        self.assertTrue(result["blocks_everything"])

    def test_google_extended_alone_is_explicitly_fine(self):
        """The single most misread token in robots.txt: Gemini training only,
        no effect whatsoever on Google Search."""
        result = check_text("User-agent: Google-Extended\nDisallow: /\n")
        self.assertEqual("readable", result["verdict"])

    def test_applebot_extended_alone_is_fine_but_plain_applebot_is_not(self):
        self.assertEqual("readable",
                         check_text("User-agent: Applebot-Extended\nDisallow: /\n")["verdict"])
        self.assertEqual("not-readable",
                         check_text("User-agent: Applebot\nDisallow: /\n")["verdict"])

    def test_a_site_can_refuse_the_root_and_permit_the_pages_that_matter(self):
        robots = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /\nAllow: /posts/\n"
        self.assertEqual("not-readable", check_text(robots, path="/")["verdict"])
        self.assertTrue(ar.decide(ar.parse_robots(robots), "Googlebot", "/posts/x")[0])


class VocabularyTest(unittest.TestCase):
    def test_no_agent_is_in_two_buckets(self):
        seen = {}
        for kind in ("training", "retrieval", "unclassified"):
            for agent in CRAWLERS[kind]["agents"]:
                self.assertNotIn(agent, seen,
                                 "%s is in both %s and %s" % (agent, seen.get(agent), kind))
                seen[agent] = kind

    def test_every_agent_carries_an_explanation(self):
        for kind in ("training", "retrieval", "unclassified"):
            for agent, why in CRAWLERS[kind]["agents"].items():
                self.assertTrue(why.strip(), "%s has no explanation" % agent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
