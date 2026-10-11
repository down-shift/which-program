def safe_ratio(numerator, denominator, default=0.0):
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    return int(numerator) // int(denominator)
