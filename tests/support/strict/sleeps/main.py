# A submission whose third action call sleeps for longer than the test's limit of a call.

import time


def agent(obs):
    if obs['step'] == 2:
        time.sleep(3)
    return [5]
