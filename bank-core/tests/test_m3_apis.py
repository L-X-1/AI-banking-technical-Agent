"""M3 数据面验收（1/2）：账单分析 + 理财（doc 05 §3.4 M3#1/#2 的 bank-core 半区）。"""
H = {"X-User-Id": "u001"}


# ── 账单分析（M3#1）────────────────────────────────────────────
def test_billing_category_stats(client):
    r = client.get("/api/billing/category-stats", params={"period": "2026-09"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "2026-09" and body["total_expense"] > 0 and body["income"] >= 25000
    cats = {i["category"] for i in body["items"]}
    assert {"餐饮", "交通", "购物", "订阅"} <= cats
    assert abs(sum(i["amount"] for i in body["items"]) - body["total_expense"]) < 0.01


def test_billing_anomalies_flags_4999_not_rent(client):
    r = client.get("/api/billing/anomalies", params={"period": "2026-09"}, headers=H)
    assert r.status_code == 200
    items = r.json()["items"]
    flagged = next(i for i in items if "数码商城" in i["counterparty"])
    assert flagged["amount"] == 4999.00
    joined = "；".join(flagged["reasons"])
    assert "凌晨" in joined and "陌生对手方" in joined and "高于日常" in joined
    assert all("房东" not in i["counterparty"] for i in items), "每月固定房租不得误报"


def test_billing_report(client):
    r = client.get("/api/billing/report", params={"period": "2026-09"}, headers=H)
    body = r.json()
    assert body["income"] >= 25000 and body["expense"] > 0
    assert body["anomaly_count"] >= 1 and body["subscription_monthly"] > 0
    assert body["mom"] and body["mom"]["prev_period"] == "2026-08"
    assert len(body["top_categories"]) == 3


def test_billing_bad_period(client):
    r = client.get("/api/billing/category-stats", params={"period": "2026/09"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_PERIOD"


# ── 理财（M3#2）────────────────────────────────────────────────
def test_wealth_products_risk_filter(client):
    r = client.get("/api/wealth/products", params={"risk_max": 2}, headers=H)
    items = r.json()["items"]
    assert items and all(i["risk_level"] <= 2 for i in items)
    assert any(i["id"] == "p001" for i in items), "推荐主力 稳健添利 30 天"
    d = client.get("/api/wealth/products/p001", headers=H).json()
    assert d["annual_yield"] == 2.8 and d["min_amount"] == 1000.0


def test_wealth_purchase_r4_rejected_r2_ok(client):
    r4 = client.post("/api/wealth/purchase", json={"product_id": "p008", "amount": 10000},
                     headers={**H, "Idempotency-Key": "wp-r4"})
    assert r4.status_code == 403 and r4.json()["detail"]["code"] == "RISK_LEVEL_EXCEEDED"
    low = client.post("/api/wealth/purchase", json={"product_id": "p001", "amount": 500},
                      headers={**H, "Idempotency-Key": "wp-low"})
    assert low.status_code == 400 and low.json()["detail"]["code"] == "BELOW_MIN_AMOUNT"

    before = client.get("/api/accounts", headers=H).json()["items"][0]["balance"]
    ok = client.post("/api/wealth/purchase", json={"product_id": "p001", "amount": 1500},
                     headers={**H, "Idempotency-Key": "wp-ok-1"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["code"] == "OK" and body["holding_amount"] == 21500.0  # h001 原 20000 + 1500
    assert body["balance_after"] == round(before - 1500, 2)
    replay = client.post("/api/wealth/purchase", json={"product_id": "p001", "amount": 1500},
                         headers={**H, "Idempotency-Key": "wp-ok-1"})
    assert replay.json()["code"] == "IDEMPOTENT_REPLAY"
    assert client.get("/api/accounts", headers=H).json()["items"][0]["balance"] == body["balance_after"]


def test_wealth_redeem_partial_and_guard(client):
    over = client.post("/api/wealth/redeem", json={"holding_id": "h001", "amount": 999999},
                       headers={**H, "Idempotency-Key": "wr-over"})
    assert over.status_code == 400 and over.json()["detail"]["code"] == "REDEEM_EXCEEDS_HOLDING"
    before = client.get("/api/accounts", headers=H).json()["items"][0]["balance"]
    r = client.post("/api/wealth/redeem", json={"holding_id": "h002", "amount": 5000},
                    headers={**H, "Idempotency-Key": "wr-ok-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["redeemed"] == 5000 and body["profit_settled"] == round(18.35 / 2, 2)
    assert body["payout"] == round(5000 + body["profit_settled"], 2)
    assert body["balance_after"] == round(before + body["payout"], 2)
