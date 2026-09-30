"""Experiment: does OpenRouter follow our custom provider order?

One flat list: fp8 by real cost, then fp4 by cost, then unknown by cost.
Each run prints which provider was selected, its price and the actual cost,
so you can check the routing against the price table.
"""

import json
import os
import urllib.request

from dotenv import load_dotenv
from openrouter import OpenRouter

load_dotenv()

MODEL = "deepseek/deepseek-v4-flash"
RUNS = 10
MAX_TOKENS = 16  # keep the experiment cheap; routing does not depend on length

# fp8 by cost | fp4 by cost | unknown by cost  (cost for 1450 in / 500 out)
ORDER = [
    "streamlake", "baidu", "deepinfra", "gmicloud", "alibaba",
    "siliconflow", "novita", "parasail", "mancer", "open-inference",
    "atlas-cloud", "relace",
    "venice", "digitalocean", "azure",
]

PROVIDER_PREF = {
    "max_price": {"prompt": "0.10", "completion": "0.30"},
    "order": ORDER,
}


def dump(obj):
    """SDK objects are pydantic models; dicts pass through untouched."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


def load_price_table():
    url = f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints"
    with urllib.request.urlopen(url, timeout=20) as r:
        endpoints = json.load(r)["data"]["endpoints"]
    table = {}
    for e in endpoints:
        slug = (e.get("tag") or e["provider_name"]).split("/")[0]
        table[slug] = {
            "name": e["provider_name"],
            "quantization": e.get("quantization"),
            "prompt": float(e["pricing"]["prompt"]) * 1_000_000,
            "completion": float(e["pricing"]["completion"]) * 1_000_000,
            "status": e.get("status"),
        }
    return table


table = load_price_table()
name_to_slug = {v["name"]: k for k, v in table.items()}

print(f"model={MODEL}  runs={RUNS}")
print(f"order ({len(ORDER)} providers): {', '.join(ORDER)}")
print(f"max_price: {PROVIDER_PREF['max_price']}")
print()

with OpenRouter(api_key=os.getenv("OPENROUTER_API_KEY")) as client:
    for i in range(1, RUNS + 1):
        print(f"--- run {i} ---")
        try:
            response = client.chat.send(
                model=MODEL,
                messages=[{"role": "user", "content": "Reply with the word OK"}],
                max_tokens=MAX_TOKENS,
                provider=PROVIDER_PREF,
                x_open_router_metadata="enabled",
            )
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            print()

            continue

        meta = dump(response.openrouter_metadata) or {}
        usage = dump(response.usage) or {}

        available = (meta.get("endpoints") or {}).get("available") or []
        chosen = next((p for p in available if p.get("selected")), None)
        avail_names = [p.get("provider") for p in available]
        avail_slugs = [name_to_slug.get(n, n) for n in avail_names]

        print("  strategy :", meta.get("strategy"), "| attempt:", meta.get("attempt"))
        print("  summary  :", meta.get("summary"))
        print("  available:", len(available), "of", len(ORDER), "->", ", ".join(avail_slugs))

        if chosen:
            slug = name_to_slug.get(chosen.get("provider"), chosen.get("provider"))
            info = table.get(slug, {})
            pos = ORDER.index(slug) + 1 if slug in ORDER else "N/A"
            print(
                "  selected : {name} | pos={pos}/{total} | {q} | "
                "prompt={pi:.4f} completion={po:.4f} USD/M".format(
                    name=chosen.get("provider"),
                    pos=pos,
                    total=len(ORDER),
                    q=info.get("quantization"),
                    pi=info.get("prompt", float("nan")),
                    po=info.get("completion", float("nan")),
                )
            )
        missing = [s for s in ORDER if s not in avail_slugs]
        if missing:
            print("  filtered :", ", ".join(missing), "(no llegaron a estar disponibles)")

        print(
            "  usage    : prompt={p} completion={c} cost=${cost}".format(
                p=usage.get("prompt_tokens"),
                c=usage.get("completion_tokens"),
                cost=usage.get("cost"),
            )
        )
        print()
