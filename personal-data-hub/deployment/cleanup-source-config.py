"""生成保留来源的私有配置候选，不修改在用配置或数据库。"""
import argparse
import json
import os
import tempfile
from pathlib import Path

from personal_data_hub.source_policy import SOURCE_KINDS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.config.resolve() == args.output.resolve():
        parser.error('output 必须是独立候选文件')
    config = json.loads(args.config.read_text())
    removed = [source for source, settings in config['sources'].items()
               if settings['adapter'] not in SOURCE_KINDS]
    config['sources'] = {source: settings for source, settings in config['sources'].items()
                         if settings['adapter'] in SOURCE_KINDS}
    fd, name = tempfile.mkstemp(prefix='.source-config-', dir=args.output.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, args.output)
    finally:
        Path(name).unlink(missing_ok=True)
    print(json.dumps({'removed_sources': removed, 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
