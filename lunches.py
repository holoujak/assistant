#!/usr/bin/env python3
from bs4 import BeautifulSoup
import subprocess
import re
import json
import datetime
import itertools
import traceback
import tempfile
import logging
import requests
import string
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time

days = ['Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota', 'Neděle']
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36'

logging.basicConfig(level=logging.DEBUG)

def restaurant(title, url=None):
    def wrapper(fn):
        def wrap(*args, **kwargs):
            return fn(*args, **kwargs)
        wrap.parser = {
            'name': fn.__name__,
            'title': title,
            'url': url,
            'args': fn.__code__.co_varnames[:fn.__code__.co_argcount],
        }
        return wrap
    return wrapper

@dataclass
class Soup:
    name: str
    price: int = None

@dataclass
class Lunch:
    name: str
    num: int = None
    price: int = None
    ingredients: str = None

@restaurant("Bistro IN", "https://bistroin.choiceqr.com/delivery")
def bistroin(dom):
    data = json.loads(dom.select('#__NEXT_DATA__')[0].get_text())

    for item in data["props"]["app"]["menu"]:
        ingredients = re.sub('Al\. \(.+', '', item['description'])
        price = item['price'] // 100
        if 'Polévka k menu:' in item['name']:
            yield Soup(name=item['name'].split(':')[1], price=price)
        else:
            parts = item['name'].split('.', 1)
            if len(parts) == 2:
                yield Lunch(num=parts[0], name=parts[1], price=price - 5, ingredients=ingredients)

@restaurant("U jarosu", "https://www.ujarosu.cz/cz/denni-menu/")
def u_jarosu(dom):
    day_nth = datetime.datetime.today().weekday()

    counter = 0
    food = {}
    capturing = False
    for row in dom.findAll('tr'):
        day = row.select('td')[0].get_text().strip(' \n\t\xa0:')
        if day in days:
            if capturing:
                break
            if day == days[day_nth]:
                capturing = True
                yield Soup(name=row.select('td')[1].get_text())
        elif capturing:
            spaces = all(not td.get_text().strip() for td in row.select('td'))
            if spaces:
                break

            try:
                num = int(row.select('td')[0].get_text().strip().split('.')[0])
            except ValueError:
                num = -1
            if num == counter + 1:
                counter += 1
                if food:
                    yield food
                food = Lunch(
                    name=row.select('td')[1].get_text(),
                    price=row.select('td')[2].get_text() if len(row.select('td')) >= 3 else None,
                    num=num,
                )
            else:
                food.name += ' ' + row.select('td')[1].get_text()

    if food:
        yield food

@restaurant("U zlateho lva", "http://www.zlatylev.com/menu_zlaty_lev.html")
def u_zlateho_lva(dom):
    day_nth = datetime.datetime.today().weekday()
    text = dom.select('.xr_txt.xr_s0')[0].get_text()

    capturing = False
    counter = 0
    state = 'name'
    for line in text.splitlines():
        line = line.strip()

        if line.startswith(days[day_nth]):
            capturing = True
        elif capturing:
            if day_nth < 4 and line.startswith(days[day_nth + 1]):
                break
            soup_prefix = 'Polévka:'
            if line.startswith(soup_prefix):
                yield Soup(line.replace(soup_prefix, ''))
            else:
                if state == 'name':
                    if re.match('^[0-9]+\.', line):
                        line, name = line.split('.', 1)
                        food = Lunch(name=name, num=line)
                        state = 'price'
                elif state == 'price':
                    if re.match('^[0-9]+\s*(,-|Kč)$', line):
                        food.price = line.split(' ')[0]
                        yield food
                        state = 'name'

@restaurant("Globus", "https://www.globus.cz/ostrava/nabidka/restaurace.html")
def globus(dom):
    for row in dom.select('.restaurant__menu-food-table')[0].select('tr'):
        tds = row.select('td')
        name = tds[1].text
        price = tds[2].text.replace(',–', '') if len(tds) >= 3 else None
        yield (Lunch if price and int(price) > 50 else Soup)(name=name, price=price)

