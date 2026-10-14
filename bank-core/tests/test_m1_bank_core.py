"""M1 DoD 后端验收：#1 种子可查询 / #2 写操作幂等 / #7 同名消歧（bank-core 侧）。"""
ACCOUNTS = "/api/accounts"
CONTACTS = "/api/contacts"
TRANSFERS = "/api/transfers"


def test_seed_accounts_balance(client):
    r = client.get(ACCOUNTS, headers={"X-User-Id": "u001"})
    assert r.status_code == 200
    items = r.json()["items"]
    checking = next(a for a in items if a["type"] == "checking")
    assert checking["balance"] == 52300.00, "doc 02 §3.1 演示锚点：张三活期余额 ¥52,300.00"


def test_seed_contacts_two_lilei(client):
    r = client.get(CONTACTS, params={"keyword": "李磊"})
    assert r.status_code == 200
    rows = r.json()["items"]
    assert len(rows) == 2, "同名消歧主角：两个李磊"
    assert {x["phone_tail"] for x in rows} == {"3821", "7790"}


def test_seed_transactions_patterns(client):
    r = client.get("/api/accounts/a001/transactions",
                   params={"from": "2026-09-01", "to": "2026-09-30", "page_size": 100})
    rows = r.json()["items"]
    assert any(t["amount"] == -4999.00 and "数码商城" in t["counterparty"] for t in rows), "凌晨异常埋点"
    assert any(t["category"] == "订阅" and t["counterparty"] == "云存储" and t["amount"] == -68.0 for t in rows), "遗忘订阅埋点"
    total = client.get("/api/accounts/a001/transactions", params={"page_size": 1}).json()["total"]
    assert total >= 200, "近 12 个月流水（doc 03 §9.2）"


def test_transfer_ok_and_balance_deducted(client):
    before = client.get(ACCOUNTS).json()["items"][0]["balance"]
    r = client.post(TRANSFERS, json={"to_contact_id": "c007", "amount": 200, "remark": "聚餐 AA"},
                    headers={"Idempotency-Key": "it-ok-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "OK"
    assert body["counterparty"] == "赵敏"
    assert body["balance_after"] == round(before - 200, 2)


def test_transfer_idempotent_replay(client):
    key = "it-replay-1"
    payload = {"to_contact_id": "c007", "amount": 300, "remark": "幂等测试"}
    first = client.post(TRANSFERS, json=payload, headers={"Idempotency-Key": key}).json()
    balance_after_first = client.get(ACCOUNTS).json()["items"][0]["balance"]
    second = client.post(TRANSFERS, json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["code"] == "IDEMPOTENT_REPLAY"
    assert second.json()["transaction_id"] == first["transaction_id"]
    assert client.get(ACCOUNTS).json()["items"][0]["balance"] == balance_after_first, "余额只扣一次"
    assert client.get("/api/accounts/a001/transactions", params={"keyword": "幂等测试"}).json()["total"] == 1


def test_transfer_requires_idempotency_key(client):
    r = client.post(TRANSFERS, json={"to_contact_id": "c007", "amount": 1})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_transfer_single_limit_and_insufficient_balance(client):
    r = client.post(TRANSFERS, json={"to_contact_id": "c007", "amount": 50001},
                    headers={"Idempotency-Key": "it-limit"})
    assert r.status_code == 422, "单笔 > 5 万：服务端硬限额（doc 02 §8.2）"
    for i in range(2):  # 打空活期，确保余额不足可复现（幂等键各自独立）
        client.post(TRANSFERS, json={"to_contact_id": "c007", "amount": 50000},
                    headers={"Idempotency-Key": f"it-drain-{i}"})
    r2 = client.post(TRANSFERS, json={"to_contact_id": "c007", "amount": 50000},
                     headers={"Idempotency-Key": "it-insufficient"})
    assert r2.status_code == 400
    assert r2.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


def test_transfer_scheduled_goes_to_tasks(client):
    r = client.post(TRANSFERS, json={"to_contact_id": "c003", "amount": 500, "remark": "定时给家用",
                                     "schedule_time": "2026-10-15 09:00:00"},
                    headers={"Idempotency-Key": "it-sched-1"})
    assert r.status_code == 200
    assert r.json()["code"] == "SCHEDULED"


def test_aa_split_two_members(client):
    r = client.post("/api/transfers/aa-split",
                    json={"total_amount": 300, "contact_ids": ["c005", "c006"], "remark": "这顿 300 我们仨 AA"},
                    headers={"Idempotency-Key": "it-aa-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "OK"
    assert body["share"] == 100.0 and len(body["requests"]) == 2, "仨人 AA：生成 2 笔收款单（doc 05 M3#5）"
