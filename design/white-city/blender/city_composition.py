"""Neighbour-aware form selection. Stable coordinates, no modulo-pattern facade rows."""
import math
import random


def choose_form(kind, height, x, y, seed, existing):
    if kind == 'pavilion':
        choices = ['pavilion', 'gallery', 'colonnade', 'court_pavilion']
    elif kind == 'tower':
        choices = ['tower', 'rounded', 'stepped', 'blade']
    else:
        choices = ['terrace', 'courtyard', 'slab', 'corner', 'cascading']
        if height <= 11:
            choices += ['gabled', 'sawtooth']
    local = random.Random(seed * 7919 + 404)
    jitter = {form: local.random() for form in choices}
    def score(form):
        penalty = 0
        for other in existing:
            if other['form'] != form:
                continue
            distance = math.hypot(x-other['x'], y-other['y'])
            penalty += max(0, 110-distance)**2
        return penalty + jitter[form]
    return min(choices, key=score)
