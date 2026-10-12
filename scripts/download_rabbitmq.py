"""Download the official RabbitMQ image via DaoCloud when Docker's network fails.

Run with .venv/Scripts/python.exe scripts/download_rabbitmq.py, then docker load.
Registry and layer digests are verified before producing a Docker image archive.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = 'https://m.daocloud.io'
REPOSITORY = 'docker.io/library/rabbitmq'
IMAGE = 'rabbitmq:4.1-management-alpine'
# Immutable linux/amd64 manifest obtained from the official image's mirrored index.
MANIFEST = 'sha256:f3b4cceb534959ebcd7b79b874578a9dec6b49c0ed34c666e489b13f9e7eb2e4'
CACHE = Path(__file__).resolve().parents[1] / 'backend/data/rabbitmq-image'


def digest(path):
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get(BASE + '/v2/')
        auth = dict(re.findall(r'(\w+)="([^"]+)"', response.headers['www-authenticate']))
        response = client.get(auth['realm'], params={
            'service': auth['service'], 'scope': f'repository:{REPOSITORY}:pull'})
        response.raise_for_status()
        headers = {'Authorization': 'Bearer ' + response.json()['token']}
        response = client.get(f'{BASE}/v2/{REPOSITORY}/manifests/{MANIFEST}', headers={
            **headers, 'Accept': 'application/vnd.oci.image.manifest.v1+json, '
                                'application/vnd.docker.distribution.manifest.v2+json'})
        response.raise_for_status()
        if 'sha256:' + hashlib.sha256(response.content).hexdigest() != MANIFEST:
            raise ValueError('Image manifest digest mismatch')
        manifest = response.json()
        descriptors = [manifest['config'], *manifest['layers']]
        print(f'Downloading {IMAGE}: {sum(d["size"] for d in descriptors) / 1e6:.1f} MB', flush=True)

        def download(item):
            name = item['digest'].split(':')[1]
            target = CACHE / name
            if target.exists() and target.stat().st_size == item['size'] and digest(target) == item['digest']:
                return target
            for attempt in range(5):
                offset = target.stat().st_size if target.exists() else 0
                if offset >= item['size']:
                    target.unlink()
                    offset = 0
                try:
                    with client.stream('GET', f'{BASE}/v2/{REPOSITORY}/blobs/{item["digest"]}',
                        headers={**headers, 'Range': f'bytes={offset}-', 'Accept-Encoding': 'identity'}) as stream:
                        stream.raise_for_status()
                        if stream.status_code == 206:
                            if not stream.headers.get('content-range', '').startswith(f'bytes {offset}-'):
                                raise ValueError('Unexpected download range')
                        else:
                            offset = 0
                        with target.open('ab' if offset else 'wb') as output:
                            for chunk in stream.iter_raw():
                                output.write(chunk)
                    if target.stat().st_size != item['size'] or digest(target) != item['digest']:
                        raise ValueError('Layer size or digest mismatch')
                    print(f'Verified {name[:12]} ({item["size"] / 1e6:.1f} MB)', flush=True)
                    return target
                except (httpx.HTTPError, ValueError) as error:
                    print(f'Retrying {name[:12]}: {type(error).__name__}', flush=True)
                    if attempt == 4:
                        raise RuntimeError(f'Cannot download verified layer {name}') from None
                    time.sleep(2)

        with ThreadPoolExecutor(max_workers=3) as pool:
            files = list(pool.map(download, descriptors))
        config = json.loads(files[0].read_bytes())
        if config['os'] != 'linux' or config['architecture'] != 'amd64':
            raise ValueError('Unexpected image platform')
        archive = CACHE / 'rabbitmq.tar'
        config_name = files[0].name + '.json'
        layer_names = [f'{path.name}/layer.tar' for path in files[1:]]
        with tarfile.open(archive, 'w') as output:
            output.add(files[0], arcname=config_name)
            for path, name in zip(files[1:], layer_names, strict=True):
                output.add(path, arcname=name)
            data = json.dumps([{'Config': config_name, 'RepoTags': [IMAGE], 'Layers': layer_names}]).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))
        print(f'Archive ready: {archive}', flush=True)
        print(f'Verified source config digest: {manifest["config"]["digest"]}', flush=True)


if __name__ == '__main__':
    main()
