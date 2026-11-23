"""Automated checks for the web app: logins, role permissions, input checks and a
scan that no page points to an outside website.  Run:  python test_app.py"""
import re
import app as A

passed = failed = 0


def check(name, ok):
    global passed, failed
    passed += ok
    failed += (not ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def client(user=None, pw=None):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "t"
    if user:
        c.post("/login", data={"csrf": "t", "username": user, "password": pw})
        with c.session_transaction() as s:
            s["csrf"] = "t"
    return c


DETAIL = ("/design/detail?capacity_kl=500&staging_height_m=16&soil_bearing_kpa=150&wind_speed_m_s=44"
          "&seismic_zone_factor=0.16&num_columns=8&grade=20")

# --- not signed in: everything redirects to login
anon = client()
for url in ["/overview", "/design", DETAIL, "/regional", "/vendor/plotly.js", "/advice"]:
    r = anon.get(url)
    check(f"signed-out {url[:22]} -> login", r.status_code == 302 and "/login" in r.headers["Location"])

# --- wrong password
bad = client("manager", "wrong")
check("wrong password rejected", bad.get("/overview").status_code == 302)

# --- every role can view the read-only pages
for u, p in [("manager", "Manager@123"), ("site", "Site@123"), ("client", "Client@123")]:
    c = client(u, p)
    for url in ["/design", DETAIL, "/regional"]:
        check(f"{u} can open {url[:22]}", c.get(url).status_code == 200)

# --- design detail content and input checks
c = client("client", "Client@123")
h = c.get(DETAIL).data.decode()
check("detail shows foundation load", "Load on foundation" in h)
check("detail lists assumptions", "Assumptions used for this design" in h)
check("detail rejects text input", c.get("/design/detail?capacity_kl=abc").status_code == 302)
check("detail rejects out-of-range input", c.get(DETAIL.replace("capacity_kl=500", "capacity_kl=999999")).status_code == 302)
check("detail rejects odd grade", c.get(DETAIL.replace("grade=20", "grade=22")).status_code == 302)

# --- regional planner
r = c.post("/regional", data={"csrf": "t", "zones": A.DEMO_ZONES_CSV})
check("regional plans demo zones", b"Cheapest arrangement" in r.data)
r = c.post("/regional", data={"csrf": "t", "zones": "name,lat\nX,abc"})
check("regional survives bad CSV", r.status_code == 200 and b"Could not read" in r.data)
r = c.post("/regional", data={"csrf": "bad", "zones": A.DEMO_ZONES_CSV})
check("regional POST needs CSRF token", r.status_code in (400, 403))

# --- role limits on actions
cl = client("client", "Client@123")
check("client cannot log progress (needs 'log')", cl.post("/progress", data={"csrf": "t"}).status_code in (302, 403))
sm = client("manager", "Manager@123")
check("signed-out POST without token is refused", client().post("/progress", data={}).status_code == 400)

# --- no outside links or GitHub text in any page
pages = [c.get("/design").data, c.get(DETAIL).data, c.post("/regional", data={"csrf": "t", "zones": A.DEMO_ZONES_CSV}).data,
         c.get("/overview").data]
outside = set()
for p in pages:
    outside |= set(re.findall(rb"(?:src|href)=[\"']https?://[^\"']+", p))
check("no outside links in pages (" + str(len(outside)) + " found)", not outside)
check("no 'github' text in pages", all(b"github" not in p.lower() for p in pages))

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
