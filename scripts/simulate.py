"""Send device and environmental telemetry through the actual HTTP ingestion API."""
import argparse
import json
import random
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8000')
parser.add_argument('--device', default='P-101')
parser.add_argument('--count', type=int, default=10)
parser.add_argument('--interval', type=float, default=1)
args = parser.parse_args()
if args.count < 1 or args.interval < 0:
    parser.error('count must be positive and interval nonnegative')
for index in range(args.count):
    payload = {'device_id': args.device, 'temperature': round(60 + random.random() * 28, 1),
        'vibration': round(3 + random.random() * 5, 2), 'current': round(20 + random.random() * 4, 1),
        'pressure': round(.5 + random.random() * .1, 3), 'ambient_temperature': 26.4,
        'humidity': 58, 'source': 'demo-simulator'}
    request = urllib.request.Request(args.url + '/api/telemetry', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        print(json.load(response))
    if index + 1 < args.count:
        time.sleep(args.interval)
