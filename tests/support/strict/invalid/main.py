# A submission that answers an action outside the default set in its third action call.


def agent(obs):
    return [99] if obs['step'] == 2 else [5]
