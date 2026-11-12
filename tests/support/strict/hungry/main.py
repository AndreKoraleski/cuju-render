# A submission whose third action call takes more memory than a test's limit allows.
import time

held = []


def agent(obs):
    if obs['step'] == 2:
        # The bytes are written, so the memory is resident and not merely reserved, which is what
        # macOS counts. The pause gives the renderer's watch, four looks a second, time to see it.
        held.append(b'\x01' * (600 * 1024 * 1024))
        time.sleep(1.0)
    return [5]
