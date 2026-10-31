"""End-to-end checks for every scene in the problem statement.

Run with:  python -m pytest -q
"""
import time
from datetime import date, timedelta

from conftest import login

from app.database import SessionLocal
from app.models import Invoice, Plan, Subscription, SubscriptionLine, User
from app.security import hash_password
from app.services import change_status, next_period_start, price_lines, run_billing

TODAY = date.today()


def new_customer(client, email, password="Strong#Pass1"):
    r = client.post("/api/auth/register", json={"name": "Test Customer", "email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]


def plan_id(client, headers, name):
    return next(p["id"] for p in client.get("/api/plans", headers=headers).json() if p["name"] == name)


# ---------------------------------------------------------------- sign-up, passwords and roles
def test_password_rules(client):
    cases = {"Short1!": "more than 8", "nouppercase1!": "uppercase", "NOLOWERCASE1!": "lowercase",
             "NoSpecialChar123": "special"}
    for pw, words in cases.items():
        r = client.post("/api/auth/register", json={"name": "X Y", "email": "rules@test.in", "password": pw})
        assert r.status_code == 422 and words in r.json()["detail"], (pw, r.text)


def test_signup_is_customer_only_and_email_unique(client):
    _, user = new_customer(client, "unique@test.in")
    assert user["role"] == "customer"
    r = client.post("/api/auth/register", json={"name": "Again", "email": "UNIQUE@test.in", "password": "Strong#Pass1"})
    assert r.status_code == 409


def test_roles(client, admin, staff, customer):
    assert client.get("/api/users", headers=customer).status_code == 403
    assert client.get("/api/users", headers=staff).status_code == 403          # only admin manages the team
    staff_member = {"name": "New Staff", "email": "newstaff@intrinsic.io", "password": "Staff#Pass1", "role": "staff"}
    assert client.post("/api/users", headers=staff, json=staff_member).status_code == 403
    assert client.post("/api/users", headers=admin, json=staff_member).status_code == 200
    product = {"name": "Nope", "sales_price": 10}
    assert client.post("/api/products", headers=staff, json=product).status_code == 403
    discount = {"code": "STAFF5", "name": "Staff try", "value": 5, "start_date": TODAY.isoformat()}
    assert client.post("/api/discounts", headers=staff, json=discount).status_code == 403
    assert client.get("/api/discounts", headers=customer).status_code == 403   # codes are not public
    assert client.get("/api/subscriptions").status_code == 401


def test_customers_only_see_their_own_records(client, admin, customer):
    others = client.get("/api/subscriptions?q=Priya", headers=admin).json()["items"]
    assert others
    assert client.get(f"/api/subscriptions/{others[0]['id']}", headers=customer).status_code == 404
    mine = client.get("/api/subscriptions?page_size=200", headers=customer).json()["items"]
    assert mine and all(s["customer_email"] == "customer@intrinsic.io" for s in mine)
    invoices = client.get("/api/invoices?page_size=200", headers=customer).json()["items"]
    assert all(i["status"] != "draft" for i in invoices)


def test_password_reset_flow(client):
    new_customer(client, "forgot@test.in", "Old#Password1")
    r = client.post("/api/auth/forgot-password", json={"email": "forgot@test.in"}).json()
    token = r["demo_reset_link"].split("token=")[1]
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "weak"}).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "New#Password1"}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "New#Password2"}).status_code == 400
    login(client, "forgot@test.in", "New#Password1")
    # Unknown emails get the same answer and no link
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@test.in"}).json()
    assert "demo_reset_link" not in r


def test_deactivated_user_is_locked_out(client, admin):
    headers, user = new_customer(client, "leaver@test.in")
    team = {"name": "Temp Staff", "email": "temp@intrinsic.io", "password": "Temp#Pass12", "role": "staff"}
    staff_id = client.post("/api/users", headers=admin, json=team).json()["id"]
    temp = login(client, "temp@intrinsic.io", "Temp#Pass12")
    client.post(f"/api/users/{staff_id}/toggle-active", headers=admin)
    assert client.get("/api/auth/me", headers=temp).status_code == 401
    assert client.post("/api/auth/login", json={"email": "temp@intrinsic.io", "password": "Temp#Pass12"}).status_code == 403


