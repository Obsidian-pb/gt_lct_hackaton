"""Route an assigned service to an exact locally indexed OSM house address."""
from functools import lru_cache
from heapq import heappop, heappush
from math import cos, hypot, radians
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent / 'ui' / 'geo'


def _street(value):
    value = str(value or '').casefold().replace('ё', 'е')
    value = re.sub(r'\b(улица|ул\.?|проспект|пр\.?|переулок|пер\.?|бульвар|бул\.?|шоссе)\b', '', value)
    return re.sub(r'[^\w]+', '', value)


def _house(value):
    return re.sub(r'[^0-9a-zа-я]', '', str(value or '').casefold().replace('ё', 'е'))


def _meters(a, b):
    return hypot((a[0]-b[0])*62000, (a[1]-b[1])*111200)


@lru_cache(maxsize=1)
def _data():
    addresses = json.loads((ROOT/'addresses.json').read_text(encoding='utf-8'))
    map_data = json.loads((ROOT/'map.json').read_text(encoding='utf-8'))
    index = {}
    for row in addresses['addresses']:
        index.setdefault((_street(row['street']), _house(row['house'])), []).append(row)
    graph = {}
    for road in map_data['roads']:
        for a,b in zip(road['points'], road['points'][1:]):
            a,b = tuple(a),tuple(b)
            length = _meters(a,b)
            if length:
                graph.setdefault(a, []).append((b,length))
                graph.setdefault(b, []).append((a,length))
    return addresses, index, graph


def _nearest(point, vertices):
    return min(vertices, key=lambda v:_meters(point,v))


def route(card, service):
    addresses,index,graph = _data()
    city = (card.get('city') or '').casefold().replace('ё','е')
    if city and city != addresses['city'].casefold().replace('ё','е'):
        return {'found':False,'message':'Маршрут доступен только для адресов Железногорска из учебной карты.'}
    street,house = card.get('street'),card.get('house')
    matches = index.get((_street(street),_house(house)), []) if street and house else []
    if not matches:
        return {'found':False,'message':'Дом с указанными улицей и номером отсутствует в локальном справочнике OSM. Уточните точный адрес карточки.'}
    destination = matches[0]
    # A stable training base: a different indexed building within the same city.
    candidates = [row for row in addresses['addresses']
                  if row['id'] != destination['id'] and 900 < _meters(row['point'],destination['point']) < 2200]
    if not candidates:
        return {'found':False,'message':'Для этого дома не найдена учебная база службы на карте.'}
    origin = candidates[sum(ord(c) for c in service) % len(candidates)]
    vertices = tuple(graph)
    start,end = _nearest(origin['point'],vertices),_nearest(destination['point'],vertices)
    if _meters(start,origin['point'])>180 or _meters(end,destination['point'])>180:
        return {'found':False,'message':'До указанного дома не удалось привязать проезд к дорожной сети OSM.'}
    queue=[(0,start)]
    costs={start:0}
    previous={}
    while queue:
        length,node=heappop(queue)
        if length!=costs[node]:
            continue
        if node==end:
            break
        for next_node,distance in graph[node]:
            total=length+distance
            if total<costs.get(next_node,float('inf')):
                costs[next_node]=total
                previous[next_node]=node
                heappush(queue,(total,next_node))
    if end not in costs:
        return {'found':False,'message':'До указанного дома не найден связный маршрут по дорожной сети OSM.'}
    points=[end]
    while points[-1]!=start:
        points.append(previous[points[-1]])
    points.reverse()
    return {'found':True,'service':service,
            'origin':{'label':f"Учебная база службы · {origin['street']}, {origin['house']}",'point':origin['point']},
            'destination':{'label':f"{destination['street']}, {destination['house']}",'point':destination['point'],'id':destination['id']},
            'points':[origin['point'],*points,destination['point']],
            'distance_m':round(costs[end]+_meters(start,origin['point'])+_meters(end,destination['point'])),
            'attribution':'© OpenStreetMap contributors'}
