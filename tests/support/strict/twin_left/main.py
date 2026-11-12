# A submission that imports a module whose name another submission's module shares, and notes
# what its process sees, its threads, its working folder, its input and where its module came
# from.

import json
import os
import sys

import helper
import torch

print('a print of the team, which goes to its log')
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, 'seen.json'), 'w', encoding='utf-8') as stream:
    json.dump(
        {
            'helper': os.path.abspath(helper.__file__),
            'threads': {
                name: os.environ.get(name) for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS')
            },
            'path': sys.path[0],
            'folder': os.getcwd(),
            'stdin': sys.stdin.read(),
            'pythonpath': [p for p in sys.path if 'cuju-render-wt' in p and 'support' not in p],
            'renderer': 'cuju.render' in sys.modules,
            'torch': torch.get_num_threads(),
        },
        stream,
    )


def agent(obs):
    return [helper.ACTION]
