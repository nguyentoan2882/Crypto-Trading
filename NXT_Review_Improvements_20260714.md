# NXT v3.5 Latest — Verify & Đề xuất cải thiện (2026-07-14)

Nguồn: `latest/NXT_Latest_NXT35_BTC_BNB_SOL_FundingAdjusted_20K.json` (253 trades, 2020-05 → 2026-05, BTC/BNB/SOL).

## 1. Kết quả verify

Tính lại toàn bộ từ trade-level JSON, đối chiếu với `NXT_Latest_Summary.md`:

| Chỉ số | Summary | Tính lại | Khớp |
|---|---|---|---|
| Trades | 253 | 253 | ✅ |
| Net R (funding-adj) | 159.74R | 159.74R | ✅ |
| Win rate | 45.45% | 45.45% | ✅ |
| Profit factor | 2.66 | 2.66 | ✅ |
| Max DD | −8.67R | −8.67R | ✅ |

Số liệu trung thực, cost + funding được tách bạch đúng, không double-count. Hai điểm cần lưu ý khi đọc kết quả:

- **Phụ thuộc đuôi phải rất nặng**: top 5 trades = 42% tổng R, top 10 = 63%, top 20 = 88%. Hệ thống sống nhờ vài runner lớn (best 20.9R) — mọi filter mới phải kiểm tra không cắt nhầm nhóm này.
- Win rate 45.45% là số funding-adjusted; số gốc là 43.87% (funding đẩy 4 trade từ lỗ nhẹ sang lãi nhẹ). Nên dùng nhất quán một định nghĩa khi so biến thể.

## 2. Chẩn đoán chop (dữ liệu trade-level)

- 75 stop-loss exits = −77.9R; trong đó **60 trades lỗ có hold ≤ 3 ngày = −50.7R** — chữ ký chop kinh điển: vào theo flip, bị quét trong vài nến.
- SHORT là nguồn kém hiệu quả chính: **106 trades (42%) chỉ tạo 20.3R (13% tổng R), PF 1.51** vs LONG PF 3.31–3.99. Runner SHORT avg 0.89R (max 3.99R) vs runner LONG avg 2.81R — sóng giảm crypto V-shape, SSL14 flip thoát quá chậm.
- Năm chop 2022: 36 trades, WR 33%, −0.25R. Các tháng tệ nhất đều là cụm whipsaw: 2022-03 (−5.3R), 2023-05 (−3.8R), 2024-10 (−3.5R). Chuỗi thua dài nhất: 8 trade liên tiếp; BNB có chuỗi 6 lỗ (04–05/2024).
- Primary LONG với **RSI 55–60**: 38 trades, avg chỉ 0.07R (vs RSI 50–55: avg 1.06R) — vào khi đà đã chạy nửa đường, dễ đúng đỉnh pullback.
- Phản chứng quan trọng: re-entry ≤2 ngày sau lỗ **có lời** (+0.97R avg, 73 lần); flip-flop đổi chiều sau lỗ cũng dương (+70R, WR 51%). → **Không nên thêm cooldown thô** — chop phải xử lý bằng chất lượng entry, không phải bằng khóa thời gian.

## 3. Ít nhất 5 điểm cải thiện (đã backup bằng số liệu)

### 3.1. Nâng cấp anti-reversal: block SHORT sau khi runner LONG thoát lỗ *(tăng cả R lẫn WR — ưu tiên số 1)*
Grid `nxt35_post_bull_chop_filters` đã chạy sẵn: `block_short_after_losing_long_runner_exit` → **164.5R (+4.75R), WR 46%, PF 2.83**, bỏ 10 trade chop (DD −8.95R, xấu hơn 0.28R không đáng kể). Đây là mở rộng tự nhiên của rule anti-immediate-reversal hiện tại (hiện chỉ block khi runner thoát **lãi** ≥0.5R) và là biến thể duy nhất trong grid tăng đồng thời totalR + WR. Đề xuất promote.

### 3.2. Siết Primary SHORT: yêu cầu close < EMA50 *(giảm chop/DD, giữ ~98% R)*
Đã test: `primary_short_requires_close_below_ema50` → 226 trades, 156.0R (−3.7R), **DD −6.98R (giảm 19% DD)**, PF 2.79. Loại 27 lệnh short "bắt dao" khi giá vẫn trên EMA50 (chính là nhóm short-trong-uptrend gây chop 2023–2025: SHORT 2025 chỉ +3.05R/22 trades, WR 36%). Nếu ưu tiên PF hơn: biến thể EMA20<EMA50 cho PF 3.06.

