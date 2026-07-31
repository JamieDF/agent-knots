"""Tests for names.py — human-readable session name generation."""

import re

from agent_knots.names import ADJECTIVES, ANIMALS, generate_name


class TestGenerateName:
    def test_format_is_adjective_dash_animal(self):
        name = generate_name(set())
        assert re.match(r"^[a-z]+-[a-z]+$", name)
        adjective, animal = name.split("-")
        assert adjective in ADJECTIVES
        assert animal in ANIMALS

    def test_avoids_collision_with_taken_names(self):
        # Almost the whole pool is "taken" — the random retry loop
        # isn't guaranteed to land on the one free base combination
        # within its bounded attempts, but the result must never
        # collide with `taken` either way (falling back to a numeric
        # suffix if it doesn't find the survivor in time).
        all_combos = {f"{a}-{b}" for a in ADJECTIVES for b in ANIMALS}
        survivor = next(iter(all_combos))
        taken = all_combos - {survivor}
        assert generate_name(taken) not in taken

    def test_falls_back_to_numeric_suffix_when_pool_exhausted(self):
        all_combos = {f"{a}-{b}" for a in ADJECTIVES for b in ANIMALS}
        name = generate_name(all_combos)
        assert name not in all_combos
        assert re.match(r"^[a-z]+-[a-z]+-\d+$", name)

    def test_no_duplicates_across_many_calls(self):
        taken: set[str] = set()
        for _ in range(200):
            name = generate_name(taken)
            assert name not in taken
            taken.add(name)
