# A submission whose actions come from a generator without a seed, so they differ each time.

import random


def agent(obs):
    return [random.randrange(19)]
