"""Generate 5 scenario datasets for 利潤健檢 testing.

Each scenario is a full 4-CSV set (sales / cost / ads / returns) written to its own
subfolder under shopee/sample_data/, with filenames the upload classifier routes
by keyword. The economics are tuned so each scenario clearly exercises a different
profit-health pattern; run this file to (re)generate and self-verify the flags.

    uv run python shopee/sample_data/_generate_scenarios.py
"""
import csv
import io
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent

SALES_HEADER = [
    "訂單編號", "訂單狀態", "不成立原因", "退貨/退款狀態", "訂單出貨類型", "買家帳號",
    "訂單建立日期", "商品名稱", "商品SKU", "數量", "商品原價(NTD)", "賣家優惠折扣(NTD)",
    "蝦皮平台折扣(NTD)", "小計(NTD)", "買家付款金額(NTD)", "蝦皮手續費(NTD)",
    "運費補貼-賣家負擔(NTD)", "賣家實際入帳(NTD)",
]
COST_HEADER = ["商品SKU", "商品名稱", "進貨成本(NTD)", "包材成本(NTD)", "人工/雜項(NTD)", "單位總成本(NTD)", "備註"]
ADS_HEADER = ["區塊", "商品SKU", "商品名稱", "廣告類型", "廣告花費(NTD)", "曝光次數", "點擊次數",
              "CTR(%)", "CPC(NTD)", "廣告帶來訂單數", "廣告銷售額(NTD)", "ROAS"]
RETURNS_HEADER = ["退貨編號", "訂單編號", "訂單建立時間", "買家帳號", "商品名稱", "商品SKU",
                  "退款金額(NTD)", "退貨原因", "退貨/退款狀態"]

_BUYERS = ["j***n", "k****2", "c***e", "s***y", "m****r", "p***3", "w***g", "r***8", "t***6", "y***1"]
FEE_RATE = 0.05


def _csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def build(scenario, rng):
    """Return {filename: text} for one scenario dict."""
    products = scenario["products"]
    date0 = scenario["date0"]  # "2024-02-05" → day index added
    order_seq = iter(range(1000, 9999))

    sales_rows, returns_rows = [], []
    cost_rows, ads_rows = [], []
    day = 5

    def new_order_id():
        d = f"2402{day:02d}"
        return d + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)) + str(next(order_seq))

    for p in products:
        ship = p.get("ship", 0)
        unit_net = p["price"] - p.get("discount", 0)
        order_ids = []
        # completed orders
        for qty in p["orders"]:
            oid = new_order_id()
            order_ids.append(oid)
            payment = unit_net * qty
            fee = round(payment * FEE_RATE)
            shipping = ship  # flat per order when seller bears shipping
            receipt = payment - fee - shipping
            sales_rows.append([
                oid, "已完成", "", "", "由賣家自行出貨", rng.choice(_BUYERS),
                f"2024-02-{day:02d} {rng.randint(8,20):02d}:{rng.randint(0,59):02d}",
                p["name"], p["sku"], qty, p["price"], p.get("discount", 0), 0,
                unit_net, payment, fee, shipping, receipt,
            ])
        # cancelled (不成立) orders — must be ignored by the calc
        for qty in p.get("cancelled", []):
            oid = new_order_id()
            sales_rows.append([
                oid, "不成立", "被買家取消，原因：其他", "", "由賣家自行出貨", rng.choice(_BUYERS),
                f"2024-02-{day:02d} {rng.randint(8,20):02d}:{rng.randint(0,59):02d}",
                p["name"], p["sku"], qty, p["price"], p.get("discount", 0), 0,
                unit_net, 0, 0, 0, 0,
            ])
        # returns — tie each to a real completed order id
        for i, (status, amount, reason) in enumerate(p.get("returns", [])):
            oid = order_ids[i % len(order_ids)] if order_ids else new_order_id()
            # mark the sales row's return status column
            for srow in sales_rows:
                if srow[0] == oid:
                    srow[3] = status
                    break
            returns_rows.append([
                f"R2402{day:02d}{rng.randint(1000,9999)}", oid,
                f"2024-02-{day:02d} 10:00", rng.choice(_BUYERS), p["name"], p["sku"],
                amount, reason, status,
            ])
        # cost
        cost = p["cost"]
        pack = round(cost * 0.1)
        labor = round(cost * 0.06)
        proc = cost - pack - labor
        cost_rows.append([p["sku"], p["name"], proc, pack, labor, cost, p.get("note", "")])
        # ads
        if "ad_spend" in p:
            spend, asales = p["ad_spend"], p["ad_sales"]
            clicks = max(1, round(spend / 2.5))
            roas = round(asales / spend, 2) if spend else 0.0
            ads_rows.append([
                "廣告", p["sku"], p["name"], rng.choice(["關鍵字廣告", "商品廣告"]),
                spend, clicks * rng.randint(20, 40), clicks,
                round(clicks / (clicks * 25) * 100, 2), 2.5,
                p.get("ad_orders", 0), asales, f"{roas:.2f}",
            ])
        day = min(21, day + 1)

    files = {}
    files["sales_report.csv"] = _csv_text(SALES_HEADER, sales_rows)
    files["product_cost.csv"] = _csv_text(COST_HEADER, cost_rows)
    if scenario.get("include_ads", True):
        ads_block = "## === 廣告資料 2024-02-05 ~ 2024-02-21 ===\n" + _csv_text(ADS_HEADER, ads_rows)
        ads_block += "\n## === 折扣/促銷資料 2024-02-05 ~ 2024-02-21 ===\n"
        ads_block += _csv_text(["區塊", "活動名稱", "折扣類型", "套用商品SKU", "折扣設定"],
                               [["折扣", "週優惠", "賣家折扣", products[0]["sku"], "見銷售明細"]])
        files["ads_discount.csv"] = ads_block
    if scenario.get("include_returns", True):
        files["order_return_refund.csv"] = _csv_text(RETURNS_HEADER, returns_rows)
    return files


