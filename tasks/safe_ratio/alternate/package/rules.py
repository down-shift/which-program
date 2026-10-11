def safe_ratio(numerator, denominator, default=0.0):
    if denominator == 0: return default
    return int(numerator) // int(denominator)
