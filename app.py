from flask import Flask, jsonify, request, render_template_string
import mysql.connector

app = Flask(__name__)

# XAMPP's default MySQL login: user "root" with an empty password
DB = dict(host="localhost", port=3306, user="root", password="", database="bincomphptest")

ENTERED_BY = "Web Form"


def query(sql, params=()):
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------- shared look
STYLE = """
<style>
  body { font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; color: #222; }
  nav { background: #1d3557; padding: 14px 24px; }
  nav a { color: #cfd8e6; margin-right: 24px; text-decoration: none; font-weight: bold; }
  nav a.active { color: #fff; border-bottom: 2px solid #fff; padding-bottom: 4px; }
  .card { max-width: 560px; margin: 32px auto; background: #fff; padding: 28px;
          border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.08); }
  h1 { margin-top: 0; font-size: 22px; }
  h2 { font-size: 16px; margin: 26px 0 4px; }
  label { display: block; margin: 16px 0 6px; font-weight: bold; }
  select, input[type=text], input[type=number] {
    width: 100%; padding: 10px; font-size: 15px; border: 1px solid #ccc;
    border-radius: 6px; box-sizing: border-box; }
  select:disabled { background: #eee; }
  table { width: 100%; border-collapse: collapse; margin-top: 24px; }
  th, td { padding: 10px; border-bottom: 1px solid #e3e3e3; text-align: left; }
  th { background: #1d3557; color: #fff; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .msg { margin-top: 20px; color: #666; }
  .note { margin-top: 14px; color: #555; font-size: 14px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; margin-top: 10px; }
  .grid label { margin: 0 0 4px; font-weight: normal; font-size: 14px; color: #444; }
  button { margin-top: 26px; width: 100%; padding: 12px; font-size: 16px; font-weight: bold;
           background: #1d3557; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
  button:disabled { background: #8a97ab; cursor: wait; }
  .ok { margin-top: 18px; padding: 12px; background: #e6f4ea; color: #1e6b34; border-radius: 6px; }
  .err { margin-top: 18px; padding: 12px; background: #fdecea; color: #a12622; border-radius: 6px; }
</style>
"""


def nav(active):
    def cls(name):
        return ' class="active"' if name == active else ""
    return (
        "<nav>"
        '<a href="/"' + cls("pu") + ">Polling Unit Result</a>"
        '<a href="/lga"' + cls("lga") + ">LGA Total Result</a>"
        '<a href="/new"' + cls("new") + ">Enter New Result</a>"
        "</nav>"
    )


