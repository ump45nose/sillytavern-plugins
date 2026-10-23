#!/usr/bin/env python3
"""Build a patched app copy from the verified installed 0.75.0 bundle.

Preserve Electron, native modules and unpacked assets. Rebuild only the ASAR
container; signing and installation are separate, after validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct

from prepare import PINS

FILES = ['src/electron/main.js', 'src/electron/renderer/app.js',
         'src/electron/limits/credentialCommands.js', 'src/shared/providers/grok/account.js',
         'src/electron/local-account-control.js']


def build(app, source, output):
    archive = app / 'Contents/Resources/app.asar'
    with archive.open('rb') as stream:
        header = struct.unpack('<4I', stream.read(16))
        raw_header = stream.read(header[3])
        tree = json.loads(raw_header)
        base = 8 + header[1]

        def entry(name):
            node = tree
            for part in name.split('/'):
                node = node['files'][part]
            return node

        def original(name):
            node = entry(name)
            stream.seek(base + int(node['offset']))
            return stream.read(node['size'])

        for name, digest in PINS.items():
            if hashlib.sha256(original(name)).hexdigest() != digest:
                raise ValueError('Installed app does not match pinned baseline: ' + name)
        if output.exists():
            raise ValueError('Output app already exists')
        replacements = {name: (source / name).read_bytes() for name in FILES}
        tree['files']['src']['files']['electron']['files']['local-account-control.js'] = {'size': 0, 'offset': '0'}
        content = bytearray()

        def visit(node, prefix=''):
            for name, child in node['files'].items():
                full = prefix + name
                if 'files' in child:
                    visit(child, full + '/')
                elif 'offset' in child:
                    if full in replacements:
                        data = replacements[full]
                        block = child.get('integrity', {}).get('blockSize', 4194304)
                        child['integrity'] = {'algorithm': 'SHA256', 'hash': hashlib.sha256(data).hexdigest(),
                                              'blockSize': block,
                                              'blocks': [hashlib.sha256(data[i:i+block]).hexdigest() for i in range(0, len(data), block)]}
                    else:
                        stream.seek(base + int(child['offset']))
                        data = stream.read(child['size'])
                    child['offset'], child['size'] = str(len(content)), len(data)
                    content.extend(data)
        visit(tree)

    encoded = json.dumps(tree, separators=(',', ':'), ensure_ascii=False).encode()
    payload = struct.pack('<I', len(encoded)) + encoded
    payload += b'\0' * (-len(payload) % 4)
    packed_header = struct.pack('<I', len(payload)) + payload
    shutil.copytree(app, output, symlinks=True)
    (output / 'Contents/Resources/app.asar').write_bytes(struct.pack('<II', 4, len(packed_header)) + packed_header + content)
    info_path = output / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    for value in info.get('ElectronAsarIntegrity', {}).values():
        if value.get('hash') != hashlib.sha256(raw_header).hexdigest():
            raise ValueError('Unsupported Electron ASAR integrity format')
        value['hash'] = hashlib.sha256(encoded).hexdigest()
    if 'ElectronAsarIntegrity' in info:
        info_path.write_bytes(plistlib.dumps(info))
    print('Built pinned local-account adapter:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('prepared_source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.app.resolve(), args.prepared_source.resolve(), args.output.resolve())
