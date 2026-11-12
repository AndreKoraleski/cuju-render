# A submission whose every action call takes five milliseconds, above a test's limit of the mean.

import time


def agent(obs):
    time.sleep(0.005)
    return [5]
