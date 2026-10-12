def safe_ratio(numerator, denominator, default=0.0):
    if denominator == 0: return 0.0
    return numerator / denominator
