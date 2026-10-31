"""Demo data for Brightloop Software, created the first time the app starts.

Every demo account uses the password  Intrinsic@2026
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Discount, Invoice, Plan, Product, ProductVariant, QuotationTemplate, Subscription, Tax, TemplateLine, User,
)
from app.schemas import LineIn
from app.security import hash_password
from app.services import audit, build_lines, change_status, record_payment, run_billing

DEMO_PASSWORD = "Intrinsic@2026"
METHODS = ("bank_transfer", "upi", "card", "cash", "cheque")


def seed(db: Session, today: date | None = None) -> bool:
    if db.query(User.id).first():
        return False
    today = today or date.today()
    pw = hash_password(DEMO_PASSWORD)

    # ---------------------------------------------------------- people
    admin = User(name="Ananya Rao", email="admin@intrinsic.io", password_hash=pw, role="admin",
                 department="Finance & Administration")
    staff = User(name="Rahul Menon", email="staff@intrinsic.io", password_hash=pw, role="staff",
                 department="Customer Success")
    db.add_all([admin, staff, User(name="Meera Pillai", email="meera@intrinsic.io", password_hash=pw, role="staff",
                                   department="Billing Operations")])
    customers_spec = [
        ("Arjun Nair", "customer@intrinsic.io", "Nimbus Retail Pvt Ltd", "+91 98470 11223", "MG Road, Kochi, Kerala"),
        ("Priya Sharma", "priya@acmetraders.in", "Acme Traders", "+91 99950 44556", "Technopark, Trivandrum, Kerala"),
        ("David Thomas", "david@globexindia.com", "Globex India Ltd", "+91 80 4123 7788", "Whitefield, Bengaluru"),
        ("Fatima Khan", "fatima@heliostudio.in", "Helio Studio", "+91 97445 66778", "Kakkanad, Kochi, Kerala"),
        ("Vikram Iyer", "vikram@initech.co.in", "Initech Solutions", "+91 44 2811 9900", "OMR, Chennai"),
        ("Sneha Kulkarni", "sneha@bluepeak.in", "Bluepeak Foods", "+91 20 6610 2233", "Baner, Pune"),
        ("Rohan Das", "rohan@kaveriprints.in", "Kaveri Prints", "+91 33 4002 1188", "Salt Lake, Kolkata"),
        ("Lakshmi Menon", "lakshmi@greenleaf.in", "Greenleaf Organics", "+91 484 270 3344", "Edappally, Kochi"),
    ]
    customers = [User(name=n, email=e, password_hash=pw, role="customer", company=c, phone=p, address=a)
                 for n, e, c, p, a in customers_spec]
    db.add_all(customers)
    nimbus, acme, globex, helio, initech, bluepeak, kaveri, greenleaf = customers

    # ---------------------------------------------------------- taxes
    gst18 = Tax(name="GST 18%", rate=18)
    gst5 = Tax(name="GST 5%", rate=5)
    db.add_all([gst18, gst5, Tax(name="Exempt", rate=0)])

    # ---------------------------------------------------------- products & variants
    crm = Product(name="Brightloop CRM", product_type="service", sales_price=1200, cost_price=400, tax=gst18,
                  notes="Core CRM licence, billed per subscription period.",
                  variants=[ProductVariant(attribute="Brand", value="Standard", extra_price=0),
                            ProductVariant(attribute="Brand", value="Odoo", extra_price=560)])
    storage = Product(name="Cloud Storage 100 GB", product_type="addon", sales_price=300, cost_price=90, tax=gst18,
                      notes="Extra storage add-on.")
    support = Product(name="Priority Support", product_type="addon", sales_price=800, cost_price=300, tax=gst18,
                      notes="4-hour response time, business days.")
    analytics = Product(name="Analytics Pack", product_type="addon", sales_price=600, cost_price=150, tax=gst18,
                        notes="Dashboards and scheduled reports.")
    scanner = Product(name="Barcode Scanner Rental", product_type="goods", sales_price=450, cost_price=250, tax=gst5,
                      notes="Hardware rental, replaced free if faulty.",
                      variants=[ProductVariant(attribute="Brand", value="Honeywell", extra_price=0),
                                ProductVariant(attribute="Brand", value="Zebra", extra_price=120)])
    db.add_all([crm, storage, support, analytics, scanner])

    # ---------------------------------------------------------- plans
    start = today - timedelta(days=400)
    starter = Plan(name="Starter", price=999, billing_period="monthly", min_quantity=1, start_date=start,
                   pausable=True, closable=True, renewable=True, tax=gst18,
                   description="For small shops getting started.")
    business = Plan(name="Business (per seat)", price=799, billing_period="monthly", min_quantity=5, start_date=start,
                    closable=True, renewable=True, tax=gst18, description="Per-seat plan for growing teams.")
    enterprise = Plan(name="Enterprise Annual", price=89000, billing_period="yearly", min_quantity=1, start_date=start,
                      auto_close=True, closable=False, renewable=True, tax=gst18,
                      description="Yearly contract. Closes on its own at the end of the term unless renewed.")
    pilot = Plan(name="Weekly Pilot", price=499, billing_period="weekly", min_quantity=1, start_date=start,
                 end_date=today + timedelta(days=90), closable=True, renewable=False, tax=gst18,
                 description="Short trial billed weekly. Offered for a limited time.")
    event = Plan(name="Event Day Pass", price=199, billing_period="daily", min_quantity=1, start_date=start,
                 closable=True, renewable=False, tax=gst18, description="Billed per day for events.")
    db.add_all([starter, business, enterprise, pilot, event])

    # ---------------------------------------------------------- discounts
    welcome = Discount(code="WELCOME10", name="Welcome offer - 10% off", discount_type="percentage", value=10,
                       start_date=today - timedelta(days=365), end_date=today + timedelta(days=180), usage_limit=500)
    seats = Discount(code="SEATS15", name="15% off for 10+ seats", discount_type="percentage", value=15,
                     min_quantity=10, start_date=today - timedelta(days=365))
    odoo = Discount(code="ODOO560", name="Odoo partner rebate (CRM)", discount_type="fixed", value=560,
                    applies_to="product", product=crm, start_date=today - timedelta(days=60),
                    end_date=today + timedelta(days=60), usage_limit=50)
    big = Discount(code="BIGSPEND", name="Rs 1,000 off orders above Rs 10,000", discount_type="fixed", value=1000,
                   min_amount=10000, start_date=today - timedelta(days=30), usage_limit=3)
    expired = Discount(code="DIWALI20", name="Festive 20% (expired)", discount_type="percentage", value=20,
                       start_date=today - timedelta(days=200), end_date=today - timedelta(days=150))
    db.add_all([welcome, seats, odoo, big, expired])
    db.flush()

    # ---------------------------------------------------------- quotation templates
    db.add_all([
        QuotationTemplate(name="Business 10 seats + CRM (Odoo)", plan=business, plan_quantity=10, validity_days=15,
                          notes="Standard offer for mid-size customers.",
                          lines=[TemplateLine(product_id=crm.id, variant_id=crm.variants[1].id, quantity=1),
                                 TemplateLine(product_id=storage.id, quantity=2)]),
        QuotationTemplate(name="Starter bundle", plan=starter, plan_quantity=1, validity_days=30,
                          lines=[TemplateLine(product_id=storage.id, quantity=1)]),
        QuotationTemplate(name="Enterprise annual contract", plan=enterprise, plan_quantity=1, validity_days=21,
                          lines=[TemplateLine(product_id=support.id, quantity=1),
                                 TemplateLine(product_id=analytics.id, quantity=1)]),
    ])
    db.flush()

    # ---------------------------------------------------------- subscriptions
    def make(customer, plan, qty, items, started_days_ago, discount=None, expiry_days=None, terms=15, notes=None):
        start_date = today - timedelta(days=started_days_ago)
        sub = Subscription(customer_id=customer.id, plan_id=plan.id, plan=plan, status="draft",
                           start_date=start_date, payment_terms_days=terms, notes=notes, created_by_id=staff.id,
                           discount_id=discount.id if discount else None, discount=discount,
                           expiry_date=start_date + timedelta(days=expiry_days) if expiry_days else None)
        db.add(sub)
        db.flush()
        sub.number = f"SUB-{sub.id:05d}"
        sub.lines.extend(build_lines(db, plan, qty, [LineIn(**i) for i in items]))
        audit(db, sub, "created", staff, "Created.", None, "draft")
        db.flush()
        return sub

    def walk(sub, target, when):
        for step in ("quotation", "confirmed", "active", "closed"):
            if sub.status == target:
                break
            user = sub.customer if step == "confirmed" else staff
            if step == "quotation":
                sub.quote_valid_until = when + timedelta(days=30)
            change_status(db, sub, step, user, None, when)

    active_specs = [  # customer, plan, qty, items, days ago, discount, expiry days, unpaid at end, leave last draft
        (nimbus, business, 12, [{"product_id": crm.id, "variant_id": crm.variants[1].id, "quantity": 1},
                                {"product_id": storage.id, "quantity": 2}], 150, seats, None, 1, False),
        (acme, starter, 1, [{"product_id": support.id, "quantity": 1}], 125, welcome, None, 2, False),
        (globex, enterprise, 1, [{"product_id": support.id, "quantity": 1},
                                 {"product_id": analytics.id, "quantity": 1}], 200, None, 365, 0, False),
        (bluepeak, business, 6, [{"product_id": scanner.id, "variant_id": scanner.variants[1].id, "quantity": 3}],
         95, None, None, 0, False),
        (kaveri, starter, 1, [{"product_id": storage.id, "quantity": 1}], 70, None, None, 1, True),
        (greenleaf, pilot, 1, [], 40, None, None, 0, False),
        (helio, starter, 1, [], 80, None, None, 0, False),
    ]
    running = []
    for customer, plan, qty, items, ago, disc, exp, unpaid, draft in active_specs:
        sub = make(customer, plan, qty, items, ago, disc, exp)
        walk(sub, "active", sub.start_date)
        running.append((sub, unpaid, draft))

    # Replay every billing day from the oldest start date up to today.
    day = min(s.start_date for s, _, _ in running)
    while day <= today:
        run_billing(db, day)
        day += timedelta(days=1)

    for i, (sub, unpaid, leave_draft) in enumerate(running):
        invoices = db.query(Invoice).filter(Invoice.subscription_id == sub.id).order_by(Invoice.period_start).all()
        for n, inv in enumerate(invoices):
            last = n == len(invoices) - 1
            if leave_draft and last:
                continue
            inv.status = "confirmed"
            if n >= len(invoices) - unpaid:
                continue
            paid_on = min(inv.issue_date + timedelta(days=3 + (n + i) % 9), today)
            if sub.customer is bluepeak and n == 1:  # one invoice settled in two instalments
                half = round(inv.total / 2, 2)
                record_payment(db, inv, half, "bank_transfer", paid_on, "First instalment", staff)
                record_payment(db, inv, inv.total - half, "upi", min(paid_on + timedelta(days=5), today),
                               "Final instalment", staff)
                continue
            record_payment(db, inv, inv.total, METHODS[(n + i) % len(METHODS)], paid_on,
                           f"Ref {inv.number[-5:]}{n}", staff)

    helio_sub = running[-1][0]
    helio_sub.paused = True
    audit(db, helio_sub, "paused", helio, "Billing paused for the off-season.")

    # A closed contract, an open quotation, a draft request and a confirmed order.
    old = make(helio, starter, 1, [{"product_id": analytics.id, "quantity": 1}], 300, notes="Previous plan.")
    walk(old, "active", old.start_date)
    change_status(db, old, "closed", staff, "Moved to a new subscription.", old.start_date + timedelta(days=1))
    for inv in db.query(Invoice).filter(Invoice.subscription_id == old.id):
        inv.status = "confirmed"
        record_payment(db, inv, inv.total, "card", inv.issue_date + timedelta(days=2), None, staff)

    quote = make(initech, business, 10, [{"product_id": crm.id, "variant_id": crm.variants[1].id, "quantity": 1},
                                         {"product_id": storage.id, "quantity": 2}], 0, seats,
                 notes="Started from the 'Business 10 seats + CRM (Odoo)' template.")
    quote.template_id = db.query(QuotationTemplate.id).filter(QuotationTemplate.plan_id == business.id).scalar()
    walk(quote, "quotation", today)
    quote.quote_valid_until = today + timedelta(days=15)

    request = make(nimbus, starter, 1, [{"product_id": analytics.id, "quantity": 1}], -7,
                   notes="Customer asked for a separate account for their new outlet.")
    request.created_by_id = nimbus.id

    order = make(acme, pilot, 1, [], -3, notes="Pilot for the new warehouse team, starts next week.")
    walk(order, "confirmed", today)

    db.commit()
    return True
