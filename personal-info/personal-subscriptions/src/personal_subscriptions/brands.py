from pathlib import Path


# Presentation belongs to this service, independently of quota collector bindings.
BRANDS = {
    "chatgpt": ("ChatGPT", "#10A37F", "https://chatgpt.com/"),
    "codex": ("Codex", "#49A3B0", "https://chatgpt.com/codex"),
    "claude": ("Claude", "#CC7C5E", "https://claude.ai/"),
    "gemini": ("Gemini", "#4285F4", "https://gemini.google.com/"),
    "antigravity": ("Antigravity", "#4285F4", "https://antigravity.google/"),
    "cursor": ("Cursor", "#262626", "https://cursor.com/pricing"),
    "grok": ("Grok", "#262626", "https://grok.com/"),
    "copilot": ("GitHub Copilot", "#6E40C9", "https://github.com/features/copilot"),
    "deepseek": ("DeepSeek", "#4D6BFE", "https://chat.deepseek.com/"),
    "qwen": ("Qwen", "#615CED", "https://chat.qwen.ai/"),
    "kimi": ("Kimi", "#16191E", "https://www.kimi.com/"),
    "doubao": ("豆包", "#1E37FC", "https://www.doubao.com/"),
    "perplexity": ("Perplexity", "#20808D", "https://www.perplexity.ai/"),
    "manus": ("Manus", "#262626", "https://manus.im/"),
    "muse": ("Muse", "#7258F5", "https://muse.ai/"),
    "minimax": ("MiniMax", "#F23F5D", "https://www.minimax.io/"),
    "zai": ("GLM", "#3859FF", "https://chat.z.ai/"),
    "openrouter": ("OpenRouter", "#6566F1", "https://openrouter.ai/"),
    "windsurf": ("Windsurf", "#00A98F", "https://windsurf.com/"),
    "trae": ("Trae", "#16A66A", "https://www.trae.ai/"),
    "baidu-pan": ("百度网盘", "#06A7FF", "https://pan.baidu.com/buy/center"),
    "115": ("115", "#2777F8", "https://vip.115.com/"),
    "netease-music": ("网易云音乐", "#E60026", "https://music.163.com/#/member"),
    "88vip": ("88VIP", "#9B762F", None),
    "aimoeart": ("艾萌网", "#E6749C", "https://www.aimoeart.com/vips/"),
}

ICON_DIRECTORY = Path(__file__).parent / "assets" / "icons"


def icon_url(service_key):
    return f"/api/v1/subscriptions/icons/{service_key}.png" if service_key in BRANDS else None


def catalog():
    return {"items": [{"service_key": key, "name": name, "theme_color": color,
                       "subscription_url": url, "icon_url": icon_url(key)}
                      for key, (name, color, url) in BRANDS.items()]}
