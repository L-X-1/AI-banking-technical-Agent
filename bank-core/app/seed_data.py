"""种子静态数据（对齐 doc 03 §9；金额单位：元）。

演示锚点（doc 02 §3.1）：张三活期余额 ¥52,300.00；通讯录 8 人含两个李磊。
"""
USERS = [
    dict(id="u001", name="张三", phone="13800006688", id_card_masked="1101**********1234",
         risk_level=2, login_password="123456"),
]

ACCOUNTS = [
    dict(id="a001", user_id="u001", account_no="6222020200006688", type="checking", balance=52300.00, frozen_amount=0.0),
    dict(id="a002", user_id="u001", account_no="6222020200007799", type="deposit", balance=200000.00, frozen_amount=0.0),
]

# doc 03 §9.1：8 人（含同名消歧主角 李磊×2；生日联动主角 王芳）
CONTACTS = [
    dict(id="c001", user_id="u001", name="李磊", phone="13800003821", account_no="6222020200003821", remark="同事"),
    dict(id="c002", user_id="u001", name="李磊", phone="13800007790", account_no="6222020200007790", remark="大学同学"),
    dict(id="c003", user_id="u001", name="王芳", phone="13800005566", account_no="6222020200005566", remark="妻子"),
    dict(id="c004", user_id="u001", name="房东-陈姐", phone="13800009012", account_no="6222020200009012", remark="每月房租"),
    dict(id="c005", user_id="u001", name="张伟", phone="13800003344", account_no="6222020200003344", remark="同事"),
    dict(id="c006", user_id="u001", name="刘洋", phone="13800008877", account_no="6222020200008877", remark="同事"),
    dict(id="c007", user_id="u001", name="赵敏", phone="13800002211", account_no="6222020200002211", remark="朋友"),
    dict(id="c008", user_id="u001", name="妈妈", phone="13800006688", account_no="6222020200006699", remark="家人"),
]

# doc 03 §9.3：12 只（R1×2 / R2×3 / R3×3 / R4×2 / R5×2）；p001 推荐主力；p008 用于 R4 拒绝演示
PRODUCTS = [
    dict(id="p001", code="WP001", name="稳健添利 30 天", type="债券", risk_level=2, annual_yield=2.8, min_amount=1000.0, lock_days=30),
    dict(id="p002", code="WP002", name="天天盈货币 A", type="货币", risk_level=1, annual_yield=1.9, min_amount=1.0, lock_days=0),
    dict(id="p003", code="WP003", name="现金宝货币 B", type="货币", risk_level=1, annual_yield=2.1, min_amount=100.0, lock_days=0),
    dict(id="p004", code="WP004", name="稳盈债券 90 天", type="债券", risk_level=2, annual_yield=3.1, min_amount=1000.0, lock_days=90),
    dict(id="p005", code="WP005", name="固收增强 180 天", type="债券", risk_level=3, annual_yield=3.6, min_amount=5000.0, lock_days=180),
    dict(id="p006", code="WP006", name="平衡配置混合", type="混合", risk_level=3, annual_yield=4.2, min_amount=5000.0, lock_days=180),
    dict(id="p007", code="WP007", name="量化对冲混合", type="混合", risk_level=3, annual_yield=4.5, min_amount=10000.0, lock_days=365),
    dict(id="p008", code="WP008", name="成长精选股票型", type="股票", risk_level=4, annual_yield=6.8, min_amount=10000.0, lock_days=365),
    dict(id="p009", code="WP009", name="沪深 300 指数增强", type="股票", risk_level=4, annual_yield=7.2, min_amount=10000.0, lock_days=365),
    dict(id="p010", code="WP010", name="全球科技主题", type="股票", risk_level=5, annual_yield=9.0, min_amount=20000.0, lock_days=730),
    dict(id="p011", code="WP011", name="高波动量化", type="股票", risk_level=5, annual_yield=9.5, min_amount=20000.0, lock_days=730),
    dict(id="p012", code="WP012", name="稳健添利 90 天", type="债券", risk_level=2, annual_yield=3.0, min_amount=1000.0, lock_days=90),
]

HOLDINGS = [
    dict(id="h001", user_id="u001", product_id="p001", amount=20000.0, profit=46.58, status="持有"),
    dict(id="h002", user_id="u001", product_id="p002", amount=10000.0, profit=18.35, status="持有"),
]

CARDS = [
    dict(id="cd001", user_id="u001", card_no_masked="6222 **** **** 6688", type="借记", credit_limit=0.0, daily_limit=50000.0, status="正常"),
    dict(id="cd002", user_id="u001", card_no_masked="6225 **** **** 8899", type="信用", credit_limit=30000.0, daily_limit=50000.0, status="正常"),
]

# doc 03 §9.4：5 个生效中（含 2 个遗忘）+ 1 个 7 天后到期续费（s006，2026-09-30）
SUBSCRIPTIONS = [
    dict(id="s001", user_id="u001", merchant="视频会员", amount=25.0, cycle="月", next_billing_date="2026-10-03", status="生效"),
    dict(id="s002", user_id="u001", merchant="音乐会员", amount=15.0, cycle="月", next_billing_date="2026-10-08", status="生效"),
    dict(id="s003", user_id="u001", merchant="云存储", amount=68.0, cycle="月", next_billing_date="2026-10-14", status="生效"),
    dict(id="s004", user_id="u001", merchant="健身 App", amount=198.0, cycle="季", next_billing_date="2026-11-01", status="生效"),
    dict(id="s005", user_id="u001", merchant="新闻订阅", amount=12.0, cycle="月", next_billing_date="2026-10-20", status="生效"),
    dict(id="s006", user_id="u001", merchant="云盘 Pro", amount=30.0, cycle="月", next_billing_date="2026-09-30", status="生效"),
]