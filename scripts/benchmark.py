"""Measure HTTP overview queries; results apply only to the supplied environment."""
import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8000')
parser.add_argument('--requests', type=int, default=200)
parser.add_argument('--concurrency', type=int, default=4)
args = parser.parse_args()
if args.requests < 1 or args.concurrency < 1:
    parser.error('requests and concurrency must be positive')


def query(_):
    start = time.perf_counter()
    with urllib.request.urlopen(args.url + '/api/overview', timeout=30) as response:
        data = json.load(response)
    return (time.perf_counter() - start) * 1000, data


query(0)
with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
    results = list(executor.map(query, range(args.requests)))
latencies = sorted(result[0] for result in results)
print(json.dumps({'requests': len(results), 'concurrency': args.concurrency,
    'telemetry_count': results[-1][1]['telemetry_count'], 'shards': results[-1][1]['shard_count'],
    'p50_ms': round(statistics.median(latencies), 2),
    'p95_ms': round(latencies[min(len(latencies) - 1, int(len(latencies) * .95))], 2),
    'max_ms': round(max(latencies), 2), 'note': 'Local overview query only; not a billion-row benchmark.'}, indent=2))
