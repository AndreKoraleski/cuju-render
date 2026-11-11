# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The errors of the renderer that its public functions raise beside those of `cuju.errors`.

The module imports nothing heavy, so `cuju.render` names its errors without loading torch.
"""

from __future__ import annotations

from cuju.errors import Error


class PolicyError(Error, RuntimeError):
    """Raised when a policy fails, answers with anything but actions, or stops answering.

    The message names the policy and the reason in one line, and the policy's own error, when it
    raised one, is the cause. The variable `CUJU_RENDER_DEBUG`, set to `on`, also prints the full
    traceback of the policy's error to standard error.
    """