# ---------------------------------------------------------------- products, variants, plans
def test_variant_adds_to_price(client, admin, staff):
    tax = client.post("/api/taxes", headers=admin, json={"name": "GST 12%", "rate": 12}).json()
    product = client.post("/api/products", headers=admin, json={
        "name": "Helpdesk", "product_type": "service", "sales_price": 1000, "cost_price": 300, "notes": "Test",
        "tax_id": tax["id"], "variants": [{"attribute": "Brand", "value": "Odoo", "extra_price": 560}]}).json()
    variant = product["variants"][0]
    customer = client.get("/api/customers?q=Arjun", headers=staff).json()[0]
    sub = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": customer["id"], "plan_id": plan_id(client, staff, "Starter"),
        "lines": [{"product_id": product["id"], "variant_id": variant["id"], "quantity": 2}]}).json()
    line = next(l for l in sub["lines"] if l["product_id"] == product["id"])
    assert line["unit_price"] == 1560.0 and line["subtotal"] == 3120.0
    assert line["tax_amount"] == round(3120 * 0.12, 2)


def test_plan_minimum_quantity_and_availability(client, admin, staff):
    customer = client.get("/api/customers?q=Arjun", headers=staff).json()[0]
    r = client.post("/api/subscriptions", headers=staff, json={
        "customer_id": customer["id"], "plan_id": plan_id(client, staff, "Business (per seat)"), "plan_quantity": 2})
    assert r.status_code == 400 and "minimum quantity of 5" in r.json()["detail"]
    future = client.post("/api/plans", headers=admin, json={
        "name": "Next Year", "price": 10, "billing_period": "monthly",
        "start_date": (TODAY + timedelta(days=200)).isoformat()}).json()
    r = client.post("/api/subscriptions", headers=staff, json={"customer_id": customer["id"], "plan_id": future["id"]})
    assert r.status_code == 400 and "not available" in r.json()["detail"]


# ---------------------------------------------------------------- lifecycle, invoices, payments
def test_full_lifecycle_quote_to_paid(client, staff, customer):
    me = client.get("/api/auth/me", headers=customer).json()
    tpl = next(t for t in client.get("/api/templates", headers=staff).json() if t["name"].startswith("Starter"))
    sub = client.post("/api/subscriptions", headers=staff, json={"customer_id": me["id"], "template_id": tpl["id"]}).json()
    assert sub["status"] == "draft" and sub["number"].startswith("SUB-")
    assert len(sub["lines"]) == 1 + len(tpl["lines"])                   # plan line + template product lines

    bad = client.post(f"/api/subscriptions/{sub['id']}/transition", headers=staff, json={"to": "active"})
    assert bad.status_code == 400                                        # cannot skip steps

    sub = client.post(f"/api/subscriptions/{sub['id']}/transition", headers=staff, json={"to": "quotation"}).json()
    assert sub["quote_valid_until"] == (TODAY + timedelta(days=tpl["validity_days"])).isoformat()
    assert client.post(f"/api/subscriptions/{sub['id']}/transition", headers=customer,
                       json={"to": "active"}).status_code == 403          # customers only accept or decline
    sub = client.post(f"/api/subscriptions/{sub['id']}/transition", headers=customer, json={"to": "confirmed"}).json()
    sub = client.post(f"/api/subscriptions/{sub['id']}/transition", headers=staff, json={"to": "active"}).json()
    assert sub["status"] == "active"

    invs = client.get(f"/api/invoices?subscription_id={sub['id']}", headers=staff).json()["items"]
    assert len(invs) == 1 and invs[0]["status"] == "draft"               # first invoice created automatically
    inv = client.get(f"/api/invoices/{invs[0]['id']}", headers=staff).json()
    assert inv["total"] == sub["total"] and inv["lines"]

    assert client.post(f"/api/invoices/{inv['id']}/payments", headers=staff,
                       json={"amount": 10, "method": "cash"}).status_code == 400   # draft cannot be paid
    client.post(f"/api/invoices/{inv['id']}/confirm", headers=staff)
    part = client.post(f"/api/invoices/{inv['id']}/payments", headers=staff,
                       json={"amount": 100, "method": "upi", "note": "Advance"}).json()
    assert part["status"] == "confirmed" and part["balance"] == round(inv["total"] - 100, 2)
    too_much = client.post(f"/api/invoices/{inv['id']}/payments", headers=staff,
                           json={"amount": inv["total"], "method": "cash"})
    assert too_much.status_code == 400
    paid = client.post(f"/api/invoices/{inv['id']}/pay", headers=customer, json={"method": "card"}).json()
    assert paid["status"] == "paid" and paid["balance"] == 0 and len(paid["payments"]) == 2

    html = client.get(f"/api/invoices/{inv['id']}/print", headers=customer)
    assert html.status_code == 200 and inv["number"] in html.text
    sent = client.post(f"/api/invoices/{inv['id']}/send", headers=staff).json()
    assert sent["sent_at"] and "Demo mode" in sent["message"]
    history = client.get(f"/api/subscriptions/{sub['id']}", headers=staff).json()["history"]
    assert [h["to"] for h in history if h["action"] == "status"] == ["quotation", "confirmed", "active"]