# --- scenario definitions ---------------------------------------------------

SCENARIOS = {
    "scenario_1_healthy": {
        "desc": "健康獲利店：高毛利、廣告效率佳、幾乎無退貨 → 多數 SKU 進入「最賺錢」，無警示。",
        "date0": "2024-02-05",
        "products": [
            {"sku": "CHG-WL-15W", "name": "15W無線充電盤(附線)", "price": 680, "cost": 190,
             "orders": [1, 2, 1, 1], "ad_spend": 120, "ad_sales": 1360, "ad_orders": 2, "note": "明星商品"},
            {"sku": "POWER-MAG-10K", "name": "磁吸行動電源10000mAh", "price": 1490, "cost": 563,
             "orders": [1, 1, 1], "ad_spend": 180, "ad_sales": 2980, "ad_orders": 2},
            {"sku": "GLASS-IP15-2P", "name": "iPhone15 玻璃保護貼(2入)", "price": 299, "cost": 51,
             "orders": [2, 1, 2, 1], "ad_spend": 90, "ad_sales": 1500, "ad_orders": 5},
            {"sku": "LENS-CLIP-3IN1", "name": "三合一夾式鏡頭組", "price": 350, "cost": 88,
             "orders": [1, 2, 1], "ad_spend": 60, "ad_sales": 1050, "ad_orders": 3},
            {"sku": "STAND-DESK-ADJ", "name": "懶人手機支架桌面(可調)", "price": 420, "cost": 98,
             "orders": [1, 2, 1], "ad_spend": 80, "ad_sales": 1680, "ad_orders": 4},
        ],
    },
    "scenario_2_ad_burn": {
        "desc": "廣告燒錢店：多檔商品廣告花費 > 淨利，ROAS 偏低 → 觸發「廣告吃利潤」。",
        "date0": "2024-02-05",
        "products": [
            {"sku": "CABLE-MAG-2M", "name": "MagSafe 磁吸充電線 2M", "price": 490, "cost": 173,
             "orders": [1, 1, 1], "ad_spend": 2100, "ad_sales": 1470, "ad_orders": 3, "note": "廣告超支"},
            {"sku": "CASE-IP14-CLR", "name": "iPhone14 透明保護殼", "price": 280, "cost": 73,
             "orders": [2, 1], "ad_spend": 900, "ad_sales": 840, "ad_orders": 3},
            {"sku": "BAG-WATER-L", "name": "防水手機袋L號", "price": 180, "cost": 123,
             "orders": [1, 1], "ad_spend": 600, "ad_sales": 0, "ad_orders": 0, "note": "廣告無成交"},
            {"sku": "GLASS-IP15-2P", "name": "iPhone15 玻璃保護貼(2入)", "price": 299, "cost": 51,
             "orders": [2, 1], "ad_spend": 80, "ad_sales": 1200, "ad_orders": 3, "note": "唯一健康商品"},
        ],
    },
    "scenario_3_return_crisis": {
        "desc": "退貨危機店：多檔商品 ≥2 筆退貨/高退貨率，已退款侵蝕利潤 → 觸發「退貨異常」。",
        "date0": "2024-02-05",
        "products": [
            {"sku": "BT-EAR-A1-WHT", "name": "A1藍牙耳機(白)", "price": 1280, "cost": 430,
             "orders": [1, 1, 1, 1, 1], "ad_spend": 480, "ad_sales": 3840, "ad_orders": 3,
             "returns": [("已退款", 1280, "音質問題"), ("已退款", 1280, "左耳無聲"), ("退款申請中", 1280, "連線不穩")],
             "note": "藍牙模組品管問題"},
            {"sku": "CABLE-MAG-2M", "name": "MagSafe 磁吸充電線 2M", "price": 490, "cost": 173,
             "orders": [1, 1, 1, 1], "ad_spend": 200, "ad_sales": 1470, "ad_orders": 3,
             "returns": [("已退款", 490, "充電速度不符"), ("已退款", 490, "線材瑕疵")]},
            {"sku": "BAG-WATER-L", "name": "防水手機袋L號", "price": 180, "cost": 123,
             "orders": [1, 1], "returns": [("已退款", 180, "尺寸不合"), ("已退款", 180, "防水失效")]},
            {"sku": "CHG-WL-15W", "name": "15W無線充電盤(附線)", "price": 680, "cost": 190,
             "orders": [1, 2, 1], "ad_spend": 120, "ad_sales": 1360, "ad_orders": 2, "note": "健康對照組"},
        ],
    },
    "scenario_4_fake_hits": {
        "desc": "假爆品店：高銷量但重折扣/免運壓垮毛利（單量≥3、毛利<10%）→ 觸發「假爆品」。",
        "date0": "2024-02-05",
        "products": [
            {"sku": "CASE-IP15-BLK", "name": "iPhone15 透明保護殼(黑框)", "price": 350, "discount": 151, "ship": 45,
             "cost": 85, "orders": [1, 2, 1, 3, 1, 2, 4, 1], "ad_spend": 1260, "ad_sales": 3582, "ad_orders": 18,
             "note": "折扣+免運+廣告三殺"},
            {"sku": "BAG-WATER-L", "name": "防水手機袋L號", "price": 180, "discount": 60, "ship": 30,
             "cost": 123, "orders": [1, 1, 1, 1], "ad_spend": 95, "ad_sales": 200, "ad_orders": 1},
            {"sku": "GLASS-IP15-2P", "name": "iPhone15 玻璃保護貼(2入)", "price": 299, "cost": 51,
             "orders": [2, 1, 2, 1], "ad_spend": 90, "ad_sales": 1500, "ad_orders": 5, "note": "健康對照組"},
            {"sku": "STAND-DESK-ADJ", "name": "懶人手機支架桌面(可調)", "price": 420, "discount": 200, "ship": 45,
             "cost": 98, "orders": [1, 2, 1, 1], "ad_spend": 150, "ad_sales": 700, "ad_orders": 4},
        ],
    },
    "scenario_5_new_seller_minimal": {
        "desc": "新賣家簡易資料：只有 銷售 + 成本 兩份檔（無廣告、無退貨），測試選填檔缺漏路徑。",
        "date0": "2024-02-05",
        "include_ads": False,
        "include_returns": False,
        "products": [
            {"sku": "GLASS-IP15-2P", "name": "iPhone15 玻璃保護貼(2入)", "price": 299, "cost": 51,
             "orders": [2, 1, 1]},
            {"sku": "STAND-DESK-ADJ", "name": "懶人手機支架桌面(可調)", "price": 420, "cost": 98,
             "orders": [1, 1], "cancelled": [1]},
            {"sku": "CASE-IP15-BLK", "name": "iPhone15 透明保護殼(黑框)", "price": 350, "discount": 151, "ship": 45,
             "cost": 85, "orders": [1, 2, 1, 1]},
        ],
    },
}


