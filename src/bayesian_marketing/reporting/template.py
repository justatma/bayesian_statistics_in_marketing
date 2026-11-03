"""The report's HTML template (Jinja2, autoescaped). Inline CSS, no external assets.

Kept as a Python string so it ships inside the package without package-data configuration.
Section headings and column labels are layout, not claims; prose a reader takes as a statement
comes from ``phrasing.yaml`` and ``guarantee_templates.yaml`` through ``render``.
"""

REPORT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marketing decision report · {{ client_id }}</title>
<style>
  :root {
    --ink: #1c1f24; --muted: #5b6270; --line: #d9dde3; --panel: #f6f7f9;
    --accent: #2f5d8a; --warn-bg: #fff4d6; --warn-ink: #6b4e00;
    --nk-bg: #eef1f6; --ok: #2e6b3a; --bad: #9b2c2c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #ffffff; color: var(--ink);
    font: 17px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  .watermark {
    background: var(--warn-bg); color: var(--warn-ink); border-bottom: 2px solid #e6c766;
    text-align: center; font-weight: 600; padding: 10px 16px; letter-spacing: .02em;
  }
  main { max-width: 1120px; margin: 0 auto; padding: 32px 40px 64px; }
  header.report { border-bottom: 1px solid var(--line); padding-bottom: 20px; margin-bottom: 8px; }
  h1 { font-size: 32px; line-height: 1.2; margin: 0 0 8px; }
  h2 { font-size: 23px; margin: 40px 0 12px; padding-top: 8px; }
  h3 { font-size: 18px; margin: 20px 0 8px; }
  .meta { color: var(--muted); font-size: 15px; margin: 0; }
  .meta code { font-size: 14px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0 4px; font-size: 16px; }
  caption { text-align: left; color: var(--muted); font-size: 14px; padding-bottom: 6px; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line);
           vertical-align: top; }
  th { background: var(--panel); font-weight: 600; font-size: 14px; color: var(--muted);
       text-transform: uppercase; letter-spacing: .03em; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .status { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 13px;
            font-weight: 600; }
  .status-estimable { background: #e3f1e6; color: var(--ok); }
  .status-marginal { background: var(--warn-bg); color: var(--warn-ink); }
  .status-below_floor { background: var(--nk-bg); color: var(--muted); }
  .caveat { color: var(--warn-ink); font-size: 14px; }
  .notice { color: var(--muted); font-size: 14px; }
  .plain { color: var(--muted); font-size: 14px; }
  .nk { background: var(--nk-bg); border-left: 4px solid var(--accent); padding: 14px 18px;
        margin: 12px 0; border-radius: 4px; }
  .rec { border: 1px solid var(--line); border-radius: 6px; padding: 16px 20px; margin: 12px 0; }
  .rec .action { font-weight: 700; font-size: 18px; }
  .narrative p { font-size: 18px; margin: 0 0 12px; }
  dl.kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 20px; margin: 8px 0; }
  dl.kv dt { color: var(--muted); }
  dl.kv dd { margin: 0; }
  .pass { color: var(--ok); font-weight: 600; }
  .fail { color: var(--bad); font-weight: 600; }
  footer { margin-top: 48px; color: var(--muted); font-size: 13px;
           border-top: 1px solid var(--line); padding-top: 12px; }
</style>
</head>
<body>
{% if watermark %}<div class="watermark" role="note">{{ watermark }}</div>{% endif %}
<main>
<header class="report">
  <h1>Marketing decision report</h1>
  <p class="meta">Client <code>{{ client_id }}</code> · run <code>{{ run_id }}</code>
     · {{ kind }} report{% if window %} · data {{ window }}{% endif %}</p>
</header>

{% if narrative %}
<section class="narrative" aria-labelledby="h-narrative">
  <h2 id="h-narrative">Summary</h2>
  {% for p in narrative %}<p>{{ p }}</p>{% endfor %}
</section>
{% endif %}

{% if recommendations %}
<section aria-labelledby="h-recs">
  <h2 id="h-recs">Recommendations</h2>
  {% for r in recommendations %}
  <article class="rec">
    <div class="action">{{ r.action }}</div>
    {% if r.allocation %}<p>Allocation: {{ r.allocation }}</p>{% endif %}
    <p>{{ r.guarantee }}</p>
    <dl class="kv">
      <dt>Decision basis</dt>
      <dd><span class="status status-{{ r.status }}">{{ r.status_label }}</span></dd>
      {% if r.benefit %}<dt>Expected benefit</dt><dd>{{ r.benefit }}</dd>{% endif %}
      {% if r.loss %}<dt>Expected loss</dt><dd>{{ r.loss }}</dd>{% endif %}
      <dt>Reversibility</dt><dd>{{ r.reversibility }}</dd>
      <dt>Approval</dt><dd>requires human approval</dd>
    </dl>
  </article>
  {% endfor %}
</section>
{% endif %}

{% if findings %}
<section aria-labelledby="h-findings">
  <h2 id="h-findings">What the data shows</h2>
  <table>
    <caption>Estimates with a 90% range. Each row says in plain words what was counted.</caption>
    <thead><tr>
      <th>Option</th><th>Measure</th><th class="num">Estimate</th><th class="num">90% range</th>
      <th>Status</th><th>What this counts</th>
    </tr></thead>
    <tbody>
    {% for f in findings %}
      <tr>
        <td><code>{{ f.entity }}</code></td>
        <td>{{ f.label }}</td>
        <td class="num">{{ f.estimate }}</td>
        <td class="num">{{ f.low }} to {{ f.high }}</td>
        <td><span class="status status-{{ f.status }}">{{ f.status_label }}</span>
            {% if f.caveat %}<div class="caveat">{{ f.caveat }}</div>{% endif %}</td>
        <td>{{ f.evidence }}<div class="plain">{{ f.route }}</div>
            {% for n in f.notices %}<div class="notice">{{ n }}</div>{% endfor %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</section>
{% endif %}

{% if comparisons %}
<section aria-labelledby="h-comp">
  <h2 id="h-comp">Comparisons</h2>
  {% for c in comparisons %}
  <table>
    <caption>Objective: {{ c.objective }} over the next {{ c.horizon }}.</caption>
    <thead><tr><th>Option</th><th class="num">Chance of being best</th>
      <th class="num">Expected value</th><th class="num">Expected loss if chosen</th></tr></thead>
    <tbody>
    {% for row in c.rows %}
      <tr><td><code>{{ row.option }}</code></td><td class="num">{{ row.p_best }}</td>
        <td class="num">{{ row.value }}</td><td class="num">{{ row.loss }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% endfor %}
</section>
{% endif %}

{% if not_knowable %}
<section aria-labelledby="h-nk">
  <h2 id="h-nk">Not knowable yet</h2>
  {% for nk in not_knowable %}
  <div class="nk">{{ nk.text }}
    {% for n in nk.notices %}<div class="notice">{{ n }}</div>{% endfor %}
  </div>
  {% endfor %}
</section>
{% endif %}

<section aria-labelledby="h-know">
  <h2 id="h-know">What we observed and what we did not</h2>
  <dl class="kv">
    <dt>Observed</dt><dd>{{ know.observed or "none" }}</dd>
    <dt>Platform-modeled</dt><dd>{{ know.platform_modeled or "none" }}</dd>
    <dt>Not knowable yet</dt><dd>{{ know.not_knowable or "none" }}</dd>
  </dl>
  {% if know.windows %}
  <table>
    <caption>Attribution windows</caption>
    <thead><tr><th>Source</th><th>Window</th></tr></thead>
    <tbody>
    {% for k, v in know.windows %}
      <tr><td>{{ k }}</td><td><code>{{ v }}</code></td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}
</section>

<section aria-labelledby="h-diag">
  <h2 id="h-diag">Appendix: model checks</h2>
  {% if conjugate_phrase %}<p>{{ conjugate_phrase }}</p>{% endif %}
  {% for d in diagnostics %}
  <h3>Check <code>{{ d.report_id }}</code> ({{ d.sampler }})
    {% if d.passed is none %}<span class="notice">not checked</span>
    {% elif d.passed %}<span class="pass">passed</span>
    {% else %}<span class="fail">failed</span>{% endif %}</h3>
  <table>
    <thead><tr><th>Check</th><th class="num">Value</th><th class="num">Threshold</th></tr></thead>
    <tbody>
    {% for row in d.rows %}
      <tr><td>{{ row[0] }}</td><td class="num">{{ row[1] }}</td>
        <td class="num">{{ row[2] }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% if d.seeds %}<p class="notice">Seeds: {{ d.seeds }}</p>{% endif %}
  {% endfor %}
</section>

<section aria-labelledby="h-prov">
  <h2 id="h-prov">Appendix: where each number comes from</h2>
  <table>
    <thead><tr><th>Quantity</th><th>Model</th><th>Fitted state</th><th>Data pulls</th></tr></thead>
    <tbody>
    {% for p in provenance %}
      <tr><td><code>{{ p.qid }}</code></td><td>{{ p.route }}</td><td><code>{{ p.state }}</code></td>
        <td><code>{{ p.pulls }}</code></td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>

<footer>Inputs hash <code>{{ inputs_hash }}</code></footer>
</main>
</body>
</html>
"""
