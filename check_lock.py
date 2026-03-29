import json
with open('package-lock.json') as f:
    d = json.load(f)
for key in ['@types/react','postcss-selector-parser','yaml','mapbox-gl','fsevents','typescript']:
    v = d.get('packages', {}).get('node_modules/' + key, {}).get('version')
    print(key, v)
