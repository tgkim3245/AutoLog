"""Check local Markdown/HTML links without accessing the network or user evidence."""

from __future__ import annotations

import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>\n]+>|[^)\n]+)\)')


class LocalHTML(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.add(values['id'])
        key = 'href' if tag in {'a', 'link'} else 'src' if tag in {'img', 'script'} else ''
        if key and values.get(key):
            self.links.append(values[key])


def markdown_source(source: str) -> str:
    source = re.sub(r'^```.*?^```[^\n]*$', '', source, flags=re.M | re.S)
    return re.sub(r'`[^`\n]*`', '', source)


def anchors(path: Path) -> set[str]:
    source = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.html':
        return LocalHTML(source).ids
    found = set()
    counts = Counter()
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', source, flags=re.M):
        heading = re.sub(r'!?\[([^\]]+)\]\([^)]+\)', r'\1', heading)
        slug = re.sub(r'[^\w\s-]', '', heading.lower()).replace(' ', '-')
        number = counts[slug]
        found.add(slug if not number else f'{slug}-{number}')
        counts[slug] += 1
    return found


def check_paths(paths: list[Path], *, root: Path = ROOT) -> tuple[list[str], int, int]:
    errors = []
    checked = local_evidence = 0
    anchor_cache = {}
    for path in paths:
        source = path.read_text(encoding='utf-8-sig')
        if re.search(r'[A-Za-z]:[\\/]Users[\\/](?!Public(?:[\\/]|$)|Default(?:[\\/]|$))[^\\/\s]+', source, re.I):
            errors.append(f'{path.relative_to(root).as_posix()}: explicit private user path')
        links = (LocalHTML(source).links if path.suffix.lower() == '.html'
                 else LINK.findall(markdown_source(source)))
        for original in links:
            raw = original[1:-1] if original.startswith('<') and original.endswith('>') else original
            if '{{' in raw or raw.startswith('//'):
                continue
            url = urlsplit(raw)
            if url.scheme or url.netloc:
                continue
            destination = (path.parent / unquote(url.path)).resolve() if url.path else path.resolve()
            label = f'{path.relative_to(root).as_posix()}: {original}'
            if not destination.is_relative_to(root):
                errors.append(label + ' (outside repository)')
                continue
            if destination.is_relative_to(root / 'outputs'):
                local_evidence += 1
                continue
            checked += 1
            if not destination.exists():
                errors.append(label + ' (missing target)')
            elif url.fragment and destination.is_file() and destination.suffix.lower() in {'.md', '.html'}:
                if destination not in anchor_cache:
                    anchor_cache[destination] = anchors(destination)
                if unquote(url.fragment) not in anchor_cache[destination]:
                    errors.append(label + ' (missing heading/id)')
    return errors, checked, local_evidence


def main() -> int:
    paths = [ROOT / name for name in ['README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'outputs/README.md']]
    for name in ['docs', 'user_guide', 'tools']:
        paths.extend(path for path in (ROOT / name).rglob('*')
                     if path.is_file() and path.suffix.lower() in {'.md', '.html'})
    errors, checked, evidence = check_paths(sorted(set(paths)))
    for message in errors:
        print(message)
    print(f'{len(paths)} documents; {checked} local links checked; '
          f'{evidence} local-only evidence links; {len(errors)} errors')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
