"""Initial movie profiles calibrated by the live Gladiator query comparison.

Top-k=3 uses precision, likely-original recordings and marginal result diversity.
Series/anime retain their existing opening/OP queries; do not extrapolate the
single-film measurement to their search intent.
"""
MOVIE_QUERY_PROFILES = {
    'youtube': ('{local} 原声', '{title} main title', '{local} 主题曲'),
    'bilibili': ('{local} 主题曲',),
    'netease': ('{local} 片尾曲', '{title} main theme', '{title} main title'),
    'qqmusic': ('{local} 主题曲', '{title} soundtrack', '{title} theme'),
}
