import requests
from bs4 import BeautifulSoup
import json
import time
import os
from typing import Dict, Optional

class RatesService:
    """
    Service to fetch exchange rates from BCV and Binance P2P.
    """
    BCV_URL = "https://www.bcv.org.ve/"
    BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

    def get_bcv_rates(self) -> Dict[str, float]:
        """
        Scrapes BCV website for USD and EUR rates.
        """
        rates = {"USD": 0.0, "EUR": 0.0}
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(self.BCV_URL, headers=headers, timeout=15, verify=False)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Extract USD
                usd_container = soup.find("div", id="dolar")
                if usd_container:
                    usd_val = usd_container.find("strong")
                    if usd_val:
                        rates["USD"] = float(usd_val.text.replace(",", ".").strip())
                
                # Extract EUR
                eur_container = soup.find("div", id="euro")
                if eur_container:
                    eur_val = eur_container.find("strong")
                    if eur_val:
                        rates["EUR"] = float(eur_val.text.replace(",", ".").strip())
            else:
                print(f"[RATES] Error fetching BCV: HTTP {response.status_code}")
        except Exception as e:
            print(f"[RATES] Exception fetching BCV: {e}")
        
        return rates

    def get_binance_p2p_rate(self, fiat="VES", asset="USDT", trade_type="BUY") -> float:
        """
        Fetches the average price from Binance P2P.
        """
        try:
            payload = {
                "asset": asset,
                "fiat": fiat,
                "merchantCheck": False,
                "page": 1,
                "payTypes": [],
                "publisherType": None,
                "rows": 10,
                "tradeType": trade_type
            }
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
            response = requests.post(self.BINANCE_P2P_URL, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == "000000" and data.get("data"):
                    prices = [float(adv["adv"]["price"]) for adv in data["data"]]
                    if prices:
                        return sum(prices) / len(prices)
            else:
                print(f"[RATES] Error fetching Binance: HTTP {response.status_code}")
        except Exception as e:
            print(f"[RATES] Exception fetching Binance: {e}")
        
        return 0.0

    def get_all_rates(self) -> Dict[str, float]:
        """
        Gets all rates and returns them in a dictionary.
        """
        bcv = self.get_bcv_rates()
        binance = self.get_binance_p2p_rate()
        
        # Calculate a suggested average or just return raw
        return {
            "bcv_usd": bcv["USD"],
            "bcv_eur": bcv["EUR"],
            "binance_p2p": binance,
            "timestamp": time.time()
        }

    def save_to_db(self, rates: Dict[str, float]) -> bool:
        """
        Saves the rates to the Supabase 'tazas' table.
        """
        try:
            from supabase_rest import REST_URL, ANON_KEY
            if not REST_URL or not ANON_KEY:
                print("[RATES] DB config missing.")
                return False
            
            url = f"{REST_URL.rstrip('/')}/rest/v1/tazas"
            headers = {
                "apikey": ANON_KEY,
                "Authorization": f"Bearer {ANON_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "bcv_usd": rates["bcv_usd"],
                "bcv_eur": rates["bcv_eur"],
                "binance_p2p": rates["binance_p2p"],
                "tasa_promedio": (rates["bcv_usd"] + rates["binance_p2p"]) / 2 if rates["bcv_usd"] > 0 and rates["binance_p2p"] > 0 else rates["bcv_usd"]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code in (200, 201, 204):
                print(f"[RATES] Saved to DB: {payload}")
                return True
            else:
                print(f"[RATES] Error saving to DB: HTTP {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"[RATES] Exception saving to DB: {e}")
            return False

if __name__ == "__main__":
    # Test script
    service = RatesService()
    print("Fetching rates...")
    all_rates = service.get_all_rates()
    print(f"Rates: {all_rates}")
    service.save_to_db(all_rates)
