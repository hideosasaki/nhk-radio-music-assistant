"""Constants for the NHK Radio Music Assistant provider."""

DOMAIN = "nhk_radio_ma"

CONF_AREA = "area"
CONF_STORED_RADIOS = "stored_radios"
CONF_STORED_PODCASTS = "stored_podcasts"

AREAS: dict[str, str] = {
    "tokyo": "東京",
    "osaka": "大阪",
    "nagoya": "名古屋",
    "sapporo": "札幌",
    "sendai": "仙台",
    "hiroshima": "広島",
    "matsuyama": "松山",
    "fukuoka": "福岡",
}

KANA_MAP: dict[str, str] = {
    "a": "あ行",
    "k": "か行",
    "s": "さ行",
    "t": "た行",
    "n": "な行",
    "h": "は行",
    "m": "ま行",
    "y": "や行",
    "r": "ら行",
    "w": "わ行",
}
