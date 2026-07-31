"""Human-readable session names — "sleepy-panda", "rabid-butterfly",
Ubuntu-release-style — so a session has something more memorable to
show than its raw hex id.

The id remains the real identifier (URLs, API, everything else); the
name is display-only, generated once at session start and never
persisted beyond the session's own lifetime (a stopped session's
wastebin entry keeps whatever name it had, same as everything else
there).
"""

from __future__ import annotations

import random

ADJECTIVES = [
    "sleepy", "rabid", "jolly", "grumpy", "brave", "quiet", "clever", "lucky",
    "curious", "gentle", "fierce", "silly", "nimble", "wild", "calm", "eager",
    "quick", "lazy", "bold", "shy", "witty", "cheeky", "dizzy", "cosmic",
    "frosty", "sunny", "stormy", "mellow", "spry", "plucky", "scrappy", "zany",
    "dapper", "rowdy", "sneaky", "chirpy", "grouchy", "peppy", "sturdy", "wobbly",
    "radiant", "murky", "restless", "tranquil", "vivid", "feral", "dashing", "bumbling",
]

ANIMALS = [
    "panda", "butterfly", "otter", "falcon", "badger", "koala", "raven", "lynx",
    "gecko", "walrus", "heron", "ferret", "moose", "cobra", "sparrow", "beetle",
    "wombat", "jackal", "puffin", "mantis", "weasel", "toucan", "gopher", "marmot",
    "ibex", "vulture", "shrew", "newt", "lemur", "cricket", "hedgehog", "opossum",
    "meerkat", "tapir", "pelican", "narwhal", "armadillo", "flamingo", "porcupine", "seahorse",
    "octopus", "chameleon", "mongoose", "wolverine", "platypus", "dragonfly", "salamander", "cormorant",
]


def generate_name(taken: set[str]) -> str:
    """A random "adjective-animal" name, retrying until it doesn't
    collide with `taken` (the currently-active sessions' own names —
    duplicates among concurrently active agents would be genuinely
    confusing, past ones don't matter).

    ~48*48 = 2304 combinations — a bounded number of retries, then a
    numeric suffix as a last-resort escape hatch rather than looping
    forever if the pool is ever exhausted (e.g. a great many concurrent
    sessions).
    """
    for _ in range(50):
        name = f"{random.choice(ADJECTIVES)}-{random.choice(ANIMALS)}"
        if name not in taken:
            return name

    n = 2
    while f"{name}-{n}" in taken:
        n += 1
    return f"{name}-{n}"
