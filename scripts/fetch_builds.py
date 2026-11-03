#!/usr/bin/env python3
# Качает билды с dota2protracker в builds/<герой>.json. Запускается GitHub Action.
# Низкая частота запросов, один поток. Если сайт блокирует (403/429), скрипт останавливается и пишет это в отчёт.
import datetime, json, os, pathlib, re, sys, time, urllib.error, urllib.request
from html.parser import HTMLParser

BASE = os.environ.get('D2PT_BASE', 'https://dota2protracker.com').rstrip('/')
HEROES = os.environ.get('HEROES_URL', 'https://api.opendota.com/api/heroes')
ONLY = {x.strip() for x in os.environ.get('ONLY', '').split(',') if x.strip()}
DELAY = float(os.environ.get('DELAY', '1.2'))
OUT = pathlib.Path(os.environ.get('OUT', '.'))
UA = 'dota-draft-helper (personal use, low rate)'


class LP(HTMLParser):
    IN = {'span', 'a', 'b', 'i', 'em', 'strong', 'small', 'sup', 'sub', 'label', 'abbr', 'button', 'font'}
    SKIP = {'script', 'style', 'noscript', 'svg'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.L, self.cur, self.skip = [], '', 0

    def fl(self):
        s = re.sub(r'\s+', ' ', self.cur).strip()
        if s:
            self.L.append(s)
        self.cur = ''

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == 'img':
            self.fl()
            alt = (dict(attrs).get('alt') or '').strip()
            if alt:
                self.L.append(alt)
        elif tag == 'br':
            self.fl()
        elif tag in self.IN:
            self.cur += ' '
        else:
            self.fl()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in self.IN:
            self.cur += ' '
        elif tag not in ('img', 'br'):
            self.fl()

    def handle_data(self, d):
        if not self.skip:
            self.cur += d


def lines(html):
    p = LP()
    p.feed(html)
    p.fl()
    return p.L


def parse(L):
    nn = lambda s: s.replace('’', "'").replace('‘', "'").strip()

    def sec(rx):
        return next((i for i, l in enumerate(L) if re.fullmatch(rx, l)), -1)

    def g(rx, off):
        i = sec(rx)
        return L[i + off] if 0 <= i and i + off < len(L) else ''

    num = lambda s: (lambda m: float(m.group()) if m else None)(re.search(r'\d+(?:\.\d+)?', s))
    o = {'title': '', 'wr': num(g(r'Win Rate', 1)), 'm': None, 'start': [], 'core': [], 'sit': [], 'neu': {}}
    mm = num(g(r'Matches', 1))
    o['m'] = int(mm) if mm is not None else None
    ti = next((i for i, l in enumerate(L) if re.match(r'#\d+ ', l)), -1)
    o['title'] = L[ti + 1] if 0 <= ti < len(L) - 1 else ''
    a, c, s, k, n = sec(r'Starting items'), sec(r'Core build order'), sec(r'Situational'), sec(r'Skills'), sec(r'Neutral items')
    end = lambda x, y: y if y > x else len(L)
    if a >= 0:
        for i in range(a, end(a, c)):
            p = re.fullmatch(r'(\d+)% pick', L[i])
            w = re.fullmatch(r'(\d+)% WR', L[i + 1]) if i + 1 < len(L) else None
            q = re.fullmatch(r'(.+) · (\d+) matches', L[i + 2]) if i + 2 < len(L) else None
            if p and w and q:
                items = []
                for x in q.group(1).split(' · '):
                    z = re.fullmatch(r'(.*?)(?: ×(\d+))?', x)
                    items.append([nn(z.group(1)), int(z.group(2) or 1)])
                o['start'].append([items, int(p.group(1)), int(w.group(1)), int(q.group(2))])
    if c >= 0:
        for i in range(c + 1, end(c, s)):
            t = re.fullmatch(r"(?:(.+?) )?(\d+(?:\.\d+)?)'", L[i])
            r = re.fullmatch(r'(\d+)% · (\d+)%', L[i + 1]) if i + 1 < len(L) else None
            if t and r:
                o['core'].append([nn(t.group(1) or L[i - 1]), float(t.group(2)), int(r.group(1)), int(r.group(2))])
    if s >= 0:
        for i in range(s + 1, end(s, k)):
            m = re.fullmatch(r"(\d+)% pick (\d+)% WR (\d+)'", L[i])
            if m:
                o['sit'].append([nn(L[i - 1]), int(m.group(3)), int(m.group(1)), int(m.group(2))])
    if n >= 0:
        tr = 0
        for i in range(n + 1, len(L)):
            t = re.fullmatch(r'Tier (\d)', L[i])
            m = re.fullmatch(r'(\d+)% (\d+)%', L[i])
            if t:
                tr = int(t.group(1))
            elif m and tr:
                o['neu'].setdefault(str(tr), []).append([nn(L[i - 1]), int(m.group(1)), int(m.group(2))])
    return o


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception as e:
        return 0, str(e)


def slugs(name):
    a = re.sub(r'[^a-z0-9]+', '-', re.sub(r"['.]", '', name.lower())).strip('-')
    b = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return ([a] + ([b] if b != a else [])), a


def main():
    code, body = get(HEROES)
    if code != 200:
        print('не получил список героев', code, body[:200])
        sys.exit(1)
    heroes = json.loads(body)
    (OUT / 'builds').mkdir(exist_ok=True)
    (OUT / 'debug').mkdir(exist_ok=True)
    rep = {'started': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'heroes_ok': 0, 'pages': 0, 'parse_fail': [], 'errors': [], 'blocked': False}
    patch, bad, dbg_fail = '', 0, 0
    for h in heroes:
        name = h['localized_name']
        vs, key = slugs(name)
        if ONLY and key not in ONLY:
            continue
        res = {}
        for pos in range(1, 6):
            lst = []
            for i in range(1, 6):
                page = None
                for sl in vs:
                    time.sleep(DELAY)
                    code, html = get(f'{BASE}/builds/{sl}-pos{pos}-{i}')
                    if code == 200 and len(html) > 2000:
                        page, bad = (sl, html), 0
                        break
                    if code not in (404, 200):
                        bad += 1
                        if len(rep['errors']) < 40:
                            rep['errors'].append(f'{sl}-pos{pos}-{i}: {code or html[:80]}')
                if bad >= 8 or not page:
                    break
                L = lines(page[1])
                b = parse(L)
                rep['pages'] += 1
                tag = f'{page[0]}-pos{pos}-{i}'
                if not (OUT / 'debug' / 'sample.html').exists():
                    (OUT / 'debug' / 'sample.html').write_text(page[1], encoding='utf-8')
                    (OUT / 'debug' / 'sample_lines.txt').write_text('\n'.join(L), encoding='utf-8')
                if not b['core']:
                    rep['parse_fail'].append(tag)
                    if dbg_fail < 3:
                        (OUT / 'debug' / f'fail_{tag}.html').write_text(page[1], encoding='utf-8')
                        (OUT / 'debug' / f'fail_{tag}_lines.txt').write_text('\n'.join(L), encoding='utf-8')
                        dbg_fail += 1
                    break
                lst.append(b)
                if not patch:
                    m = re.search(r'Patch ([\w.]+) Released', ' '.join(L[:40]))
                    patch = m.group(1) if m else ''
            if bad >= 8:
                break
            if lst:
                res[str(pos)] = lst
        if bad >= 8:
            rep['blocked'] = True
            break
        if res:
            data = {'hero': name, 'slug': key, 'patch': patch, 'updated': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'builds': res}
            (OUT / 'builds' / f'{key}.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            rep['heroes_ok'] += 1
        print(name, sorted(res), flush=True)
    rep['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (OUT / 'builds' / '_report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(rep, ensure_ascii=False)[:600])


if __name__ == '__main__':
    main()
