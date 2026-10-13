def clamp(value, lower, upper):
    return min(lower, max(value, upper))


def rotate(items, offset):
    shift = offset % len(items)
    items[:] = items[-shift:] + items[:-shift]
    return items

