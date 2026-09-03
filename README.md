# agent-readable-check

**Is your site actually unreadable to AI assistants, or have you just opted out of model training?**

Those are different questions. Almost every "is my site blocking AI?" checker answers the wrong one, and the wrong answer is alarming in a way the right one isn't.

```
python3 agent_readable.py yourdomain.com
```

No dependencies, no signup, no data leaves your machine. It fetches one file — your `/robots.txt` — and tells you what it actually says.

---

## The distinction

There are two kinds of bot with "AI" in the description, and they do opposite jobs.

**Training crawlers** — `GPTBot`, `CCBot`, `ClaudeBot`, `Google-Extended`, `Applebot-Extended`, `Bytespider` — collect pages to train a model. Refusing them says *"do not train on me."* That is deliberate, common, entirely reasonable, and **it does not remove you from ChatGPT's answers.**

**Retrieval crawlers** — `ChatGPT-User`, `OAI-SearchBot`, `Claude-User`, `Claude-SearchBot`, `PerplexityBot`, `Googlebot`, `Bingbot`, `Applebot`, `DuckDuckBot` — fetch or index a page so an assistant can *read and cite it at the moment somebody asks a question*. Refuse those and you genuinely cannot be recommended.

Two that nearly everyone gets backwards:

- **`Google-Extended` governs Gemini training only.** It has no effect on Google Search ranking or inclusion. Blocking it does not hurt you.
- **`Applebot-Extended` is the Apple Intelligence training opt-out.** Plain `Applebot` still crawls for Siri and Spotlight, so blocking `Applebot-Extended` does not remove you from Apple's answers.

## Why it matters: a 19x overstatement, measured

We scanned 6,284 businesses and found 212 whose `robots.txt` blocked something AI-related. Read as one number, that is *"212 businesses are invisible to AI."* On 2026-09-03 we re-fetched all 212 files and read them properly:

| count | what it really is |
| ---: | --- |
| 212 | blocked something AI-related |
| **194** | block **training** crawlers only — not a defect. Nothing is wrong. |
| 14 | block a **retrieval** crawler |
| −3 | are `instagram.com`, `yelp.com`, `vagaro.com` — businesses with no site of their own, recorded under the platform they use. That `robots.txt` is the platform's policy and was never theirs to change. |
| **11** | real businesses with the real problem |

11, not 212. And the people best equipped to notice the error are exactly the technical buyers you would be saying it to.

## What it tells you

Three verdicts, and the third one is the point.

- **READABLE** — no retrieval crawler is refused. If you block training crawlers it says so, and says explicitly that this is fine.
- **NOT READABLE** — at least one retrieval crawler is refused, or a blanket `Disallow: /` covers everything not specifically named. It names which, and what each one does.
- **UNDECIDED** — it could not read your policy. This is a real answer and it is never dressed up as a pass.

That last one exists because of a false clean bill of health this tool produced in its first hour of life. `linkedin.com/robots.txt` answers **HTTP 200 with a Google reCAPTCHA challenge page** — 21KB of HTML and not one directive. The parser found no rules, every crawler fell through to "no rules apply, so it's permitted", and the tool cheerfully reported LinkedIn as READABLE with nothing refused. LinkedIn in fact carries `Disallow: /` for every agent it does not name.

A checker that is silently confident is worse than no checker, because the output is indistinguishable from a real answer. Anything that isn't recognisably `robots.txt` now returns UNDECIDED and says why. It also retries the `www.` host once, which is what resolves the LinkedIn case honestly.

## Details it gets right

- **Grouped user-agents.** Three consecutive `User-agent:` lines share the rules that follow. Attributing them to only the last one silently clears the other two.
- **Prefix matching, per [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html).** `User-agent: Yandex` governs `YandexBot`; the most specific matching group wins.
- **Longest-match precedence with `Allow` breaking ties**, the same rule Google's parser uses, plus `*` wildcards and `$` anchors.
- **`Disallow:` with an empty value means allow everything** — the opposite of `Disallow: /`, one character apart.
- **Per-path verdicts.** `--path /blog/` — a site can refuse the root and permit the pages that matter, or the reverse. LinkedIn does exactly this: `/` is refused for almost everyone, while seven named crawlers are permitted on `/posts/`.
- **Agents it will not classify** are reported as undecided rather than counted either way. The list is in [`crawlers.json`](crawlers.json), with a one-line justification for every entry.

## Examples

```console
$ python3 agent_readable.py nytimes.com
  NOT READABLE by assistants
  6 retrieval crawler(s) are refused.
    ChatGPT-User    OAI-SearchBot    Claude-User
    Claude-SearchBot    PerplexityBot    Perplexity-User

$ python3 agent_readable.py linkedin.com
  (linkedin.com did not serve robots.txt — it returned an HTML page; this is www.linkedin.com.)
  NOT READABLE by assistants
  robots.txt refuses every agent that is not specifically named.

$ python3 agent_readable.py --json example.com     # machine-readable
$ python3 test_agent_readable.py                   # 19 tests, no network
```

Exit status is `0` unless some domain came back NOT READABLE, so it drops into CI.

## Fixing a real block

If a retrieval crawler is refused and you did not mean it, remove that group from `robots.txt`. If you want to keep the training opt-out and stay citable, that is a coherent position and it looks like this:

```
User-agent: GPTBot
User-agent: CCBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
Disallow: /

User-agent: *
Disallow:
```

Being in the answer is a separate problem from being allowed in it. `robots.txt` decides whether an assistant *may* read you; whether it finds anything worth saying depends on what you have actually published.

## Who made this

Built by [River Cade Concepts](https://rivercadeconcepts.com/?utm_source=github&utm_medium=organic_repo&utm_campaign=rcc_growth_engine&utm_content=agent_readable_check_v1), from the crawler-classification work behind our study of 6,284 businesses. We do [agent-readiness diagnostics](https://rivercadeconcepts.com/services/agent-presence?utm_source=github&utm_medium=organic_repo&utm_campaign=rcc_growth_engine&utm_content=agent_readable_check_v1) — what assistants say about a business, and the public evidence behind it.

Corrections welcome, particularly on the crawler classifications. If a vendor's documentation says something different from `crawlers.json`, open an issue with the link and we will fix it — an agent in the wrong bucket is the one bug that makes this tool worse than nothing.

MIT licensed.
