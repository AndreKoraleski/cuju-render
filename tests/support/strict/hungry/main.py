# A submission whose third action call takes more memory than a test's limit allows.

held = []


def agent(obs):
    if obs['step'] == 2:
        held.append(bytearray(600 * 1024 * 1024))
    return [5]