### 3.3. SHORT half-risk (0.5R) *(giảm chop theo trọng số vốn)*
Đã test: PF 2.66 → **2.96**, DD −8.67 → **−7.68R**, portfolio-cap DD 16.2% → 14.9%, đổi lấy −10.2R totalR. SHORT đóng góp R/trade chỉ 0.19R vs LONG 0.95R nên giảm nửa risk cho short là cách rẻ nhất để hạ biến động chuỗi lỗ (chuỗi 8 lỗ liên tiếp có nhiều short). Có thể kết hợp 3.2 + 3.3 thay vì bỏ hẳn short (no-short đã test: DD tăng lên −10.26R do mất hedge 2022 — không nên).

### 3.4. Lọc Primary LONG vùng RSI 55–60 *(phát hiện mới từ phân tích này — cần walk-forward trước khi promote)*
38 trades Primary LONG có RSI entry 55–60 chỉ đạt avg 0.07R, WR 39.5%. Loại bỏ: totalR 157.1R (−2.7R), **WR 46.5%, PF 3.01, DD −6.85R (giảm 21%)**. Logic: SSL flip + RSI đã 55–60 nghĩa là cross EMA20 muộn, entry đúng lúc đà ngắn hạn cạn. Cảnh báo overfit: bucket 60–70 (n=5) lại rất tốt, tức quan hệ không đơn điệu — cần chạy walk-forward giống quy trình đã làm cho Early-BE sweep trước khi đưa vào latest.

### 3.5. Đổi cơ chế thoát runner cho SHORT: TP2 cố định thay vì chờ SSL flip *(tăng R từ 42% số lệnh đang gần hòa vốn)*
Runner SHORT avg 0.89R và **cao nhất chỉ 3.99R** trong 49 lần — tức SSL14 flip trả lại gần hết lợi nhuận sóng giảm (down-move crypto dốc, đảo nhanh). Đề xuất test: sau TP1, runner SHORT chốt tại TP2 cố định 4–5 ATR hoặc trail bằng chandelier 3 ATR (script `test_nxt32_chandelier_exit.py` tái sử dụng được), giữ nguyên cơ chế SSL flip cho LONG (avg 2.81R, đang làm tốt việc ôm trend dài).

### 3.6. (Bonus) Bộ lọc chất lượng nến tín hiệu cho nhóm lỗ nhanh ≤3 ngày
−50.7R nằm ở 60 lệnh chết trong ≤3 nến. Hướng đã có script (`test_nxt35_signal_candle_range_filter.py`): yêu cầu nến tín hiệu range ≥ 0.8–1.0 ATR **và** close nằm ở 1/3 trên (LONG) — flip bằng nến yếu giữa vùng nhiễu là mẫu số chung của các cụm 2022-03, 2024-04/05 (BNB 6 lỗ liên tiếp). Chạy grid kèm ràng buộc "không giảm quá 5% tổng R" để không cắt runner.

### Những gì KHÔNG nên làm (đã có bằng chứng âm)
- Cooldown/re-entry guard thô: re-entry sau lỗ đang +0.97R avg.
- Regime throttle theo trend-quality score hoặc SSL flip-density: đã test, mất 7–33R mà DD cải thiện không tương xứng.
- Bỏ hẳn SHORT: mất hedge 2022, DD tăng lên −10.26R.

## 4. Gói đề xuất tổng hợp

Bước 1 (promote ngay, đã đủ bằng chứng): 3.1 + 3.2. Ước tính hiệu ứng gộp cần chạy lại chuỗi (hai rule tương tác), kỳ vọng ~158–162R, WR ~46%, DD ~−7R.
Bước 2 (test thêm): 3.4 walk-forward, 3.5 grid TP2 short, 3.6 grid nến tín hiệu.
Bước 3 (tùy khẩu vị rủi ro): 3.3 nếu mục tiêu là hạ DD portfolio-cap dưới 15%.

*Lưu ý: đây là phân tích kỹ thuật trên dữ liệu backtest, không phải khuyến nghị đầu tư; kết quả quá khứ không đảm bảo tương lai, đặc biệt với hệ thống phụ thuộc 63% R vào 10 trades.*
