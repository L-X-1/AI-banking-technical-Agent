"""M3 数据面验收（2/2）：卡片 + 订阅 + 资金锁定/调度器联动 + 修改密码。

fixture client 为 session 级共享库，用例按依赖顺序书写（锁定/改密/任务执行会改变状态）。
"""
H = {"X-User-Id": "u001"}


# ── 卡片（M3#4）────────────────────────────────────────────────
def test_cards_flow(client):
    cards = client.get("/api/cards", headers=H).json()["items"]
    assert len(cards) == 2 and all(c["status"] == "正常" for c in cards)

    v = client.post("/api/cards/apply-virtual", headers=H).json()
    assert v["code"] == "OK" and v["type"] == "虚拟" and v["daily_limit"] == 5000.0

    lim = client.post("/api/cards/cd002/limit", json={"daily_limit": 8888}, headers=H).json()
    assert lim["daily_limit"] == 8888.0
    bad = client.post("/api/cards/cd002/limit", json={"daily_limit": 999999}, headers=H)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "INVALID_LIMIT"

    fr = client.post("/api/cards/cd002/freeze", headers=H).json()
    assert fr["status"] == "冻结" and fr["changed"] is True
    again = client.post("/api/cards/cd002/freeze", headers=H).json()
    assert again["changed"] is False, "状态转换幂等"
    un = client.post("/api/cards/cd002/unfreeze", headers=H).json()
    assert un["status"] == "正常"

    loss = client.post("/api/cards/cd001/report-loss", headers=H).json()
    assert loss["status"] == "挂失"
    fr2 = client.post("/api/cards/cd001/freeze", headers=H)
    assert fr2.status_code == 409 and fr2.json()["detail"]["code"] == "CARD_LOST"
    un_loss = client.post("/api/cards/cd001/cancel-loss", headers=H).json()
    assert un_loss["status"] == "正常"
    bad_cancel = client.post("/api/cards/cd001/cancel-loss", headers=H)
    assert bad_cancel.status_code == 409 and bad_cancel.json()["detail"]["code"] == "INVALID_STATE"


# ── 订阅（M3#3）────────────────────────────────────────────────
def test_subscriptions_detect_and_cancel(client):
    lst = client.get("/api/subscriptions", headers=H).json()
    assert lst["total"] == 6 and lst["monthly_cost"] > 0

    det = client.get("/api/subscriptions/detect", headers=H).json()
    by_merchant = {i["merchant"]: i for i in det["items"]}
    assert by_merchant["云存储"]["subscription_id"] == "s003" and by_merchant["云存储"]["is_new"] is False
    assert by_merchant["云存储"]["occurrences"] >= 3, "遗忘订阅：连续扣费被识别"
    assert by_merchant["iCloud 扩容"]["is_new"] is True, "流水有、订阅表无 → 新识别候选"

    c = client.post("/api/subscriptions/s005/cancel", headers=H).json()
    assert c["status"] == "已取消" and c["changed"] is True and c["saved_monthly"] == 12.0
    again = client.post("/api/subscriptions/s005/cancel", headers=H).json()
    assert again["changed"] is False
    missing = client.post("/api/subscriptions/s999/cancel", headers=H)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "SUBSCRIPTION_NOT_FOUND"


# ── 资金锁定（M3#6 前半）──────────────────────────────────────
def test_freeze_unfreeze_amount(client):
    f = client.post("/api/accounts/a001/freeze-amount", json={"amount": 1000, "reason": "爱人生日准备金"}, headers=H)
    assert f.status_code == 200 and f.json()["frozen_amount"] == 1000.0
    over = client.post("/api/accounts/a001/unfreeze-amount", json={"amount": 99999}, headers=H)
    assert over.status_code == 400 and over.json()["detail"]["code"] == "INSUFFICIENT_FROZEN"


