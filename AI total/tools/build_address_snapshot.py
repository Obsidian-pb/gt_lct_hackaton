"""Build a portable OSM city snapshot from the simulator's existing GeoJSON export.

Usage: python tools/build_address_snapshot.py --source ../data
No network or geocoder is used. Source export date is unknown.
"""
import argparse
import hashlib
import json
from pathlib import Path


def interior(rings):
    # Widest inside interval on a scanline; includes holes (even/odd fill).
    ys = sorted({p[1] for ring in rings for p in ring})
    y = (ys[len(ys)//2-1] + ys[len(ys)//2]) / 2
    xs = []
    for ring in rings:
        for a, b in zip(ring, ring[1:]):
            if (a[1] > y) != (b[1] > y):
                xs.append(a[0] + (y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
    xs.sort()
    intervals = list(zip(xs[::2], xs[1::2]))
    if not intervals:
        return rings[0][0]
    a, b = max(intervals, key=lambda pair: pair[1]-pair[0])
    return [round((a+b)/2, 7), round(y, 7)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    source = args.source
    out = Path(__file__).resolve().parents[1] / 'ui' / 'geo'
    out.mkdir(parents=True, exist_ok=True)
    inputs = {n: (source / (n+'.geojson')).read_bytes() for n in ('buildings', 'roads', 'boundary')}
    data = {n: json.loads(raw) for n, raw in inputs.items()}
    addresses, buildings, roads, streets, seen = [], [], [], {}, set()
    for feature in data['buildings']['features']:
        p, g = feature['properties'], feature['geometry']
        polygons = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        rings = max(polygons, key=lambda poly: (max(x[0] for x in poly[0])-min(x[0] for x in poly[0])) * (max(x[1] for x in poly[0])-min(x[1] for x in poly[0])))
        point = interior(rings)
        street, house = (p.get('addr:street') or '').strip(), (p.get('addr:housenumber') or '').strip()
        buildings.append({'rings': [[[round(x, 6), round(y, 6)] for x, y in r] for r in rings], 'point': point, 'house': house})
        if street:
            streets.setdefault(street, []).append(point)
        if street and house:
            # Original export keeps an ID but loses OSM element type: do not invent an OSM URL.
            addresses.append({'id': 'building-'+str(p['id']), 'kind': 'building', 'street': street, 'house': house, 'point': point})
    for feature in data['roads']['features']:
        p, g = feature['properties'], feature['geometry']
        if g['type'] != 'LineString':
            continue
        points = [[round(x, 6), round(y, 6)] for x, y in g['coordinates']]
        key = min(str(points), str(list(reversed(points))))
        if key in seen:
            continue
        seen.add(key)
        name = p.get('name') or ''
        if not isinstance(name, str) or name.startswith('['):
            name = ''
        roads.append({'points': points, 'name': name, 'type': p.get('highway') or ''})
        if name:
            streets.setdefault(name, []).append(points[len(points)//2])
    for i, (street, points) in enumerate(sorted(streets.items())):
        center = [sum(p[j] for p in points)/len(points) for j in (0, 1)]
        point = min(points, key=lambda p: sum((p[j]-center[j])**2 for j in (0, 1)))
        addresses.append({'id': 'street-'+str(i), 'kind': 'street', 'street': street, 'house': '', 'point': point})
    meta = {'version': 1, 'city': 'Железногорск', 'region': 'Красноярский край', 'country': 'Россия', 'source': 'OpenStreetMap', 'license': 'ODbL-1.0', 'attribution': '© OpenStreetMap contributors', 'source_export_date': None, 'source_sha256': {n: hashlib.sha256(b).hexdigest() for n, b in inputs.items()}}
    for name, payload in [('addresses', {**meta, 'addresses': addresses}), ('map', {**meta, 'buildings': buildings, 'roads': roads, 'boundary': data['boundary']['features'][0]['geometry']['coordinates'][0]})]:
        (out / (name+'.json')).write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'OSM snapshot: {len(addresses)} address/street results, {len(buildings)} buildings, {len(roads)} road segments')


if __name__ == '__main__':
    main()
