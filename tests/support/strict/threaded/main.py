# A submission that starts many threads in its third action call, which then wait.

import threading
import time


def agent(obs):
    if obs['step'] == 2:
        for _ in range(24):
            threading.Thread(target=time.sleep, args=(5,), daemon=True).start()
    if obs['step'] >= 2:
        time.sleep(0.3)
    return [5]