@restaurant("Jacks Burger", "https://www.zomato.com/cs/widgets/daily_menu.php?entity_id=16525845")
def jacks_burger(dom):
    day_nth = datetime.datetime.today().weekday()

    started = False
    prev_line = ""
    for el in dom.select('.main-body > div'):
        if 'line-wider' in el.get('class', []):
            break
        name = el.select_one('.item-name')
        if name:
            name = name.text.strip()
            num = None
            if re.match('^[0-9]+\..+', name):
                num = name.split('.')[0]

            if num:
                if not started:
                    yield Soup(name=prev_line)
                    started = True

                price = el.select_one('.item-price')
                if price:
                    price = price.text.strip()
                    yield Lunch(name=name, price=price, num=num)
            else:
                prev_line = name

@restaurant("Poklad", "https://dkpoklad.cz/restaurace/poledni-menu-4-8-6-8/")
def poklad(res):
    images = [r.strip().split(' ') for r in re.search('srcset="([^"]+)"', res).group(1).split(',')]
    img = sorted(images, key=lambda r: int(r[1].replace('w', '')))[-1][0]
    with requests.get(img) as r:
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(r.content)
            tmp.flush()
            txt = subprocess.check_output(['tesseract', '--psm', '6', '-l', 'ces', tmp.name, '-'], text=True)

        in_common = True
        in_day = False
        in_day_soup = False
        for line in txt.splitlines():
            m = re.match('([0-9]{1,2})\s*\.*\s*([0-9]{1,2})\s*\.*\s*([0-9]{4})', line)
            if m:
                c = [int(i) for i in m.groups()]
                day = datetime.date(day=c[0], month=c[1], year=c[2]).weekday()
                day_nth = datetime.datetime.today().weekday()
                in_day = day == day_nth
                in_day_soup = in_day
                in_common = False
            elif re.match('^[0-9]+', line):
                if in_common or in_day:
                    price = re.search('([0-9]{3}) kč', line.lower())
                    m = re.search('^(?P<num>[0-9]+)\s*\.?\s*[0-9]+\s*(g|ks|)\s*[\|—]?\s*(?P<name>.+).*?(?P<price>[12][0-9]{2})', line)
                    values = m.groupdict() if m else {'name': line}
                    if len(values['name']) > 8:
                        yield Lunch(**values)
            elif in_day_soup:
                in_day_soup = False
                for soup in line.split('/'):
                    yield Soup(name=soup)

@restaurant("Trebovicky mlyn", "https://www.trebovickymlyn.cz/")
def trebovicky_mlyn(dom):
    el = dom.select('.soup h2')
    if not el:
        return
    yield Soup(el[0].text)

    for lunch in dom.select('.owl-carousel')[0].select('.menu-post'):
        parts = lunch.select('h2')[0].text.split(')')
        if len(parts) == 2:
            yield Lunch(num=parts[0], name=parts[1], ingredients=lunch.select('h2 + div')[0].text, price=lunch.select('span')[0].text.split(',')[0])

@restaurant("Arrows", "https://restaurace.arrows.cz/")
def arrows():
    tday = datetime.datetime.now().date()
    week = tday.isocalendar().week

    for t in ['GetSoupsByActualWeekNumber', 'GetMenusByActualWeekNumber']:
        res = requests.get(f"https://restaurace.arrows.cz/api/menu/{t}/{week}")
        for item in res.json():
            date = datetime.datetime.fromisoformat(item['validDateTime']).date()
            if date != tday or item['deletedDate']:
                continue

            if item['isSoup']:
                yield Soup(name=item['text'])
            else:
                yield Lunch(num=item['menuItemOrder'] + 1, name=item['text'], price=item['price'])

