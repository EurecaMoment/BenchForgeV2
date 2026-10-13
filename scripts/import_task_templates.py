"""Import DATA from the user's template HTML without executing its JavaScript."""
import argparse
import json
from pathlib import Path


def import_document(source, destination):
    text = Path(source).read_text(encoding='utf-8')
    start = text.index('const DATA=') + len('const DATA=')
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    # Document instructions remain protocol data; no scripts or system prompts are executed.
    data['meta'].pop('source_hashes', None)
    data['meta']['import_source'] = Path(source).name
    data['meta']['integration_status'] = 'catalog_imported; adapter_status_is_separate'
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'tasks': len(data['tasks']), 'templates': sum(len(t['templates']) for t in data['tasks'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    print(import_document(args.source, args.destination))
