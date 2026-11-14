#!/usr/bin/env python3
"""Pull dynasty trade values from several free sites and write values.json.

Runs daily on GitHub Actions (see .github/workflows/update-values.yml). Uses only the
Python standard library. Each site is optional: if one fails, its previous numbers in
values.json are kept (with their original date), so a bad day never drops a site.

values.json schema (read by index.html):
  {"asOf": "YYYY-MM-DD",
   "sources": [{"id","name","url","method","formats":["sf","1qb"],"asOf","count","note"?}],
   "rows": [[name, pos, {source_id: [superflex_value, one_qb_value]}]]}
Values are raw, on each site's own scale; the page puts them on one scale.
DynastyProcess is read by the page itself, so it only appears in "sources".
"""
import csv, datetime as dt, html, io, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'values.json')
STATS_OUT = os.path.join(HERE, 'stats.json')
HIST_OUT = os.path.join(HERE, 'history.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
TODAY = dt.date.today().isoformat()
POS = {'QB', 'RB', 'WR', 'TE'}
PICK_RE = re.compile(r'^(20\d\d) (Early|Mid|Late) (\d)(st|nd|rd|th)$', re.I)

SOURCES = [
    {'id': 'dp', 'name': 'DynastyProcess', 'url': 'https://github.com/dynastyprocess/data',
     'method': 'FantasyPros expert consensus rankings converted to values', 'formats': ['sf', '1qb']},
    {'id': 'ktc', 'name': 'KeepTradeCut', 'url': 'https://keeptradecut.com/dynasty-rankings',
     'method': 'Crowdsourced keep/trade/cut votes', 'formats': ['sf', '1qb']},
    {'id': 'fc', 'name': 'FantasyCalc', 'url': 'https://www.fantasycalc.com/dynasty-rankings',
     'method': 'Real trades from synced leagues', 'formats': ['sf', '1qb']},
    {'id': 'rw', 'name': 'RotoWire', 'url': None,
     'method': 'Expert trade value chart (monthly)', 'formats': ['sf']},
    {'id': 'fp', 'name': 'FantasyPros Trade Value Chart', 'url': None,
     'method': 'Expert trade value chart (monthly)', 'formats': ['sf', '1qb']},
]


def get(url, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    return data if binary else data.decode('utf-8', 'replace')


def num(x):
    x = re.sub(r'[^\d.\-]', '', str(x or ''))
    try:
        return float(x) if x not in ('', '-', '.') else None
    except ValueError:
        return None


def strip(s):
    return html.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ').strip()


def tables(page):
    """Yield (start_offset, rows) for each <table>, rows as lists of cell text."""
    for m in re.finditer(r'<table.*?</table>', page, re.S | re.I):
        rows = []
        for tr in re.findall(r'<tr.*?</tr>', m.group(0), re.S | re.I):
            cells = [re.sub(r'\s+', ' ', strip(c)) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S | re.I)]
            if cells:
                rows.append(cells)
        yield m.start(), rows


# ---------------------------------------------------------------- KeepTradeCut
def ktc():
    page = get('https://keeptradecut.com/dynasty-rankings?page=0&filters=QB|WR|RB|TE|RDP&format=2')
    m = re.search(r'playersArray\s*=\s*(\[.*?\]);\s*\n', page, re.S)
    if not m:
        raise RuntimeError('playersArray not found')
    out = []
    for p in json.loads(m.group(1)):
        pos = (p.get('position') or '').upper()
        sf = (p.get('superflexValues') or {}).get('value')
        q = (p.get('oneQBValues') or {}).get('value')
        if not p.get('playerName') or (sf is None and q is None):
            continue
        out.append([p['playerName'], 'PICK' if pos in ('RDP', 'PICK') else pos, [sf, q]])
    return out, {'url': 'https://keeptradecut.com/dynasty-rankings'}


# ---------------------------------------------------------------- FantasyCalc
def fc():
    rows = {}
    for f, q in ((0, 2), (1, 1)):
        data = json.loads(get(f'https://api.fantasycalc.com/values/current?isDynasty=true&numQbs={q}&numTeams=12&ppr=1'))
        for x in data:
            p = x.get('player') or {}
            name, val = p.get('name'), x.get('value')
            if not name or val is None:
                continue
            pos = (p.get('position') or '').upper()
            r = rows.setdefault(name, [name, 'PICK' if pos == 'PICK' else pos, [None, None]])
            r[2][f] = val
    if len(rows) < 100:
        raise RuntimeError(f'only {len(rows)} rows')
    return list(rows.values()), {}


# ---------------------------------------------------------------- RotoWire
def rw(prev_url):
    """Newest RotoWire dynasty trade value chart. Article ids increase over time."""
    pat = re.compile(r'(?:https://www\.rotowire\.com)?/football/article/[a-z0-9-]*dynasty-trade-value-chart[a-z0-9-]*-(\d+)')
    found = {}
    if prev_url:
        m = pat.search(prev_url)
        if m:
            found[int(m.group(1))] = prev_url
    for idx in ('https://www.rotowire.com/football/', 'https://www.rotowire.com/football/articles.php',
                'https://www.rotowire.com/football/dynasty.php'):
        try:
            for m in pat.finditer(get(idx)):
                u = m.group(0)
                found[int(m.group(1))] = u if u.startswith('http') else 'https://www.rotowire.com' + u
        except Exception:
            pass
    if not found:
        raise RuntimeError('no article found')
    url = found[max(found)]
    page = get(url)
    out = []
    for _, rows in tables(page):
        for cells in rows:
            val = num(cells[-1]) if cells else None
            if val is None:
                continue
            pick = next((c for c in cells if PICK_RE.match(c)), None)
            if pick:
                out.append([pick, 'PICK', [val, None]])
                continue
            pi = next((k for k, c in enumerate(cells) if c.upper() in POS), None)
            if pi is None:
                continue
            name = next((c for c in cells[:pi] if re.search(r'[A-Za-z]{2}', c) and c.upper() not in POS), None)
            if name:
                out.append([name, cells[pi].upper(), [val, None]])
    if len(out) < 100:
        raise RuntimeError(f'only {len(out)} rows from {url}')
    pub = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d\d-\d\d)', page)
    return out, {'url': url, 'asOf': pub.group(1) if pub else TODAY}


