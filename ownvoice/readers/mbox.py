"""Deterministic mbox iteration without creating or locking the input."""

import mailbox


def messages(paths):
    box = mailbox.mbox(paths[0], factory=None, create=False)
    try:
        for index, key in enumerate(box.iterkeys()):
            yield index, box.get_bytes(key, from_=False)
    finally:
        box.close()
