# Core V1 architecture notes

Tài liệu này ghi lại kiến trúc **đã triển khai và đã qua C9 release gate**. `overview.md`
vẫn là phạm vi sản phẩm; tài liệu này là nguồn tham chiếu cho presentation layer khi bắt
đầu xây UI.

## Dependency direction và composition

```text
PySide6 presentation (chưa triển khai)
              ↓
ApplicationFacade + immutable read models/events
              ↓
application use cases/managers/ports → domain
              ↑
yt-dlp / FFmpeg / SQLite / JSON / filesystem adapters

bootstrap.py chọn và nối toàn bộ concrete adapters
```

- Domain và application không import Qt, yt-dlp, SQLite hoặc subprocess.
- `ApplicationFacade` là API duy nhất presentation V1 cần gọi. UI dùng opaque
  configuration/preset/task IDs, command results, read models và subscription; không gọi
  repository, queue, yt-dlp hay FFmpeg trực tiếp.
- Event subscription là thread-agnostic. Qt bridge tương lai phải marshal callback sang UI
  thread trước khi chạm widget.
- `bootstrap.py` là composition root duy nhất. Không dùng service locator hoặc mutable global.

## Workflow và state ownership

```text
analyze → configure → queued → downloading → processing → completed
                              ↘ failed/cancelled
                     restart ↖ interrupted
```

- Analysis là operation tạm và hỗ trợ cooperative cancellation; task durable chỉ được tạo
  khi enqueue.
- `DownloadRequest` immutable giữ URL đã validate, title normalized, preset và output
  directory để retry không đọc lại widget state.
- `DownloadManager` sở hữu transition của download; `ProcessingManager` sở hữu settle của
  processing. Worker/adapters chỉ trả typed outcomes và progress snapshots.
- `Completed` chỉ được commit sau khi processor đã verify và publish final output. Download
  100% vẫn là `Processing` nếu còn finalize.
- Mọi mutation được commit repository trước khi publish event. Event/subscriber failure không
  rollback durable state; client refresh read model thay vì lặp command mù quáng.
- Queue FIFO dùng bounded thread pool; một slot bao trọn download và processing. Failure hoặc
  callback lỗi của một task không dừng scheduler và mọi exit path giải phóng slot.

## Persistence, retry và recovery

- SQLite persist task request, attempts, terminal failure code/category, timestamps,
  interrupted stage và final output identity. Speed, ETA và progress snapshot là telemetry,
  không phải durable facts.
- History là projection của terminal attempts, không có bảng/source of truth thứ hai.
- Startup đổi durable `Downloading`, `Processing` hoặc `Paused` còn sót thành `Interrupted`
  trước khi facade phục vụ UI. Recovery idempotent.
- Resume download cần partial file không rỗng. Resume/retry processing cần manifest relative
  và toàn bộ input còn hợp lệ. Thiếu staging trả stable `resume.*`/`retry.*` code; full restart
  là action tường minh và tạo attempt mới.
- Shutdown ngừng admission, giữ pending task ở `Queued`, persist active task thành
  `Interrupted`, gửi cooperative cancellation rồi bounded-wait. Late worker không được ghi đè
  interrupted state.

## Files, processes và failure semantics

- yt-dlp tải vào staging riêng theo task/attempt, giữ partial khi cancel/failure, không nhận
  custom arguments hoặc browser cookies ở V1.
- Format selector không dùng provider format ID và loại format xác định `has_drm=true`; field
  DRM bị extractor bỏ trống được coi là chưa xác định (`!=?true`), không bị loại nhầm.
- Process runner luôn nhận argument tuple, `shell=False`, capture UTF-8 an toàn, timeout,
  cooperative cancel và reap child process.
- FFmpeg tạo temporary sibling, FFprobe verify trước publish, rồi publish atomic khi có thể.
  Conflict mặc định `rename`; `replace` chỉ chạy khi explicit. App chỉ xóa file do chính attempt
  sở hữu theo cleanup policy.
- Public failures chỉ gồm enum category, stable lowercase code và retryable flag.
  `UserMessage` ánh xạ sang localization keys và suggested action (`retry`,
  `retry_processing`, `choose_folder`, `configure_dependency`, `view_details`). Raw engine
  exception chỉ tồn tại dưới dạng chained cause trong adapter diagnostic boundary.

## Privacy và diagnostics

- Credential trong authority, token/cookie/signature query/fragment và signed cloud URL bị
  từ chối trước event hoặc persistence.
- Application log dùng allowlist ở serialization boundary. Raw message arguments, exception,
  traceback, arbitrary extras, cookie/token và local path không được serialize.
- Presentation có thể hiển thị output path trong task read model vì đây là dữ liệu người dùng
  cần để mở file. Khi xây `Copy diagnostics`, chỉ serialize stable IDs/codes/stage/timestamp;
  không serialize chained cause, source URL, output path hoặc settings nếu chưa redaction.

## C9 release evidence (2026-09-07)

- Offline gate dùng fake analyzer/downloader/processor với SQLite thật trong temporary
  directory, chạy `analyze → queue → download → process → persist → reopen` qua facade.
- Multi-task integration bao phủ success, download failure, processing failure, queued cancel,
  active cancel và restart giữa download; kiểm tra attempt history và worker cleanup.
- Controlled Python child process bao phủ success/stdout, stderr + nonzero exit, timeout,
  cancellation và executable không tồn tại.
- Live smoke là opt-in qua `MEDIAFLOW_SMOKE_URL`, không hard-code URL vào test suite. Lần xác
  nhận C9 dùng [Sintel trailer trên Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Sintel_trailer-1080p.ogv)
  ([CC BY 3.0 theo Blender/Durian](https://durian.blender.org/sharing/)) và tải thành công một
  artifact không rỗng. Engine: yt-dlp `2026.08.19`; FFmpeg và FFprobe `not_found` trên máy gate.
  Vì vậy live processing chưa được chạy trên máy này; processor/verification được xác nhận bằng
  fake process, temporary filesystem và subprocess integration. UI phải hiển thị dependency
  status và chỉ yêu cầu cấu hình FFmpeg khi preset thực sự cần nó.
- Quality gate cuối: Ruff format/lint, mypy strict, lock/dependency consistency và `309 passed,
  1 deselected` trong default offline suite; opt-in live smoke `1 passed`.

Default pytest suite luôn offline và sockets-disabled. Live URL là input do người chạy cung
cấp, không phải fixture hay release dependency.