def test_expired_quotation_cannot_be_accepted(client, staff):
    with SessionLocal() as db:
        sub = db.query(Subscription).filter(Subscription.status == "quotation").first()
        sub.quote_valid_until = TODAY - timedelta(days=1)
        db.commit()
        sub_id = sub.id
    r = client.post(f"/api/subscriptions/{sub_id}/transition", headers=staff, json={"to": "confirmed"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]


def test_cancel_rules(client, staff):
    paid = client.get("/api/invoices?status=paid", headers=staff).json()["items"][0]
    assert client.post(f"/api/invoices/{paid['id']}/cancel", headers=staff).status_code == 400


# ---------------------------------------------------------------- billing day
def _make_active(db, customer_email, plan_name, start, qty=1, expiry=None):
    customer = db.query(User).filter(User.email == customer_email).one()
    plan = db.query(Plan).filter(Plan.name == plan_name).one()
    sub = Subscription(customer_id=customer.id, plan_id=plan.id, plan=plan, status="confirmed", start_date=start,
                       expiry_date=expiry, payment_terms_days=10)
    sub.lines.append(SubscriptionLine(description=plan.name, quantity=qty, unit_price=plan.price, tax=plan.tax))
    db.add(sub)
    db.flush()
    sub.number = f"SUB-{sub.id:05d}"
    staff = db.query(User).filter(User.email == "staff@intrinsic.io").one()
    change_status(db, sub, "active", staff, None, start)
    db.commit()
    return sub


def test_billing_never_bills_twice_or_skips(client):
    with SessionLocal() as db:
        start = TODAY - timedelta(days=95)
        sub = _make_active(db, "priya@acmetraders.in", "Starter", start)
        first = db.query(Invoice).filter(Invoice.subscription_id == sub.id).count()
        assert first == 1                                                # invoiced on its start date
        run_billing(db, TODAY)
        run_billing(db, TODAY)                                           # pressing it again changes nothing
        periods = [i.period_start for i in db.query(Invoice).filter(Invoice.subscription_id == sub.id)
                   .order_by(Invoice.period_start)]
        expected, d = [], start
        while d <= TODAY:
            expected.append(d)
            d = next_period_start(start, d, "monthly")
        assert periods == expected                                       # one per month, none missing
        assert len(set(periods)) == len(periods)


def test_billing_endpoint_is_idempotent(client, staff):
    client.post("/api/billing/run", headers=staff)
    assert client.post("/api/billing/run", headers=staff).json()["invoices_created"] == 0


def test_month_end_dates_do_not_drift():
    anchor = date(2025, 1, 31)
    d1 = next_period_start(anchor, anchor, "monthly")
    d2 = next_period_start(anchor, d1, "monthly")
    assert (d1, d2) == (date(2025, 2, 28), date(2025, 3, 31))
    assert next_period_start(date(2024, 2, 29), date(2024, 2, 29), "yearly") == date(2025, 2, 28)


def test_paused_subscriptions_are_not_billed(client, staff):
    with SessionLocal() as db:
        sub = _make_active(db, "lakshmi@greenleaf.in", "Starter", TODAY - timedelta(days=40))
        sub_id = sub.id
    client.post(f"/api/subscriptions/{sub_id}/pause", headers=staff)
    with SessionLocal() as db:
        before = db.query(Invoice).filter(Invoice.subscription_id == sub_id).count()
        run_billing(db, TODAY + timedelta(days=90))
        assert db.query(Invoice).filter(Invoice.subscription_id == sub_id).count() == before


def test_auto_close_at_expiry_and_renewal(client, staff):
    with SessionLocal() as db:
        start = TODAY - timedelta(days=400)
        sub = _make_active(db, "david@globexindia.com", "Enterprise Annual", start, expiry=start + timedelta(days=365))
        run_billing(db, TODAY)
        db.refresh(sub)
        assert sub.status == "closed"                                    # plan closes it on its own
        assert db.query(Invoice).filter(Invoice.subscription_id == sub.id).count() == 1  # one year billed, not two
        renewable = _make_active(db, "david@globexindia.com", "Enterprise Annual", TODAY,
                                 expiry=TODAY + timedelta(days=365))
        rid = renewable.id
    r = client.post(f"/api/subscriptions/{rid}/renew", headers=staff).json()
    assert r["expiry_date"] == (TODAY + timedelta(days=730)).isoformat()
    early = client.post(f"/api/subscriptions/{rid}/transition", headers=staff, json={"to": "closed"})
    assert early.status_code == 400 and "cannot be closed early" in early.json()["detail"]


# ---------------------------------------------------------------- discounts
def test_discount_rules(client, admin, staff):
    customer = client.get("/api/customers?q=Rohan", headers=staff).json()[0]
    starter = plan_id(client, staff, "Starter")
    body = {"customer_id": customer["id"], "plan_id": starter}

    r = client.post("/api/subscriptions", headers=staff, json={**body, "discount_code": "DIWALI20"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    r = client.post("/api/subscriptions", headers=staff, json={**body, "discount_code": "NOPE"})
    assert r.status_code == 400

    # Minimum quantity not met: code is kept but not applied
    sub = client.post("/api/subscriptions", headers=staff, json={**body, "discount_code": "SEATS15"}).json()
    assert not sub["discount_applied"] and "Minimum quantity" in sub["discount_note"]

    # Usage limit: the discount stops on its own once used up
    limited = client.post("/api/discounts", headers=admin, json={
        "code": "ONCE", "name": "One use", "discount_type": "fixed", "value": 100,
        "start_date": TODAY.isoformat(), "usage_limit": 1}).json()
    with SessionLocal() as db:
        sub = _make_active(db, "rohan@kaveriprints.in", "Weekly Pilot", TODAY - timedelta(days=15))
        from app.models import Discount
        sub.discount = db.get(Discount, limited["id"])
        db.query(Invoice).filter(Invoice.subscription_id == sub.id).delete()
        sub.next_invoice_date = sub.start_date
        db.commit()
        run_billing(db, TODAY)
        invs = db.query(Invoice).filter(Invoice.subscription_id == sub.id).order_by(Invoice.period_start).all()
        assert len(invs) >= 2
        assert invs[0].discount_total == 100 and invs[0].discount_code == "ONCE"
        assert all(i.discount_total == 0 for i in invs[1:])
        assert db.get(Discount, limited["id"]).used_count == 1


def test_fixed_discount_is_split_and_taxed_after(client):
    with SessionLocal() as db:
        from app.models import Discount, Tax
        tax = Tax(name="T10", rate=10)
        lines = [SubscriptionLine(description="A", quantity=1, unit_price=300, tax=tax),
                 SubscriptionLine(description="B", quantity=1, unit_price=100, tax=tax)]
        d = Discount(code="X", name="x", discount_type="fixed", value=100, min_amount=0, min_quantity=0,
                     start_date=TODAY, used_count=0, applies_to="subscription", is_active=True)
        p = price_lines(lines, d, TODAY)
        assert [l["discount_amount"] for l in p["lines"]] == [75.0, 25.0]
        assert p["tax_total"] == 30.0 and p["total"] == 330.0


# ---------------------------------------------------------------- reports & speed
def test_reports_add_up(client, admin):
    r = client.get("/api/reports/summary", headers=admin).json()
    overdue = client.get("/api/invoices?status=overdue&page_size=200", headers=admin).json()
    assert r["overdue_count"] == overdue["total"]
    assert r["overdue_amount"] == round(sum(i["balance"] for i in overdue["items"]), 2)
    assert r["mrr"] > 0 and r["active_subscriptions"] > 0


def test_pages_respond_under_two_seconds_with_thousands_of_subscriptions(client, admin):
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.name == "Starter").one()
        pw = hash_password("Bulk#Pass1")
        people = [User(name=f"Bulk {i}", email=f"bulk{i}@load.test", password_hash=pw, role="customer")
                  for i in range(300)]
        db.add_all(people)
        db.flush()
        for i in range(3000):
            sub = Subscription(customer_id=people[i % 300].id, plan_id=plan.id, status="active",
                               start_date=TODAY, next_invoice_date=TODAY + timedelta(days=30), number=f"BULK-{i}")
            sub.lines.append(SubscriptionLine(description="Starter", quantity=1, unit_price=999, tax_id=plan.tax_id))
            db.add(sub)
        db.commit()
    for path in ("/api/reports/summary", "/api/subscriptions?page_size=50", "/api/subscriptions?q=Bulk 12",
                 "/api/invoices?page_size=50", "/api/payments", "/api/customers"):
        started = time.perf_counter()
        r = client.get(path, headers=admin)
        elapsed = time.perf_counter() - started
        assert r.status_code == 200, path
        assert elapsed < 2.0, f"{path} took {elapsed:.2f}s"
