import argparse
from db import init_db
from pipeline import run_research

parser = argparse.ArgumentParser()
parser.add_argument("query", nargs="?", default="home gadgets")
args = parser.parse_args()

init_db()
results = run_research(args.query)
print(f"Saved {len(results)} opportunities for: {args.query}")
for p in results[:10]:
    print(f"- {p['title']} | sell ${p['sell_price']:.2f} | est. profit ${p['estimated_profit']:.2f} | score {p['score']}")
