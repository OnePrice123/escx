# brink.watch — an escalation barometer for state pairs

**[brink.watch](https://brink.watch)** shows, for two dozen pairs of states, what
escalation phase they are in, how hot it is right now, which way it is moving —
and **what exactly each number is made of**.

Everything is computed from open sources following a
[published methodology](docs/01-methodology.md). Any value opens down to the
source event, with a link to the publication it came from.

*The documentation in `docs/` is written in Russian; this README and
[`llms.txt`](llms.txt) are the English entry points.*

---

## What makes this different from other conflict trackers

There are several. Most either have a language model retell the news, or dump raw
signals onto a map. The difference is one thing:

**We publish the record of our own errors.**

The site carries a backtest over nineteen conflicts that have since escalated: the
index caught **16 of 19**, a median of 21 months ahead — and **two alarms in three
were false**, precision 32%. That is an uncomfortable number, and it is on the site
rather than in a drawer.

Three more properties from the same family:

- **You can see what we don't know.** Every pair shows its data coverage, and an
  unmeasured block is marked unmeasured rather than replaced with a zero.
- **History cannot be rewritten.** Raw events, the phase journal and published
  forecasts are protected by database triggers: insert only.
- **Every number opens down to an event.** The pair page carries a table of raw
  source records with links to the articles.

Copying this is hard for a non-technical reason. Copying it means publishing your
own error rate.

---

## Under the hood

| | |
|---|---|
| Sources | UCDP GED and Candidate, GDELT, OFAC SDN, UN General Assembly votes, ADS-B |
| Cross-check | the independent GPR index (Caldara & Iacoviello) — not a term in the formula, a second pair of eyes |
| Computation | Python, standard library, **zero dependencies** |
| Front end | static files, no bundler and no framework |
| Accounts and subscriptions | Cloudflare Worker + D1 |
| Running cost | **$0/month** on free tiers |
| Tests | 437 offline checks (271 pipeline + 166 API), no network needed |

The showcase data is open and machine-readable:
[`data/index.json`](https://brink.watch/data/index.json) plus one file per pair, for
example [`data/RUS-UKR.json`](https://brink.watch/data/RUS-UKR.json).

---

## Quick start

```bash
# 1. tests for the data pipeline — no network required
python3 ingest/tests/test_offline.py
python3 ingest/tests/test_compute_offline.py
python3 ingest/tests/test_llm_offline.py
node api/test/test.mjs

# 2. design language and prototypes — just open them in a browser
open design/styleguide.html     # design showcase, three tints
open brand/logo.html            # the mark: variants, sizes, contexts
open design/demo.html           # minimal example: tokens.css + escx-ui.js
open web/schema.html            # the whole system on one page

# 3. build and view the site
python3 web/build.py                    # real data, or an honest empty state
python3 web/build.py --demo             # invented numbers, LAYOUT WORK ONLY
python3 -m http.server -d site 8000     # http://localhost:8000

# 4. collect the first data
cd ingest
python3 -m escx.cli init
python3 -m escx.cli backfill-ucdp --start 2024-01-01 --end 2024-12-31
python3 -m escx.cli pull-weights
python3 -m escx.cli compute
python3 -m escx.cli status
```

No dependencies — Python 3.11+ standard library only.

---

## Layout

| Folder | Contents |
|---|---|
| `docs/` | Eight documents, in Russian. Read them in numerical order |
| `design/` | `tokens.css` and `escx-ui.js` — the design language as code; `styleguide.html` is the showcase |
| `brand/` | Mark, logo, icons. `logo.html` is the showcase, `README.md` the rules |
| `web/` | `build.py` builds the static site, `templates/` holds the shell |
| `ingest/` | The pipeline: UCDP, GDELT, sanctions, UN votes, ADS-B, GPR |
| `api/` | Cloudflare Worker: sign-in by email and password, subscriptions, access checks |
| `.github/` | Hourly and daily runs, tests on push |

The documents cover methodology, business plan, technical plan, data collection,
where AI helps and where it does harm, deployment, billing and mail.

---

## The «Warmth» design language

Structure is held by light, not by lines. Data is not coloured in — the surface
warms up.

```html
<html data-tint="sand">          <!-- sand | ash | clay -->
<link rel="stylesheet" href="design/tokens.css">
<script src="design/escx-ui.js"></script>
```

```js
gaugeEl.innerHTML = ESCX.lightArc(64, { id: 'global' });
rowEl.style.setProperty('--heat', ESCX.heatWash(79));
sparkEl.innerHTML  = ESCX.sparkWash(series);
```

A plain `<script>` rather than an ES module, deliberately: modules fail over
`file://` because of CORS, and every page here must open on a double click, with no
server and no build step. Check it: open `design/demo.html`.

---

## Deployment

The site is static: the pipeline computes everything ahead of time, `web/build.py`
writes the showcase out as JSON, the host serves a folder. No server, no database —
nothing to pay for.

**Cloudflare Pages** is the recommended host: the only free tier that does not
forbid commercial use. GitHub Pages and Vercel Hobby prohibit running a business on
them in their terms.

Step by step — `docs/06-deploy.md`.

---

## Status

The site is live: **[brink.watch](https://brink.watch/)**, rebuilt nightly.

Twenty active pairs plus completed conflicts, kinetic data through the first half of
2026, three years of media history, calibration published. The military block is
still filling up: ADS-B needs a week of hourly snapshots per zone, and coverage of
the zones that matter is limited by where volunteer receivers are.

What is measured and what is not is visible on every pair page, deliberately.

Context for Claude Code lives in `CLAUDE.md` (Russian).

---

## Sources and licences

Open data: [UCDP](https://ucdp.uu.se/), [GDELT](https://www.gdeltproject.org/),
[GPR Index](https://www.matteoiacoviello.com/gpr.htm) (free to use with attribution
to the authors, the paper and the website), [SIPRI](https://www.sipri.org/), public
sanctions registers, [UN General Assembly votes](https://digitallibrary.un.org/collection/Voting%20Data),
[adsb.lol](https://adsb.lol/). Forecast benchmark — [VIEWS](https://viewsforecasting.org/)
(Uppsala/PRIO).

[ACLED](https://acleddata.com/contentusage) is **not used**: their terms forbid
projects of this kind. See `CLAUDE.md`, invariant 4.