# ---------------------------------------------------------------- FantasyPros trade value chart
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
          'september', 'october', 'november', 'december']


def fp_article():
    d = dt.date.today().replace(day=1)
    for back in range(4):
        y, mo = d.year, d.month
        for mm in (f'{mo:02d}', str(mo)):
            url = (f'https://www.fantasypros.com/{y}/{mm}/fantasy-football-rankings-'
                   f'dynasty-trade-value-chart-{MONTHS[mo - 1]}-{y}-update/')
            try:
                page = get(url)
                if 'datawrapper' in page:
                    return url, page
            except Exception:
                pass
        d = (d - dt.timedelta(days=1)).replace(day=1)
    raise RuntimeError('no recent article found')


def fp_pick_rows(page):
    """Pick tables follow headings like '2027 Dynasty Rookie Draft Pick Values'."""
    heads = [(m.start(), m.group(1)) for m in re.finditer(r'(20\d\d) Dynasty Rookie Draft Pick Values', page)]
    acc = {}
    for start, rows in tables(page):
        year = None
        for hs, y in heads:
            if hs < start:
                year = y
        if not year:
            continue
        for cells in rows:
            if len(cells) < 3:
                continue
            label, q, sf = cells[0], num(cells[1]), num(cells[2])
            if q is None or sf is None:
                continue
            m = re.match(r'^(\d)\.(\d\d)(?:\s*[–\-]\s*\d\.(\d\d))?$', label)
            if m:
                rd, a = int(m.group(1)), int(m.group(2))
                b = int(m.group(3) or a)
                mid = (a + b) / 2
                tier = 'Early' if mid <= 4.5 else ('Mid' if mid <= 8.5 else 'Late')
                if b - a >= 5:  # e.g. "1.07 - 1.12": treat as late
                    tier = 'Late' if a >= 6 else 'Mid'
                name = f'{year} {tier} {rd}' + {1: 'st', 2: 'nd', 3: 'rd'}.get(rd, 'th')
                acc.setdefault(name, []).append((sf, q))
                continue
            m = re.match(r'^(Early|Mid|Late) (\d)(st|nd|rd|th)$', label, re.I)
            if m:
                acc.setdefault(f'{year} {m.group(1).title()} {m.group(2)}{m.group(3)}', []).append((sf, q))
    out = []
    for name, v in acc.items():
        out.append([name, 'PICK', [sum(x[0] for x in v) / len(v), sum(x[1] for x in v) / len(v)]])
    return out