# ── 调度器联动（M3#6 后半）────────────────────────────────────
def test_scheduler_gift_order_run_now(client):
    """生日联动主线：创建 gift_order + reminder + fund_unlock → run-now → 支出流水 + 解冻。"""
    gift = client.post("/api/scheduled-tasks", headers=H, json={
        "task_type": "gift_order", "next_run_at": "2026-09-01 09:00",
        "payload": {"items": ["鲜花", "蛋糕"], "amount": 600, "recipient": "爱人", "merchant": "花加鲜花"}})
    assert gift.status_code == 200 and gift.json()["code"] == "OK"
    client.post("/api/scheduled-tasks", headers=H, json={
        "task_type": "reminder", "next_run_at": "2026-09-01 08:00",
        "payload": {"title": "生日提醒", "text": "明天爱人生日，鲜花蛋糕已预订"}})
    client.post("/api/scheduled-tasks", headers=H, json={
        "task_type": "fund_unlock", "next_run_at": "2026-09-01 10:00",
        "payload": {"amount": 1000, "reason": "生日准备金到期解锁"}})
    bad = client.post("/api/scheduled-tasks", headers=H, json={
        "task_type": "hack", "next_run_at": "2026-09-01", "payload": {}})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "BAD_TASK_TYPE"

    before = client.get("/api/accounts", headers=H).json()["items"][0]
    run = client.post("/api/admin/scheduler/run-now", params={"now": "2026-09-02 00:00:00"})
    assert run.status_code == 200
    results = {r["task_type"]: r for r in run.json()["executed"]}
    assert results["gift_order"]["ok"] and results["gift_order"]["status"] == "done"
    assert results["fund_unlock"]["ok"] and results["reminder"]["ok"]

    after = client.get("/api/accounts", headers=H).json()["items"][0]
    assert after["balance"] == round(before["balance"] - 600, 2), "礼品下单产生支出"
    assert after["frozen_amount"] == 0.0, "fund_unlock 解冻 1000"
    txns = client.get("/api/accounts/a001/transactions",
                      params={"keyword": "礼品订购"}, headers=H).json()["items"]
    assert any(t["channel"] == "scheduler" and t["amount"] == -600.0 and "鲜花" in t["remark"] for t in txns)

    again = client.post("/api/admin/scheduler/run-now", params={"now": "2026-09-02 00:00:00"})
    assert again.json()["count"] == 0, "任务 done 后不可重复触发（幂等）"


def test_scheduled_transfer_executes_and_monthly_rolls(client):
    t = client.post("/api/scheduled-tasks", headers=H, json={
        "task_type": "transfer", "next_run_at": "2026-09-01 09:00", "recurrence": "monthly",
        "payload": {"to_contact_id": "c003", "amount": 100, "remark": "每月家用"}}).json()
    run = client.post("/api/admin/scheduler/run-now", params={"now": "2026-09-02 00:00:00"})
    hit = next(r for r in run.json()["executed"] if r["task_id"] == t["id"])
    assert hit["ok"] and hit["status"] == "active", "monthly 任务执行后滚入下月"
    mine = next(x for x in client.get("/api/scheduled-tasks", headers=H).json()["items"] if x["id"] == t["id"])
    assert mine["next_run_at"].startswith("2026-10-01")
    cancel = client.delete(f"/api/scheduled-tasks/{t['id']}", headers=H).json()
    assert cancel["status"] == "cancelled"


# ── 修改密码（change_password 落点，M1 欠账补齐）──────────────
def test_change_password_guards(client):
    wrong = client.post("/api/auth/change-password",
                        json={"old_password": "bad", "new_password": "Abcdef12"}, headers=H)
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "OLD_PASSWORD_INCORRECT"
    weak = client.post("/api/auth/change-password",
                       json={"old_password": "123456", "new_password": "short"}, headers=H)
    assert weak.status_code == 400 and weak.json()["detail"]["code"] == "WEAK_NEW_PASSWORD"
    ok = client.post("/api/auth/change-password",
                     json={"old_password": "123456", "new_password": "Abcdef12"}, headers=H)
    assert ok.status_code == 200 and ok.json()["code"] == "OK"
    same = client.post("/api/auth/change-password",
                       json={"old_password": "Abcdef12", "new_password": "Abcdef12"}, headers=H)
    assert same.status_code == 400 and same.json()["detail"]["code"] == "SAME_AS_OLD"