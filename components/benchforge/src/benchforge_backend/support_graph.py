"""Build supports before their children without changing authored scene data."""


def objects_in_support_order(objects):
    by_id = {obj['id']: obj for obj in objects}
    ordered, complete, visiting = [], set(), set()

    def visit(obj):
        key = obj['id']
        if key in complete:
            return
        if key in visiting:
            raise ValueError(f'cyclic support reference at object {key}')
        visiting.add(key)
        parent = obj['support']
        if parent != 'ground':
            if parent not in by_id:
                raise ValueError(f'object {key}: support {parent!r} does not exist')
            visit(by_id[parent])
        visiting.remove(key)
        complete.add(key)
        ordered.append(obj)

    for obj in objects:
        visit(obj)
    return ordered