def fp():
    url, page = fp_article()
    out = []
    ids = dict.fromkeys(re.findall(r'datawrapper\.dwcdn\.net/([A-Za-z0-9]{5})/(\d+)', page))
    for cid, ver in ids:
        try:
            text = get(f'https://datawrapper.dwcdn.net/{cid}/{ver}/dataset.csv')
        except Exception:
            continue
        rd = list(csv.reader(io.StringIO(text), delimiter='\t' if text.count('\t') > text.count(',') else ','))
        if len(rd) < 2:
            continue
        h = [c.strip().lower() for c in rd[0]]
        ni = next((k for k, c in enumerate(h) if 'player' in c or c == 'name'), 0)
        qi = next((k for k, c in enumerate(h) if '1qb' in c.replace(' ', '')), None)
        si = next((k for k, c in enumerate(h) if c in ('sf', 'superflex', '2qb') or 'superflex' in c or c.startswith('sf')), None)
        for r in rd[1:]:
            if len(r) <= max(ni, qi or 0, si or 0):
                continue
            name = re.sub(r'\s*\((QB|RB|WR|TE)\)\s*$', '', r[ni]).strip()
            q = num(r[qi]) if qi is not None else None
            s = num(r[si]) if si is not None else None
            if name and (q is not None or s is not None):
                out.append([name, '', [s, q]])
    out += fp_pick_rows(page)
    if len([r for r in out if r[1] != 'PICK']) < 50:
        raise RuntimeError(f'only {len(out)} rows from {url}')
    pub = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d\d-\d\d)', page)
    return out, {'url': url, 'asOf': pub.group(1) if pub else TODAY}


# ---------------------------------------------------------------- injuries (Sleeper)
STATUS_MAP = {'Injured Reserve': 'IR', 'Physically Unable to Perform': 'PUP', 'Non Football Injury': 'NFI'}


def injuries():
    """Injury report for fantasy positions from Sleeper's player file (Sleeper asks for at most one
    download a day, which is what this daily job does). Returns {sleeper_id: [status, body_part]}."""
    data = json.loads(get('https://api.sleeper.app/v1/players/nfl'))
    out = {}
    for pid, p in data.items():
        if (p.get('position') or '') not in POS:
            continue
        st = STATUS_MAP.get(p.get('status') or '') or (p.get('injury_status') or '')
        st = {'Sus': 'Suspended', 'COV': 'Out'}.get(st, st)
        if not st or st in ('NA', 'Active', 'DNR'):
            continue
        out[str(pid)] = [st, p.get('injury_body_part') or '']
    if len(data) < 1000:
        raise RuntimeError(f'only {len(data)} players in Sleeper file')
    return out


# ---------------------------------------------------------------- weekly stats (nflverse, free and open)
NFLV = 'https://github.com/nflverse/nflverse-data/releases/download'
FFOPP = 'https://github.com/ffverse/ffopportunity/releases/download/latest-data'
IDS = 'https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv'


def csv_rows(url):
    return list(csv.DictReader(io.StringIO(get(url))))


def f1(x):
    try:
        return round(float(x), 1)
    except (TypeError, ValueError):
        return 0.0