@restaurant("La Strada", "http://www.lastrada.cz/cz/?tpl=plugins/DailyMenu/print&week_shift=")
def lastrada(dom):
    day_nth = datetime.datetime.today().weekday()

    capturing = False
    for tr in dom.select('tr'):
        if 'day' in tr.get('class', []):
            capturing = False
            if days[day_nth] in tr.text or 'Menu na celý týden' in tr.text:
                capturing = True
        elif capturing:
            if 'highlight' in tr.get('class', []):
                yield Lunch(name=tr.select_one('td').text, price=tr.select_one('.price').text)

@restaurant("Ellas", "https://www.restauraceellas.cz/")
def ellas(dom):
    day_nth = datetime.datetime.today().weekday()

    for div in dom.select('.moduletable .custom'):
        if div.find('h3').text.strip() != days[day_nth]:
            continue
        foods = div.select('p')
        yield Soup(name=foods[0].text)

        for food in foods[1:]:
            parts = food.decode_contents().split('<br')
            num, name = parts[0].split('.')

            yield Lunch(num=num, name=name, ingredients=parts[1], price=parts[2])

def gather_restaurants(allowed_restaurants=None):
    requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += ':HIGH:!DH:!aNULL'

    def cleanup(restaurant):
        def fix_name(name):
            uppers = sum(1 for c in name if c.isupper())
            if uppers > len(name) / 2:
                name = name.lower()
                name = name.capitalize()
            name = re.sub('\d+\s*(g|ml|ks) ', '', name)
            name = re.sub('\([^)]+\)', '', name)
            name = re.sub('(\s*[0-9]+\s*,)+\s*$', '', name)
            name = re.sub('A?[0-9]+(,[0-9]+){1,},?', '', name)
            return name.strip(string.punctuation + string.whitespace + string.digits + '–')

        for t in ['lunches', 'soups']:
            num = 0
            for food in restaurant.get(t, []):
                if food.price:
                    if isinstance(food.price, str):
                        try:
                            food.price = int(food.price.replace('Kč', '').replace('.00', '').strip(string.punctuation + string.whitespace))
                        except ValueError as e:
                            print(e)
                            pass
                    else:
                        food.price = int(food.price)

                food.name = fix_name(food.name)
                if t == 'lunches':
                    if food.ingredients:
                        food.ingredients = fix_name(food.ingredients)

                    if food.num:
                        try:
                            food.num = int(food.num)
                        except ValueError as e:
                            logging.exception(e)
                            food.num = None
                    if not food.num:
                        food.num = num + 1
                    num = food.num
        return restaurant

    def collect(parser):
        start = time.time()
        res = {
            'name': parser.parser['title'],
            'url': parser.parser['url'],
        }
        try:
            lunches = []
            soups = []

            args = {}
            arg_names = parser.parser['args']
            if 'res' in arg_names or 'dom' in arg_names:
                response = requests.get(parser.parser['url'], headers={'User-Agent': USER_AGENT})
                response.encoding = 'utf-8'
                if 'res' in arg_names:
                    args['res'] = response.text
                else:
                    args['dom'] = BeautifulSoup(response.text, 'html.parser')

            for item in parser(**args) or []:
                if isinstance(item, Soup):
                    soups.append(item)
                elif isinstance(item, Lunch):
                    lunches.append(item)
                else:
                    raise "Unsupported item"
            return cleanup({
                **res,
                'lunches': lunches,
                'soups': soups,
                'elapsed': time.time() - start,
            })
        except:
            return {
                **res,
                'error': traceback.format_exc(),
                'elapsed': time.time() - start,
            }

    restaurants = [obj for _, obj in globals().items() if hasattr(obj, 'parser')]
    if not allowed_restaurants:
        allowed_restaurants = [r.parser['name'] for r in restaurants]

    with ThreadPoolExecutor(max_workers=len(allowed_restaurants)) as pool:
        return pool.map(collect, [r for r in restaurants if r.parser['name'] in allowed_restaurants])

if __name__ == '__main__':
    from pprint import pprint
    import sys

    allowed_restaurants = None
    if len(sys.argv) > 1:
        allowed_restaurants = sys.argv[1].split(',')
    res = gather_restaurants(allowed_restaurants)
    pprint(list(res), width=180)
