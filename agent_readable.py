#!/usr/bin/env python3
"""Can an AI assistant actually read your site, or have you only opted out of training?

Those are different questions and almost every "is my site blocking AI?" check
answers the wrong one. This answers the right one.

    python3 agent_readable.py example.com

No dependencies. Nothing is sent anywhere. It fetches one file — your
/robots.txt — and tells you what it says.

WHY THE DISTINCTION IS THE WHOLE POINT

There are two kinds of bot with "AI" in the description:

  TRAINING crawlers (GPTBot, CCBot, ClaudeBot, Google-Extended, ...) collect
  pages to train a model. Refusing them says "do not train on me". That is
  deliberate, common, entirely reasonable, and it does NOT remove you from
  ChatGPT's answers.

  RETRIEVAL crawlers (ChatGPT-User, OAI-SearchBot, Claude-User, PerplexityBot,
  Googlebot, ...) fetch or index a page so an assistant can read and cite it at
  the moment somebody asks a question. Refuse those and you genuinely cannot be
  recommended.

Two that nearly everyone gets backwards:

  Google-Extended governs Gemini TRAINING only. It has no effect on Google
  Search, and blocking it does not hurt your ranking.

  Applebot-Extended is the Apple Intelligence training opt-out. Plain Applebot
  still crawls for Siri and Spotlight, so blocking Applebot-Extended does not
  remove you from Apple's answers.

WHAT HAPPENS WHEN YOU CONFLATE THEM

We measured it. River Cade Concepts scanned 6,284 businesses and found 212
whose robots.txt blocked something AI-related. Read as one number, that is
"212 businesses are invisible to AI". Read correctly, on 2026-09-03, by
re-fetching all 212 robots.txt files:

    212  blocked something AI-related
    194  block TRAINING crawlers only        <- not a defect. Nothing is wrong.
     14  block a RETRIEVAL crawler
     -3  are instagram.com, yelp.com and vagaro.com — businesses with no site
         of their own, recorded under the platform they use. That robots.txt is
         the platform's policy and was never theirs to change.
     11  real businesses with the real problem

So the honest number is 11, not 212 — a 19x overstatement, and the people best
equipped to notice are exactly the technical buyers you would be saying it to.

This tool will not make that mistake on your behalf, and it will tell you when
it cannot decide something rather than guessing.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "agent-readable-check (+https://github.com/Mikeshaner78/agent-readable-check)"


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return (resp.status, resp.read().decode(charset, "replace"),
                    (resp.headers.get("Content-Type") or "").lower())
    except urllib.error.HTTPError as exc:
        return exc.code, "", ""
    except Exception as exc:  # noqa: BLE001 - unreachable is an answer
        return None, str(exc), ""


def looks_like_robots(text, content_type=""):
    """Did the server actually serve robots.txt, or a 200 that merely looks like one?

    THIS CHECK IS NOT PARANOIA; IT CAUGHT A FALSE CLEAN BILL OF HEALTH ON THE
    FIRST REAL RUN. linkedin.com/robots.txt answers HTTP 200 with a Google
    reCAPTCHA challenge page — 21KB of HTML, no directives. Without this, the
    parser found zero groups, every crawler fell through to "no group applies,
    robots.txt grants by default", and the tool reported LinkedIn as READABLE
    with nothing refused. LinkedIn in fact carries `Disallow: /` for every agent
    it does not name.

    Silently confident is the worst failure mode a checker has, because the
    output is indistinguishable from a real answer. Anything that is not
    recognisably robots.txt is UNDECIDED.

    An empty or comment-only robots.txt is a different thing and is valid: it
    means no rules, so everything is permitted. That must not be swept in here.
    """
    stripped = text.strip()
    if not stripped:
        return True, ""
    if "html" in content_type or "xml" in content_type:
        return False, ("the server answered with Content-Type %r, which is not robots.txt"
                       % content_type)
    head = stripped[:600].lower()
    for marker in ("<!doctype", "<html", "<head", "<body", "<script"):
        if marker in head:
            return False, ("the server answered 200 but returned an HTML page rather than "
                           "robots.txt — commonly a bot challenge, a login wall or a "
                           "catch-all route")
    meaningful = [line for line in stripped.splitlines()
                  if line.split("#", 1)[0].strip()]
    if meaningful and not any(":" in line.split("#", 1)[0] for line in meaningful):
        return False, "the response contains no robots.txt directives at all"
    return True, ""


def parse_robots(text):
    """robots.txt -> {lowercased agent: [(directive, value), ...]}.

    Consecutive User-agent lines share the rules that follow them, which is the
    part naive parsers get wrong: a group headed by three agents applies to all
    three, and attributing the rules to only the last one silently clears the
    other two.
    """
    groups = {}
    current = []
    starting_group = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if not starting_group:
                current = []
                starting_group = True
            current.append(value.lower())
            groups.setdefault(value.lower(), [])
        elif field in ("allow", "disallow"):
            starting_group = False
            for agent in current:
                groups.setdefault(agent, []).append((field, value))
        else:
            starting_group = False
    return groups


def _match_len(pattern, path):
    """Longest-match rule from the robots.txt spec, with * and $ support."""
    if pattern == "":
        return -1
    if "*" not in pattern and "$" not in pattern:
        return len(pattern) if path.startswith(pattern) else -1
    import re
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    regex = "^" + regex + ("$" if anchored else "")
    return len(body) if re.match(regex, path) else -1


def decide(groups, agent, path="/"):
    """Is `agent` allowed to fetch `path`? Returns (allowed, which_group, rule)."""
    lowered = agent.lower()
    # PREFIX MATCHING, PER RFC 9309. A group headed `User-agent: Yandex`
    # governs YandexBot, and `Googlebot` governs Googlebot-News. Exact matching
    # alone reports those groups as absent and then falls through to `*`, which
    # can invert the verdict. Most specific (longest) prefix wins.
    if lowered in groups:
        group = lowered
    else:
        candidates = [name for name in groups
                      if name != "*" and lowered.startswith(name)]
        group = max(candidates, key=len) if candidates else ("*" if "*" in groups else None)
    if group is None:
        return True, None, "no group applies; robots.txt grants by default"
    best = (0, "allow", "")          # (specificity, directive, pattern)
    for directive, value in groups.get(group, []):
        if directive == "disallow" and value == "":
            length = 0               # `Disallow:` empty means allow everything
            directive = "allow"
        else:
            length = _match_len(value, path)
            if length < 0:
                continue
        # Ties go to Allow, which is what Google's parser does.
        if length > best[0] or (length == best[0] and directive == "allow"):
            best = (length, directive, value)
    return best[1] == "allow", group, "%s: %s" % (best[1].title(), best[2])


# --------------------------------------------------------------------------
# The reading
# --------------------------------------------------------------------------

def load_crawlers(path=None):
    with open(path or os.path.join(HERE, "crawlers.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def check(domain, crawlers=None, timeout=20, path="/", _retried=False):
    crawlers = crawlers or load_crawlers()
    host = domain.strip().replace("https://", "").replace("http://", "").strip("/")
    result = {"domain": host, "path": path,
              "robots_url": "https://%s/robots.txt" % host}

    status, text, content_type = fetch(result["robots_url"], timeout)
    result["robots_status"] = status
    if status is None:
        result["verdict"] = "undecided"
        result["reason"] = ("Could not fetch robots.txt (%s). This is NOT a finding: an "
                            "unreachable file tells you nothing about the policy." % text[:120])
        return result
    if status == 404:
        result["verdict"] = "readable"
        result["reason"] = ("No robots.txt. Everything is permitted by default, so every "
                            "assistant may read this site.")
        result["blocked_retrieval"] = []
        result["blocked_training"] = []
        return result
    if status != 200:
        result["verdict"] = "undecided"
        result["reason"] = ("robots.txt answered HTTP %s, so the policy cannot be read. "
                            "Note that this is not the same as permitting everything."
                            % status)
        return result

    genuine, why = looks_like_robots(text, content_type)
    if not genuine:
        # TRY www. ONCE BEFORE GIVING UP. The apex frequently answers a bot
        # challenge or a marketing catch-all while the canonical www host serves
        # the real file — which is exactly what linkedin.com does. Retrying is
        # not a workaround: www.linkedin.com IS the canonical host, and reading
        # the apex's challenge page instead is reading the wrong document.
        if not _retried and not host.startswith("www."):
            retry = check("www." + host, crawlers, timeout, path, _retried=True)
            if retry.get("verdict") != "undecided":
                retry["note"] = ("%s did not serve robots.txt (%s); this is www.%s."
                                 % (host, why, host))
                return retry
        result["verdict"] = "undecided"
        result["reason"] = ("The URL answered HTTP 200, but %s. Nothing can be concluded "
                            "about this site's crawler policy, and in particular this is "
                            "NOT evidence that assistants are allowed to read it." % why)
        return result

    groups = parse_robots(text)
    result["declared_agents"] = sorted(a for a in groups if a != "*")

    buckets = {}
    for kind in ("retrieval", "training", "unclassified"):
        blocked = []
        for agent, why in crawlers[kind]["agents"].items():
            allowed, group, rule = decide(groups, agent, path)
            if not allowed:
                blocked.append({"agent": agent, "matched_group": group,
                                "rule": rule, "what_it_does": why})
        buckets[kind] = blocked
    result["blocked_retrieval"] = buckets["retrieval"]
    result["blocked_training"] = buckets["training"]
    result["undecided_agents"] = buckets["unclassified"]

    # A blanket `User-agent: * / Disallow: /` blocks everything, and saying
    # "14 crawlers are blocked" understates that considerably.
    blanket = not decide(groups, "some-crawler-not-named-anywhere", path)[0]
    result["blocks_everything"] = blanket

    if blanket:
        result["verdict"] = "not-readable"
        result["reason"] = ("robots.txt refuses every agent that is not specifically named. "
                            "No assistant and no search engine may read this site.")
    elif buckets["retrieval"]:
        result["verdict"] = "not-readable"
        result["reason"] = ("%d retrieval crawler(s) are refused. These are the ones that "
                            "fetch a page so an assistant can cite it, so this site cannot "
                            "be recommended by them." % len(buckets["retrieval"]))
    elif buckets["training"]:
        result["verdict"] = "readable"
        result["reason"] = ("%d training crawler(s) are refused and no retrieval crawler is. "
                            "That is an opt-out of model training, not invisibility — "
                            "assistants can still read and cite this site. Nothing is wrong "
                            "here." % len(buckets["training"]))
    else:
        result["verdict"] = "readable"
        result["reason"] = "No AI-related crawler is refused."
    return result


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def render(result):
    heading = "%s%s" % (result["domain"], result.get("path", "/"))
    lines = ["", "  %s" % heading, "  " + "-" * max(10, len(heading))]
    if result.get("note"):
        lines.append("  (%s)" % result["note"])
    verdict = result.get("verdict")
    label = {"readable": "READABLE by assistants",
             "not-readable": "NOT READABLE by assistants",
             "undecided": "UNDECIDED"}.get(verdict, verdict)
    lines += ["  %s" % label, "  %s" % result.get("reason", ""), ""]

    if result.get("blocked_retrieval"):
        lines.append("  Retrieval crawlers refused — this is the real problem:")
        for item in result["blocked_retrieval"]:
            lines.append("    %-18s %-24s %s" % (item["agent"], item["rule"],
                                                 item["what_it_does"]))
        lines.append("")
    if result.get("blocked_training"):
        lines.append("  Training crawlers refused — an opt-out, not a defect:")
        for item in result["blocked_training"]:
            lines.append("    %-18s %-24s %s" % (item["agent"], item["rule"],
                                                 item["what_it_does"]))
        lines.append("")
    if result.get("undecided_agents"):
        lines.append("  Refused, but this tool will not say which kind they are:")
        for item in result["undecided_agents"]:
            lines.append("    %-18s %s" % (item["agent"], item["what_it_does"]))
        lines.append("")
    lines.append("  robots.txt: %s (HTTP %s)" % (result["robots_url"],
                                                 result.get("robots_status")))
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Tell whether a site is unreadable to AI assistants, or has "
                    "merely opted out of model training.")
    parser.add_argument("domain", nargs="+", help="one or more domains, e.g. example.com")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--path", default="/",
                        help="the path to judge (default /). Worth using: a site can "
                             "refuse crawlers at the root and permit them on the pages "
                             "that matter, or the reverse.")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    crawlers = load_crawlers()
    results = [check(domain, crawlers, args.timeout, args.path) for domain in args.domain]
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    else:
        for result in results:
            print(render(result))
    return 0 if all(r.get("verdict") != "not-readable" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
