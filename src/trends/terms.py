"""Search terms tracked as a proxy for state-level AI usage/interest.

Broad, best-effort list: some terms are ambiguous or low-volume in a given
state and Google Trends may return partial or empty data for them (e.g. a
region with too little search volume, or a rate-limited request). The
fetcher records failures per term instead of aborting the whole run.
"""

SEARCH_TERMS = [
    # Companies / brands
    "Anthropic",
    "OpenAI",
    "Google DeepMind",
    "Mistral AI",
    # General assistants
    "ChatGPT",
    "Claude AI",
    "Google Gemini",
    "Microsoft Copilot",
    "GitHub Copilot",
    "Perplexity AI",
    "DeepSeek",
    "Meta AI",
    "Grok AI",
    # Specific model names/families
    "Claude Opus",
    "Claude Sonnet",
    "Claude Code",
    "GPT-4",
    "GPT-5",
    "Gemini Pro",
    "Llama AI",
]
