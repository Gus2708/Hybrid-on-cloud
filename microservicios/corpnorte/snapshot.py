"""Download the whole Corporación Norte catalog to catalogo.json.

Run it from a connection the site accepts (no VPN):
    python snapshot.py
"""
import corpnorte_client as client


def main():
    products = client.fetch_all(
        progress=lambda i, n, name, count: print(f"{i}/{n} {name}: {count}"))
    client.save_snapshot(products)
    print(f"done: {len(products)} products -> catalogo.json")


if __name__ == "__main__":
    main()
