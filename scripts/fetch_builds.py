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