# ---------------------------------------------------------------- Question 1
@app.route("/")
def index():
    # The database only holds Delta State LGAs (state id 25)
    lgas = query("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    page = PAGE_PU.replace("__STYLE__", STYLE).replace("__NAV__", nav("pu"))
    return render_template_string(page, lgas=lgas)


@app.route("/api/wards")
def wards():
    rows = query(
        "SELECT ward_id, ward_name FROM ward WHERE lga_id = %s ORDER BY ward_name",
        (request.args["lga_id"],),
    )
    return jsonify(rows)


@app.route("/api/units")
def units():
    rows = query(
        """SELECT uniqueid,
                  COALESCE(NULLIF(polling_unit_name, ''),
                           NULLIF(polling_unit_number, ''),
                           CONCAT('Polling unit ', uniqueid)) AS name
           FROM polling_unit
           WHERE ward_id = %s AND lga_id = %s
           ORDER BY name""",
        (request.args["ward_id"], request.args["lga_id"]),
    )
    return jsonify(rows)


@app.route("/api/results")
def results():
    # Results are linked through polling_unit.uniqueid, NOT polling_unit_id
    rows = query(
        """SELECT party_abbreviation AS party, party_score AS score
           FROM announced_pu_results
           WHERE polling_unit_uniqueid = %s
           ORDER BY party_score DESC""",
        (request.args["uniqueid"],),
    )
    return jsonify(rows)


# ---------------------------------------------------------------- Question 2
@app.route("/lga")
def lga_page():
    lgas = query("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    page = PAGE_LGA.replace("__STYLE__", STYLE).replace("__NAV__", nav("lga"))
    return render_template_string(page, lgas=lgas)


@app.route("/api/lga_total")
def lga_total():
    lga_id = request.args["lga_id"]
    # Sum the polling-unit results ourselves. We do NOT use announced_lga_results.
    totals = query(
        """SELECT r.party_abbreviation AS party, SUM(r.party_score) AS total
           FROM announced_pu_results r
           JOIN polling_unit p ON p.uniqueid = r.polling_unit_uniqueid
           WHERE p.lga_id = %s
           GROUP BY r.party_abbreviation
           ORDER BY total DESC""",
        (lga_id,),
    )
    counted = query(
        """SELECT COUNT(DISTINCT r.polling_unit_uniqueid) AS n
           FROM announced_pu_results r
           JOIN polling_unit p ON p.uniqueid = r.polling_unit_uniqueid
           WHERE p.lga_id = %s""",
        (lga_id,),
    )
    return jsonify({"totals": totals, "units": counted[0]["n"]})


# ---------------------------------------------------------------- Question 3
@app.route("/new")
def new_page():
    lgas = query("SELECT lga_id, lga_name FROM lga WHERE state_id = 25 ORDER BY lga_name")
    parties = query("SELECT partyid FROM party ORDER BY id")
    page = PAGE_NEW.replace("__STYLE__", STYLE).replace("__NAV__", nav("new"))
    return render_template_string(page, lgas=lgas, parties=parties)


def fail(message, code=400):
    return jsonify(ok=False, error=message), code


@app.route("/api/save", methods=["POST"])
def save():
    data = request.get_json(silent=True) or {}

    # ---- validate the input
    try:
        lga_id = int(data.get("lga_id"))
        ward_id = int(data.get("ward_id"))
    except (TypeError, ValueError):
        return fail("Please choose a local government and a ward.")

    name = (data.get("name") or "").strip()
    if not name:
        return fail("Please enter the polling unit name.")
    if len(name) > 50:
        return fail("The polling unit name is too long (50 characters maximum).")

    if not query("SELECT 1 FROM ward WHERE ward_id = %s AND lga_id = %s", (ward_id, lga_id)):
        return fail("That ward does not belong to the chosen local government.")

    scores = data.get("scores") or {}
    clean = []
    for p in query("SELECT partyid FROM party ORDER BY id"):
        pid = p["partyid"]
        try:
            value = int(scores.get(pid))
        except (TypeError, ValueError):
            return fail("Enter a whole-number score for " + pid + ".")
        if value < 0:
            return fail("The score for " + pid + " cannot be negative.")
        # party_abbreviation is CHAR(4), so LABOUR is stored as LABO (as in the existing data)
        clean.append((pid[:4], value))

    # ---- save: one new polling unit + one result row per party, all or nothing
    ip = request.remote_addr or "127.0.0.1"
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor()

        # polling_unit_id is required and has no default: use the next number in this ward
        cur.execute(
            "SELECT COALESCE(MAX(polling_unit_id), 0) + 1 FROM polling_unit "
            "WHERE ward_id = %s AND lga_id = %s",
            (ward_id, lga_id),
        )
        next_pu_id = cur.fetchone()[0]

        # uniquewardid is optional; fill it if the ward table has it
        unique_ward = None
        try:
            cur.execute(
                "SELECT uniqueid FROM ward WHERE ward_id = %s AND lga_id = %s LIMIT 1",
                (ward_id, lga_id),
            )
            row = cur.fetchone()
            if row:
                unique_ward = row[0]
        except mysql.connector.Error:
            unique_ward = None

        cur.execute(
            """INSERT INTO polling_unit
                   (polling_unit_id, ward_id, lga_id, uniquewardid, polling_unit_name,
                    entered_by_user, date_entered, user_ip_address)
               VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)""",
            (next_pu_id, ward_id, lga_id, unique_ward, name, ENTERED_BY, ip),
        )
        new_uniqueid = cur.lastrowid

        cur.executemany(
            """INSERT INTO announced_pu_results
                   (polling_unit_uniqueid, party_abbreviation, party_score,
                    entered_by_user, date_entered, user_ip_address)
               VALUES (%s, %s, %s, %s, NOW(), %s)""",
            [(str(new_uniqueid), abbr, score, ENTERED_BY, ip) for abbr, score in clean],
        )
        conn.commit()
    except mysql.connector.Error as e:
        conn.rollback()
        return fail("Database error: " + str(e), 500)
    finally:
        conn.close()

    return jsonify(ok=True, uniqueid=new_uniqueid, name=name, total=sum(s for _, s in clean))


# ---------------------------------------------------------------- page templates
PAGE_PU = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polling Unit Results</title>
__STYLE__
</head>
<body>
__NAV__
<div class="card">
  <h1>Result for a Polling Unit</h1>

  <label for="lga">Local Government</label>
  <select id="lga">
    <option value="">-- Select LGA --</option>
    {% for l in lgas %}
    <option value="{{ l.lga_id }}">{{ l.lga_name }}</option>
    {% endfor %}
  </select>

  <label for="ward">Ward</label>
  <select id="ward" disabled><option value="">-- Select ward --</option></select>

  <label for="unit">Polling Unit</label>
  <select id="unit" disabled><option value="">-- Select polling unit --</option></select>

  <div id="output" class="msg">Pick an LGA, ward and polling unit to see the result.</div>
</div>

<script>
const lga = document.getElementById("lga");
const ward = document.getElementById("ward");
const unit = document.getElementById("unit");
const output = document.getElementById("output");

function reset(select, text) {
  select.innerHTML = '<option value="">' + text + '</option>';
  select.disabled = true;
}

function fill(select, rows, valueKey, labelKey, placeholder) {
  select.innerHTML = '<option value="">' + placeholder + '</option>';
  rows.forEach(r => {
    const o = document.createElement("option");
    o.value = r[valueKey];
    o.textContent = r[labelKey];
    select.appendChild(o);
  });
  select.disabled = rows.length === 0;
}

lga.addEventListener("change", async () => {
  reset(ward, "-- Select ward --");
  reset(unit, "-- Select polling unit --");
  output.className = "msg";
  output.textContent = "Pick an LGA, ward and polling unit to see the result.";
  if (!lga.value) return;
  const res = await fetch("/api/wards?lga_id=" + lga.value);
  fill(ward, await res.json(), "ward_id", "ward_name", "-- Select ward --");
});

ward.addEventListener("change", async () => {
  reset(unit, "-- Select polling unit --");
  output.className = "msg";
  output.textContent = "Pick a polling unit to see the result.";
  if (!ward.value) return;
  const res = await fetch("/api/units?ward_id=" + ward.value + "&lga_id=" + lga.value);
  const rows = await res.json();
  fill(unit, rows, "uniqueid", "name", "-- Select polling unit --");
  if (rows.length === 0) output.textContent = "No polling units found under this ward.";
});

unit.addEventListener("change", async () => {
  if (!unit.value) return;
  const res = await fetch("/api/results?uniqueid=" + unit.value);
  const rows = await res.json();
  if (rows.length === 0) {
    output.className = "msg";
    output.textContent = "No results have been recorded for this polling unit.";
    return;
  }
  let total = 0;
  let html = "<table><tr><th>Party</th><th class='num'>Score</th></tr>";
  rows.forEach(r => {
    total += Number(r.score);
    html += "<tr><td>" + r.party + '</td><td class="num">' + r.score + "</td></tr>";
  });
  html += '<tr><th>Total</th><th class="num">' + total + "</th></tr></table>";
  output.className = "";
  output.innerHTML = html;
});
</script>
</body>
</html>
"""

PAGE_LGA = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LGA Total Result</title>
__STYLE__
</head>
<body>
__NAV__
<div class="card">
  <h1>Total Result for a Local Government</h1>

  <label for="lga">Local Government</label>
  <select id="lga">
    <option value="">-- Select LGA --</option>
    {% for l in lgas %}
    <option value="{{ l.lga_id }}">{{ l.lga_name }}</option>
    {% endfor %}
  </select>

  <div id="output" class="msg">Pick an LGA to see the summed result of all its polling units.</div>
</div>

<script>
const lga = document.getElementById("lga");
const output = document.getElementById("output");

lga.addEventListener("change", async () => {
  if (!lga.value) {
    output.className = "msg";
    output.textContent = "Pick an LGA to see the summed result of all its polling units.";
    return;
  }
  const res = await fetch("/api/lga_total?lga_id=" + lga.value);
  const data = await res.json();
  if (data.totals.length === 0) {
    output.className = "msg";
    output.textContent = "No polling unit results have been recorded for this LGA.";
    return;
  }
  let grand = 0;
  let html = "<table><tr><th>Party</th><th class='num'>Total Score</th></tr>";
  data.totals.forEach(r => {
    grand += Number(r.total);
    html += "<tr><td>" + r.party + '</td><td class="num">' + r.total + "</td></tr>";
  });
  html += '<tr><th>Grand Total</th><th class="num">' + grand + "</th></tr></table>";
  html += '<div class="note">Summed from ' + data.units + " polling unit(s) with recorded results.</div>";
  output.className = "";
  output.innerHTML = html;
});
</script>
</body>
</html>
"""

PAGE_NEW = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enter New Result</title>
__STYLE__
</head>
<body>
__NAV__
<div class="card">
  <h1>Enter Results for a New Polling Unit</h1>

  <label for="lga">Local Government</label>
  <select id="lga">
    <option value="">-- Select LGA --</option>
    {% for l in lgas %}
    <option value="{{ l.lga_id }}">{{ l.lga_name }}</option>
    {% endfor %}
  </select>

  <label for="ward">Ward</label>
  <select id="ward" disabled><option value="">-- Select ward --</option></select>

  <label for="name">New Polling Unit Name</label>
  <input type="text" id="name" maxlength="50" placeholder="e.g. Market Square 1">

  <h2>Party Scores</h2>
  <div class="grid">
    {% for p in parties %}
    <div>
      <label for="score-{{ p.partyid }}">{{ p.partyid }}</label>
      <input type="number" min="0" step="1" id="score-{{ p.partyid }}"
             data-party="{{ p.partyid }}" placeholder="0">
    </div>
    {% endfor %}
  </div>

  <button id="save">Save Result</button>
  <div id="status"></div>
</div>

<script>
const lga = document.getElementById("lga");
const ward = document.getElementById("ward");
const nameBox = document.getElementById("name");
const saveBtn = document.getElementById("save");
const statusBox = document.getElementById("status");
const scoreBoxes = document.querySelectorAll("input[data-party]");

function show(kind, text) {
  statusBox.className = kind;
  statusBox.textContent = text;
}

lga.addEventListener("change", async () => {
  ward.innerHTML = '<option value="">-- Select ward --</option>';
  ward.disabled = true;
  if (!lga.value) return;
  const res = await fetch("/api/wards?lga_id=" + lga.value);
  const rows = await res.json();
  rows.forEach(r => {
    const o = document.createElement("option");
    o.value = r.ward_id;
    o.textContent = r.ward_name;
    ward.appendChild(o);
  });
  ward.disabled = rows.length === 0;
});

saveBtn.addEventListener("click", async () => {
  // quick checks in the browser so the user gets friendly messages
  if (!lga.value || !ward.value) return show("err", "Please choose a local government and a ward.");
  if (!nameBox.value.trim()) return show("err", "Please enter the polling unit name.");

  const scores = {};
  for (const box of scoreBoxes) {
    if (box.value === "") return show("err", "Please enter a score for " + box.dataset.party + " (use 0 if none).");
    scores[box.dataset.party] = box.value;
  }

  saveBtn.disabled = true;
  show("", "");
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lga_id: lga.value,
        ward_id: ward.value,
        name: nameBox.value,
        scores: scores
      })
    });
    const data = await res.json();
    if (data.ok) {
      show("ok", "Saved! '" + data.name + "' was added (polling unit id " + data.uniqueid +
                 ", total votes " + data.total + ").");
      nameBox.value = "";
      scoreBoxes.forEach(b => b.value = "");
    } else {
      show("err", data.error);
    }
  } catch (e) {
    show("err", "Could not reach the server. Is the app still running?");
  }
  saveBtn.disabled = false;
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