def build_stats():
    """Per Sleeper player, this season's games: PPR points, receptions, expected PPR points and
    expected receptions (so the page can rescore for any league), snap share, targets, carries,
    target share, yards and touchdowns. Plus last season's totals."""
    today = dt.date.today()
    season = today.year if today.month >= 8 else today.year - 1
    ids = csv_rows(IDS)
    by_gsis = {r['gsis_id']: r['sleeper_id'] for r in ids if r.get('gsis_id') not in (None, '', 'NA') and r.get('sleeper_id') not in (None, '', 'NA')}
    by_pfr = {r['pfr_id']: r['sleeper_id'] for r in ids if r.get('pfr_id') not in (None, '', 'NA') and r.get('sleeper_id') not in (None, '', 'NA')}
    out, last_week = {}, 0

    def week_rows(yr):
        try:
            ep = csv_rows(f'{FFOPP}/ep_weekly_{yr}.csv')
            st = csv_rows(f'{NFLV}/stats_player/stats_player_week_{yr}.csv')
        except Exception:
            return None
        try:
            sn = csv_rows(f'{NFLV}/snap_counts/snap_counts_{yr}.csv')
        except Exception:
            sn = []
        return ep, st, sn

    cur = week_rows(season)
    if cur:
        ep, st, sn = cur
        stat = {(r['player_id'], r['week']): r for r in st if r.get('season_type', 'REG') == 'REG'}
        snap = {}
        for r in sn:
            if r.get('game_type', 'REG') != 'REG':
                continue
            sid = by_pfr.get(r['pfr_player_id'])
            if sid:
                snap[(sid, r['week'])] = round(float(r['offense_pct'] or 0) * 100)
        for r in ep:
            if r['position'] not in POS:
                continue
            sid = by_gsis.get(r['player_id'])
            if not sid:
                continue
            wk = r['week']
            s = stat.get((r['player_id'], wk), {})
            yds = f1(s.get('passing_yards')) + f1(s.get('rushing_yards')) + f1(s.get('receiving_yards'))
            td = int(f1(s.get('passing_tds')) + f1(s.get('rushing_tds')) + f1(s.get('receiving_tds')))
            row = [int(wk), f1(r['total_fantasy_points']), f1(r['receptions']), f1(r['total_fantasy_points_exp']),
                   f1(r['receptions_exp']), snap.get((sid, wk), None), int(f1(s.get('targets'))), int(f1(s.get('carries'))),
                   round(f1(s.get('target_share')) * 100), round(yds), td]
            p = out.setdefault(sid, {'t': r['posteam'], 'w': []})
            p['t'] = r['posteam']
            p['w'].append(row)
            last_week = max(last_week, int(wk))
        for p in out.values():
            p['w'].sort(key=lambda x: x[0])
    # last season's totals: games, PPR points, receptions, expected PPR points, expected receptions
    try:
        prev = csv_rows(f'{NFLV}/stats_player/stats_player_reg_{season - 1}.csv')
        pep = csv_rows(f'{FFOPP}/ep_weekly_{season - 1}.csv')
        xs = {}
        for r in pep:
            x = xs.setdefault(r['player_id'], [0.0, 0.0])
            x[0] += f1(r['total_fantasy_points_exp']); x[1] += f1(r['receptions_exp'])
        for r in prev:
            if r['position'] not in POS:
                continue
            sid = by_gsis.get(r['player_id'])
            g = int(f1(r.get('games')))
            if not sid or g < 1:
                continue
            x = xs.get(r['player_id'], [0.0, 0.0])
            out.setdefault(sid, {'t': r.get('recent_team') or r.get('team') or '', 'w': []})['py'] = [
                g, f1(r['fantasy_points_ppr']), f1(r['receptions']), round(x[0], 1), round(x[1], 1)]
    except Exception as e:
        print(f'stats: last season failed {e!r}', file=sys.stderr)
    if not out:
        raise RuntimeError('no stats rows')
    return {'asOf': TODAY, 'season': season, 'week': last_week, 'p': out}


