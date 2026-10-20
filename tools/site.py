"""The competition's static site: the boards and the head-to-head table on
the index, a page per bot with its games and how to replay each, and the
data files. No script: plain HTML and a stylesheet.

    python3 -m tools.site --standings FILE --games FILE --out DIR
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from html import escape
from pathlib import Path

from tools.common import read_games

REPOSITORY = "https://github.com/ef3d0c3e/dedale-submissions"
DEDALE = "https://github.com/ef3d0c3e/dedale"

STYLE = """\
:root { color-scheme: light dark; --bg: #f7f7f5; --fg: #1d1d22; --muted: #6b6b76;
  --line: #dcdce2; --accent: #3b5bdb; --win: #2b8a3e; --loss: #c92a2a; --panel: #fff; }
@media (prefers-color-scheme: dark) { :root { --bg: #17171b; --fg: #e6e6ea; --muted: #9a9aa6;
  --line: #34343d; --accent: #7c95ff; --win: #69db7c; --loss: #ff8787; --panel: #1f1f25; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 72rem; margin: 0 auto; padding: 1rem; }
a { color: var(--accent); }
h1 { margin: 0.5rem 0; font-size: 1.5rem; }
h2 { margin: 1.6rem 0 0.4rem; font-size: 1.15rem; }
.muted { color: var(--muted); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { padding: 0.25rem 0.6rem; border-bottom: 1px solid var(--line); text-align: left;
  white-space: nowrap; }
th { color: var(--muted); font-weight: 500; }
td.num { text-align: right; }
.tag { font-size: 0.75rem; padding: 0 0.4em; border: 1px solid var(--line); border-radius: 999px;
  color: var(--muted); }
.h2h td { text-align: center; padding: 0.2rem 0.35rem; }
.h2h td a { color: inherit; text-decoration: none; }
.w3 { background: color-mix(in srgb, var(--win) 45%, transparent); }
.w2 { background: color-mix(in srgb, var(--win) 28%, transparent); }
.w1 { background: color-mix(in srgb, var(--win) 12%, transparent); }
.l1 { background: color-mix(in srgb, var(--loss) 12%, transparent); }
.l2 { background: color-mix(in srgb, var(--loss) 28%, transparent); }
.l3 { background: color-mix(in srgb, var(--loss) 45%, transparent); }
pre { margin: 0.2rem 0 0.6rem; padding: 0.4rem 0.6rem; overflow-x: auto; background: var(--panel);
  border: 1px solid var(--line); border-radius: 4px; font-size: 0.8rem; }
.description { max-width: 60ch; }
"""


def page(title: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape(title)}</title>\n<link rel=\"stylesheet\" href=\"{up}style.css\">\n"
        f"</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def label(bot: dict) -> str:
    """`Name v3`, or the id when the bot gives no name."""
    name = bot.get("name") or bot["id"]
    return f"{name} v{bot['version']}" if bot.get("version") is not None else name


def bot_link(bot: dict, depth: int = 0) -> str:
    tag = f" {BASELINE_TAG}" if bot.get("baseline") else ""
    return f'<a href="{"../" * depth}bots/{escape(bot["id"])}.html">{escape(label(bot))}</a>{tag}'


def count(n: int, noun: str) -> str:
    """`1 maze`, `10 mazes`."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def percent(share: float | None) -> str:
    return "–" if share is None else f"{share * 100:.1f}%"


NOT_PLAYED = '<li class="muted">Not played yet.</li>'
BASELINE_TAG = '<span class="tag">baseline</span>'


def shade(share: float) -> str:
    """A colour class for a share: green above even, red below."""
    gap = round(share - 0.5, 6)
    step = 3 if abs(gap) >= 0.15 else 2 if abs(gap) >= 0.05 else 1 if gap else 0
    return "" if step == 0 else f"{'w' if gap > 0 else 'l'}{step}"


def replay_command(game: dict) -> str:
    """How to play a game again, from a clone of the repository."""
    spec = game["spec"]
    files = " ".join(f"bots/{key.split('@')[0]}/main.py" for key in spec["bots"])
    swap = " --swap" if spec.get("swapped") else ""
    return (
        f"git checkout {game['commit']}\n"
        f"dedale run {files} --maze {game['code']}{swap} "
        f"--startup-ms {game['startup_ms']} --move-ms {game['move_ms']}"
    )


def index(standings: dict) -> str:
    bots = {bot["id"]: bot for bot in standings["bots"]}
    duo_rows = []
    for row in standings["duo"]:
        bot = bots[row["id"]]
        note = ' <span class="tag">provisional</span>' if row["provisional"] else ""
        duo_rows.append(
            f'<tr><td class="num">{row["rank"]}</td><td>{bot_link(bot)}{note}</td>'
            f"<td>{escape(bot.get('author') or '–')}</td>"
            f'<td class="num">{row["won"]}–{row["drawn"]}–{row["lost"]}</td>'
            f'<td class="num">{percent(row["share"])}</td><td class="num">{row["failures"]}</td></tr>'
        )
    head = standings["head_to_head"]
    ids = head["ids"]
    cells = []
    for i, a in enumerate(ids):
        tds = []
        for j, b in enumerate(ids):
            share = head["shares"][i][j]
            if a == b:
                tds.append('<td class="muted">·</td>')
            elif share is None:
                tds.append('<td class="muted">–</td>')
            else:
                href = f"bots/{escape(a)}.html#vs-{escape(b.replace('/', '-'))}"
                tds.append(
                    f'<td class="{shade(share)}" title="{escape(label(bots[a]))} against '
                    f'{escape(label(bots[b]))}"><a href="{href}">{share * 100:.0f}</a></td>'
                )
        cells.append(f'<tr><th>{i + 1}. {escape(label(bots[a]))}</th>{"".join(tds)}</tr>')
    columns = "".join(f'<th title="{escape(label(bots[b]))}">{j + 1}</th>' for j, b in enumerate(ids))
    solo_rows = []
    for row in standings["solo"]:
        ratio = "–" if row["ratio"] is None else f"{row['ratio']:.3f}"
        note = ' <span class="tag">provisional</span>' if row["provisional"] else ""
        solo_rows.append(
            f'<tr><td class="num">{row["rank"]}</td><td>{bot_link(bots[row["id"]])}{note}</td>'
            f'<td class="num">{ratio}</td><td class="num">{row["cleared"]}/{row["mazes"]}</td></tr>'
        )
    commit = standings["commit"]
    settings = standings["settings"]
    mazes, solo_mazes = settings["mazes_per_pairing"], settings["solo_mazes"]
    width, height = settings["size"].split("x")
    body = f"""<h1>Dedale competition</h1>
<p class="muted">Season {escape(standings['season'])}, <a href="{DEDALE}">Dedale</a>
{escape(standings['dedale'])}. Updated {escape(standings['generated'])} at
<a href="{REPOSITORY}/commit/{escape(commit)}">{escape(commit[:12])}</a>.
<a href="{REPOSITORY}">Submit a bot</a>.</p>
<p class="muted">{width}×{height} mazes with {settings['points']} points and
{settings['loops']}% loops; {settings['startup_ms'] / 1000:g} s to start, {settings['move_ms']} ms per move.</p>

<h2>Head to head</h2>
<p class="muted">Each pair of bots plays {2 * mazes} games, {count(mazes, "fresh maze")} from both corners. A
pairing's score is a bot's share of the points; bots are ranked with the Schulze method:
one ranks above another when it beats it, directly or through a chain of bots each beating
the next, by a wider margin than the other manages back.</p>
<div class="scroll"><table>
<tr><th>#</th><th>Bot</th><th>Author</th><th>Pairings won–drawn–lost</th><th>Average share</th>
<th>Games with failures</th></tr>
{''.join(duo_rows)}
</table></div>

<h2>Pairings</h2>
<p class="muted">The row bot's share of the points against the column bot, in percent.</p>
<div class="scroll"><table class="h2h"><tr><th></th>{columns}</tr>
{''.join(cells)}
</table></div>

<h2>Solo</h2>
<p class="muted">Each bot clears {count(solo_mazes, "maze")} alone: its turns divided by the greedy baseline's
on the same mazes (lower is better; a maze not cleared counts the turn limit).</p>
<div class="scroll"><table>
<tr><th>#</th><th>Bot</th><th>Turns, relative to greedy</th><th>Cleared</th></tr>
{''.join(solo_rows)}
</table></div>

<h2>Data</h2>
<p>Every game: <a href="games.json.gz">games.json.gz</a>. These standings:
<a href="standings.json">standings.json</a>.</p>"""
    return page("Dedale competition", body)


def bot_page(bot: dict, standings: dict, games: dict[str, dict]) -> str:
    bots = {b["id"]: b for b in standings["bots"]}
    head = standings["head_to_head"]
    rows = []
    if bot["id"] in head["ids"]:
        i = head["ids"].index(bot["id"])
        for j, other in enumerate(head["ids"]):
            if other == bot["id"]:
                continue
            share = head["shares"][i][j]
            anchor = escape(other.replace("/", "-"))
            listed = []
            for game_id in head["games"][i][j]:
                game = games.get(game_id)
                if game is None:
                    continue
                seat = [k.split("@")[0] for k in game["spec"]["bots"]].index(bot["id"])
                points = game["result"]["half_points"]
                mine, theirs = points[seat] / 2, points[1 - seat] / 2
                corner = "bottom-right" if (seat == 0) == bool(game["spec"]["swapped"]) else "top-left"
                listed.append(
                    f"<li>{mine:g} to {theirs:g}, from the {corner} corner, "
                    f"{escape(game['result']['reason'].replace('_', ' '))} after "
                    f"{game['result']['turns']} turns<pre>{escape(replay_command(game))}</pre></li>"
                )
            rows.append(
                f'<h3 id="vs-{anchor}">Against {bot_link(bots[other], 2)}: {percent(share)}</h3>'
                f"<ul>{''.join(listed) or NOT_PLAYED}</ul>"
            )
    solo = [g for g in games.values() if g["spec"]["kind"] == "solo"
            and g["spec"]["bots"][0] == f"{bot['id']}@{bot['version']}"
            and g["spec"]["mazes_of"] == f"{bot['id']}@{bot['version']}"]
    solo_items = "".join(
        f"<li>{escape(g['result']['reason'].replace('_', ' '))} after {g['result']['turns']} turns"
        f"<pre>{escape(replay_command(g))}</pre></li>"
        for g in sorted(solo, key=lambda g: g["spec"]["maze"])
    )
    description = escape(bot.get("description") or "")
    baseline = f"· {BASELINE_TAG}" if bot.get("baseline") else ""
    body = f"""<p><a href="../../index.html">← Standings</a></p>
<h1>{escape(label(bot))}</h1>
<p>by {escape(bot.get('author') or '–')} · <code>{escape(bot['id'])}</code>
{baseline} ·
<a href="{REPOSITORY}/tree/master/bots/{escape(bot['id'])}">source</a></p>
<p class="description">{description}</p>
<h2>Head to head</h2>
{''.join(rows) or '<p class="muted">No pairing yet.</p>'}
<h2>Solo</h2>
<ul>{solo_items or NOT_PLAYED}</ul>"""
    return page(label(bot), body, 2)


def build(standings: dict, games: list[dict], out: Path, games_file: Path | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "style.css").write_text(STYLE)
    (out / "index.html").write_text(index(standings))
    (out / "standings.json").write_text(json.dumps(standings, indent=1))
    by_id = {game["id"]: game for game in games}
    for bot in standings["bots"]:
        path = out / "bots" / f"{bot['id']}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bot_page(bot, standings, by_id))
    if games_file is not None and games_file.exists():
        shutil.copy(games_file, out / "games.json.gz")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--standings", required=True)
    parser.add_argument("--games", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    standings = json.loads(Path(args.standings).read_text())
    games_file = Path(args.games)
    build(standings, read_games(games_file), Path(args.out), games_file)
    print(f"site written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
