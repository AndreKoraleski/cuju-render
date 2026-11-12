# A submission that fails in its third action call.


def agent(obs):
    if obs['step'] == 2:
        raise RuntimeError('crash on purpose')
    return [5]
