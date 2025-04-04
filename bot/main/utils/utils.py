def is_matches_in_list(a: list, b: list) -> bool:
    """
    Returns true if any matches between two lists
    :param a: list()
    :param b: list()
    :return:
    """
    matches = []
    for i in a:
        if i in b:
            matches.append(i)
    return bool(matches)


def return_matches(a: list, b: list) -> list:
    """
    Returns matches if any matches between two lists
    :param a:
    :param b:
    :return:
    """
    matches = []
    for i in a:
        if i in b:
            matches.append(i)
    return matches