# ---------------------------------------------------------------- value history (market momentum)
def update_history(rows):
    """Keep 45 days of KeepTradeCut and FantasyCalc Superflex values so the page can show how
    fast each player is moving across the markets that update daily."""
    h = {'dates': [], 'ktc': {}, 'fc': {}}
    if os.path.exists(HIST_OUT):
        try:
            with open(HIST_OUT) as f:
                h = json.load(f)
        except Exception:
            pass
    if h['dates'] and h['dates'][-1] == TODAY:
        h['dates'].pop()
        for src in ('ktc', 'fc'):
            for v in h[src].values():
                v.pop()
    n = len(h['dates'])
    h['dates'].append(TODAY)
    for src in ('ktc', 'fc'):
        cur = {r[0]: r[2][src][0] for r in rows if src in r[2] and r[2][src][0] is not None}
        for name in set(h[src]) | set(cur):
            series = h[src].setdefault(name, [None] * n)
            series += [None] * (n - len(series))
            series.append(round(cur[name]) if name in cur else None)
    keep = 45
    if len(h['dates']) > keep:
        cut = len(h['dates']) - keep
        h['dates'] = h['dates'][cut:]
        for src in ('ktc', 'fc'):
            for k in list(h[src]):
                h[src][k] = h[src][k][cut:]
                if all(v is None for v in h[src][k]):
                    del h[src][k]
    with open(HIST_OUT, 'w') as f:
        json.dump(h, f, separators=(',', ':'))


# ---------------------------------------------------------------- main
def main():
    prev = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            prev = json.load(f)
    prev_src = {s['id']: s for s in prev.get('sources', [])}
    prev_rows = {}
    for name, pos, vals in prev.get('rows', []):
        for sid, v in vals.items():
            prev_rows.setdefault(sid, []).append([name, pos, v])

    fetchers = {'ktc': lambda: ktc(), 'fc': lambda: fc(),
                'rw': lambda: rw((prev_src.get('rw') or {}).get('url')), 'fp': lambda: fp()}
    rows, sources = {}, []
    for meta in SOURCES:
        sid = meta['id']
        s = dict(meta)
        if sid == 'dp':
            sources.append(s)
            continue
        try:
            data, info = fetchers[sid]()
            s.update({'asOf': TODAY, 'count': len(data)})
            s.update({k: v for k, v in info.items() if v})
            print(f'{sid}: {len(data)} rows', file=sys.stderr)
        except Exception as e:  # keep the last good pull
            data = prev_rows.get(sid, [])
            old = prev_src.get(sid, {})
            s.update({k: old.get(k) for k in ('asOf', 'count', 'url') if old.get(k)})
            s['note'] = f'Last refresh failed ({type(e).__name__}); showing data from {old.get("asOf", "never")}'
            print(f'{sid}: FAILED {e!r}; kept {len(data)} old rows', file=sys.stderr)
        if not data:
            continue
        sources.append(s)
        for name, pos, v in data:
            key = name.lower()
            r = rows.setdefault(key, [name, pos, {}])
            if pos and not r[1]:
                r[1] = pos
            r[2][sid] = [None if x is None else round(float(x), 1) for x in v]
    out = {'asOf': TODAY, 'sources': sources, 'rows': sorted(rows.values(), key=lambda r: r[0])}
    try:
        out['injuries'] = injuries()
        out['injuriesAsOf'] = TODAY
        print(f'injuries: {len(out["injuries"])} players listed', file=sys.stderr)
    except Exception as e:  # keep yesterday's report rather than none
        if prev.get('injuries'):
            out['injuries'] = prev['injuries']
            out['injuriesAsOf'] = prev.get('injuriesAsOf')
        print(f'injuries: FAILED {e!r}; kept previous report', file=sys.stderr)
    with open(OUT, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    try:
        stats = build_stats()
        with open(STATS_OUT, 'w') as f:
            json.dump(stats, f, separators=(',', ':'))
        print(f'stats: {len(stats["p"])} players through week {stats["week"]}', file=sys.stderr)
    except Exception as e:  # keep yesterday's stats.json
        print(f'stats: FAILED {e!r}; kept previous file', file=sys.stderr)
    try:
        update_history(out['rows'])
    except Exception as e:
        print(f'history: FAILED {e!r}', file=sys.stderr)
    print(f'wrote {len(out["rows"])} rows from {len(sources)} sources', file=sys.stderr)


if __name__ == '__main__':
    main()
