from bs4 import BeautifulSoup
import aiohttp
import re
import json
import datetime
import asyncio
import itertools

async def gather_restaurants():
    async with aiohttp.ClientSession() as session:
        async def bistroin():
            async with session.get("https://onemenu.cz/menu/Bistro-In") as r:
                text = await r.text()
                dom = BeautifulSoup(text, 'html.parser')
                foods = []
                soup = None
                soup_price = None
                for node in dom.select('.orderitem-right'):
                    ingredients = node.select('.ingredients')[0].get_text()
                    ingredients = re.sub('Al\. \(.+', '', ingredients)
                    name = node.select('.name')[0].get_text()
                    price = node.select('.priceValue')[0].get_text().split()[0]
                    if 'Polévka' in name:
                        soup = name.split(':')[1]
                        soup_price = price
                    else:
                        parts = name.split('.', 1)
                        if len(parts) == 2:
                            foods.append({
                                'num': parts[0],
                                'name': parts[1],
                                'ingredients': ingredients,
                                'price': price,
                            })
                return {
                    'name': 'Bistro IN',
                    'soup': soup,
                    'soup_price': soup_price,
                    'lunches': foods,
                }

        async def pustkovecka_basta():
            async with session.get("https://www.pustkoveckabasta.cz/pustkovecka-basta") as r:
                text = await r.text()
                dom = BeautifulSoup(text, 'html.parser')
                soup = None
                foods = []
                for node in dom.select('.food-item'):
                    name = node.select('h4')[0].get_text()
                    if 'Polévka' in name:
                        continue

                    date = node.find_parent('div', {'class': 'daily-item'}).get('data-date')
                    if date and date != datetime.datetime.now().strftime("%Y-%m-%d"):
                        continue

                    parts = name.split('.', 1)
                    if len(parts) == 2:
                        soup = node.select('.menu-detail')[0].get_text().replace('Polévka:', '')

                        foods.append({
                            'num': parts[0],
                            'name': re.sub('\d+g', '', parts[1]),
                            'price': node.select('.price')[0].get('data-price'),
                        })
                return {
                    'name': 'Pustkovecká bašta',
                    'soup': soup,
                    'lunches': foods,
                }

        async def u_jarosu():
            async with session.get("https://www.ujarosu.cz/cz/denni-menu/") as r:
                result = {
                    'name': 'U Jarošů',
                    'soup': None,
                    'lunches': [],
                }

                text = await r.text()
                dom = BeautifulSoup(text, 'html.parser')

                days = dom.findAll('tr', {'height': 29})
                nth_day = datetime.datetime.today().weekday()
                if len(days) <= nth_day:
                    return result

                day = days[nth_day]
                result['soup'] = day.select('td')[1].get_text()

                node = day.find_next_sibling('tr')
                counter = 0
                food = {}
                foods = []
                while node and int(node.get('height')) != 29:
                    try:
                        num = int(node.select('td')[0].get_text().strip().split('.')[0])
                    except ValueError:
                        num = -1
                    if num == counter + 1:
                        counter += 1
                        if food:
                            foods.append(food)
                        food = {
                            'name': node.select('td')[1].get_text(),
                            'price': node.select('td')[2].get_text(),
                            'num': str(num),
                        }
                    else:
                        food['name'] += ' ' + node.select('td')[1].get_text()

                    node = node.find_next_sibling('tr')

                if food:
                    foods.append(food)

                result['foods'] = foods
                return result

        async def u_zlateho_lva():
            day_nth = datetime.datetime.today().weekday()
            if day_nth >= 5:
                return {
                    'name': 'U Zlatého Lva',
                    'soup': '',
                    'lunches': [],
                }

            async with session.get("http://www.zlatylev.com/menu_zlaty_lev.html") as r:
                text = await r.text()
                dom = BeautifulSoup(text, 'html.parser')
                foods = []
                text = dom.select('.xr_txt.xr_s0')[0].get_text()

                def remove_alergens(s):
                    return re.sub('\(A-\d.+', '', s)

                days = ['Ponděl', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek']
                capturing = False
                counter = 0
                food = {}
                soup = None
                for line in text.splitlines():
                    line = line.strip()

                    print(line)
                    if line.startswith(days[day_nth]):
                        capturing = True
                    elif capturing:
                        if line.startswith('Polévka:'):
                            soup = remove_alergens(line.split(':')[1])
                        else:
                            try:
                                num = int(line.split('.')[0])
                                if num == counter + 1:
                                    counter += 1
                                    num, name = remove_alergens(line).split('.', 1)
                                    if food:
                                        foods.append(food)
                                    food = {
                                        'num': num,
                                        'name': re.sub('^\d+g', '', name.strip()),
                                        'soup': soup,
                                    }
                            except ValueError:
                                if ',-Kč' in line:
                                    food['price'] = line.split(',')[0]

                if food:
                    foods.append(food)

                return {
                    'name': 'U Zlatého Lva',
                    'soup': soup,
                    'lunches': foods,
                }

        restaurants = [
            bistroin,
            pustkovecka_basta,
            u_jarosu,
            u_zlateho_lva
        ]

        foods = await asyncio.gather(*[f() for f in restaurants])
        names = [r.__name__ for r in restaurants]

        def cleanup_foods(foods):
            def fix_name(name):
                uppers = sum(1 for c in name if c.isupper())
                if uppers > len(name) / 2:
                    name = name.lower()
                    name = name.capitalize()
                return name

            for food in foods['lunches']:
                for k, v in food.items():
                    food[k] = v.strip()
                    if k == 'price':
                        try:
                            food[k] = int(food[k])
                        except ValueError:
                            pass
                food['name'] = fix_name(food['name'])
            if foods['soup']:
                foods['soup'] = fix_name(foods['soup'])
            return foods


        return map(cleanup_foods, foods)
