from __future__ import annotations

import html


def render_quantity_calculator() -> str:
    """Return an in-memory calculator with no form, named field or storage/network API."""
    return """
<dialog id="quantity-calculator" class="qty-dialog">
  <section class="qty-panel">
    <header><h2>Tính quantity</h2><button type="button" id="qty-close">Đóng</button></header>
    <p>Entry và Stop được khóa theo tín hiệu. Equity, Risk % và kết quả chỉ tồn tại trong popup này.</p>
    <div><b id="qty-signal">-</b></div>
    <label>Equity USD<input id="qty-equity" type="number" min="0" step="any" autocomplete="off"></label>
    <label>Risk %<input id="qty-risk" type="number" min="0" step="any" autocomplete="off"></label>
    <label>Entry<input id="qty-entry" type="number" readonly></label>
    <label>Stop<input id="qty-stop" type="number" readonly></label>
    <button type="button" id="qty-calculate">Tính</button>
    <p id="qty-error" role="alert"></p>
    <dl><dt>Risk USD</dt><dd id="qty-risk-usd">-</dd><dt>Risk/unit</dt><dd id="qty-risk-unit">-</dd><dt>Raw quantity</dt><dd id="qty-raw">-</dd><dt>Notional USD</dt><dd id="qty-notional">-</dd><dt>30% / 10% / 60%</dt><dd id="qty-split">-</dd></dl>
  </section>
</dialog>
<script>
(()=>{const d=document.getElementById('quantity-calculator'),v=id=>Number(document.getElementById(id).value),s=(id,x)=>document.getElementById(id).textContent=x,f=x=>Number(x).toLocaleString('en-US',{maximumFractionDigits:8}),usd=x=>Number(x).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),clear=()=>{document.getElementById('qty-equity').value='';document.getElementById('qty-risk').value='';['qty-risk-usd','qty-risk-unit','qty-raw','qty-notional','qty-split'].forEach(id=>s(id,'-'));s('qty-error','')};document.querySelectorAll('.signal-quantity-button').forEach(b=>b.addEventListener('click',()=>{clear();document.getElementById('qty-entry').value=b.dataset.entry;document.getElementById('qty-stop').value=b.dataset.stop;s('qty-signal',b.dataset.signal);d.showModal()}));document.getElementById('qty-calculate').addEventListener('click',()=>{const equity=v('qty-equity'),riskPct=v('qty-risk'),entry=v('qty-entry'),stop=v('qty-stop'),riskUnit=Math.abs(entry-stop);if(!(equity>0&&riskPct>0&&entry>0&&stop>0&&riskUnit>0)){s('qty-error','Equity, Risk %, Entry và Stop phải hợp lệ.');return}const riskUsd=equity*riskPct/100,qty=riskUsd/riskUnit,notional=qty*entry;s('qty-risk-usd','$'+f(riskUsd));s('qty-risk-unit',f(riskUnit));s('qty-raw',f(qty));s('qty-notional','$'+usd(notional));s('qty-split',f(qty*.3)+' / '+f(qty*.1)+' / '+f(qty*.6))});document.getElementById('qty-close').addEventListener('click',()=>{clear();d.close()});})();
</script>
""".strip()


def signal_button(signal_id: str, entry: float, stop: float) -> str:
    return (
        '<button type="button" class="signal-quantity-button" '
        f'data-signal="{html.escape(signal_id)}" data-entry="{float(entry)}" data-stop="{float(stop)}">Tính quantity</button>'
    )
