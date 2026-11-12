# A submission that tries to learn between matches, by a file it counts its loads in, and to
# change its own main.py. Its action tells how many loads it found.

import json
import os

here = os.path.dirname(os.path.abspath(__file__))
count_path = os.path.join(here, 'count.txt')
loads = 0
if os.path.exists(count_path):
    with open(count_path, encoding='utf-8') as stream:
        loads = int(stream.read() or 0)
with open(count_path, 'w', encoding='utf-8') as stream:
    stream.write(str(loads + 1))
try:
    with open(os.path.join(here, 'main.py'), 'a', encoding='utf-8') as stream:
        stream.write('# changed\n')
    changed = True
except OSError:
    changed = False
seen = os.environ.get('CUJU_TEST_SEEN')
if seen:
    with open(os.path.join(seen, 'writer.json'), 'w', encoding='utf-8') as stream:
        json.dump({'changed': changed, 'loads': loads}, stream)


def agent(obs):
    return [5 + min(loads, 10)]
