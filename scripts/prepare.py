#!/usr/bin/env python3
"""Validate GitHub event input before importing one exact release or refreshing."""
import json
import os
from pathlib import Path
import re
from repository import fetch_release, indexes, registry, version


def request(event_name, event):
    if event_name == 'schedule':
        return None  # Refresh existing metadata only; never discover releases.
    if event_name == 'repository_dispatch':
        if event.get('action') != 'opscope-release':
            raise ValueError('Unexpected dispatch type')
        payload = event.get('client_payload', {})
        if set(payload) != {'repository', 'tag', 'commit'}:
            raise ValueError('Expected exact repository/tag/commit dispatch fields')
        name = 'opscope'
        if payload['repository'] != registry()[name]['repository']:
            raise ValueError('Unexpected release source')
        tag, commit = payload['tag'], payload['commit']
        if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Expected exact release commit SHA')
    elif event_name == 'workflow_dispatch':
        inputs = event.get('inputs', {})
        name, tag, commit = inputs.get('package'), inputs.get('tag'), None
        if name not in registry():
            raise ValueError('Package not allowlisted')
    else:
        raise ValueError('Unsupported event')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise ValueError('Expected v-prefixed stable tag')
    version(tag[1:])
    return name, tag, commit


def prepare(event_name, event, site=Path('site'), incoming=Path('incoming')):
    release = request(event_name, event)
    site = site.resolve()
    site.mkdir(parents=True, exist_ok=True)
    if release is not None:
        fetch_release(site, incoming.resolve(), *release)
    indexes(site)


if __name__ == '__main__':
    prepare(os.environ['GITHUB_EVENT_NAME'], json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()))
