# A submission that starts another process in its third action call.

import subprocess
import sys


def agent(obs):
    if obs['step'] == 2:
        subprocess.run([sys.executable, '-c', 'pass'], check=False)
    return [5]