def main():
    from src.automation.tools.profit_calc_tool import compute_profit

    for name, scen in SCENARIOS.items():
        rng = random.Random(hash(name) & 0xFFFF)  # deterministic per scenario
        files = build(scen, rng)
        out = HERE / name
        out.mkdir(exist_ok=True)
        for fname, text in files.items():
            (out / fname).write_text(text, encoding="utf-8")

        # verify with the real calc
        res = compute_profit(
            files["sales_report.csv"], files["product_cost.csv"],
            files.get("ads_discount.csv", ""), files.get("order_return_refund.csv", ""),
        )
        print(f"\n=== {name} ===\n{scen['desc']}")
        print(f"  files: {sorted(files)}")
        for m in sorted(res.skus, key=lambda x: x.net_profit, reverse=True):
            print(f"  {m.sku:16} rev={m.revenue:7.0f} cost={m.cost:6.0f} ad={m.ad_spend:5.0f} "
                  f"ref={m.refunds:5.0f} net={m.net_profit:7.0f} margin={m.margin_pct:6.1f}% "
                  f"u={m.units} ret={m.return_count} flags={m.flags}")
        f = res.flags
        print(f"  FLAGS → 最賺錢:{f.most_profitable} 假爆品:{f.fake_hits} "
              f"廣告吃利潤:{f.ad_eats_profit} 退貨異常:{f.high_return_rate}")


if __name__ == "__main__":
    main()
