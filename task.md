# MediaFlow — Kế hoạch triển khai Core

> **Cập nhật:** 2026-09-07
>
> **Trạng thái tổng thể:** `IN_PROGRESS`
>
> **Giai đoạn hiện tại:** `C6 hoàn thành — tiếp theo C7 (chưa triển khai)`
>
> Phạm vi: Core V1 cho Windows Desktop; chưa bao gồm triển khai widget/theme UI.

## 1. Cách sử dụng file này

- `[ ]`: chưa hoàn thành; `[x]`: đã hoàn thành.
- Chỉ đánh dấu hoàn thành khi đạt toàn bộ acceptance criteria của task hoặc milestone.
- Mỗi phiên làm việc cập nhật `Giai đoạn hiện tại`, checkbox liên quan và `Nhật ký tiến độ`.
- Khi bị chặn, ghi nguyên nhân, bằng chứng và quyết định cần có vào `Blockers`; không đánh dấu task hoàn thành một phần.
- Mỗi thay đổi core phải có test ở tầng thấp nhất phù hợp. Live download không phải điều kiện duy nhất để xác nhận đúng.
- Không đưa `.agents/`, `AGENTS.md`, credential, cookie, token, database/log/runtime data vào Git.

## 2. Mục tiêu Core V1

Core V1 hoàn thành khi có thể chạy luồng sau qua application API mà không phụ thuộc UI:

```text
Analyze URL
  → normalize metadata/formats
  → create immutable download request
  → enqueue task
  → download with observable progress
  → process with FFmpeg when required
  → verify/finalize output
  → persist terminal state/history
  → recover truthfully after restart
```

Các yêu cầu bắt buộc:

- Domain và application layer không import PySide6, yt-dlp, FFmpeg hay SQLite.
- UI không giữ task state chính và không gọi trực tiếp engine.
- Một task lỗi không làm dừng hoặc làm hỏng task khác.
- `100% downloaded` chưa phải `Completed` nếu còn merge/convert/finalize.
- Không ghi đè file, xóa file hoặc sử dụng browser session một cách ngầm định.
- Log và persistence không chứa cookie, token, credential hoặc authorization header.

## 3. Kiến trúc đích

```text
src/mediaflow/
├── domain/                 # Model, value object, state rules, errors
├── application/            # Use case, task/queue orchestration, ports
├── infrastructure/
│   ├── downloader/         # yt-dlp adapters
│   ├── media/              # FFmpeg/FFprobe process adapters
│   ├── persistence/        # SQLite repositories + migrations
│   ├── settings/           # Local settings adapter
│   └── filesystem/         # Filename, conflict, output finalization
├── presentation/           # Thêm ở giai đoạn UI; Qt adapters/widgets
└── bootstrap.py            # Composition root

tests/
├── unit/
├── integration/
└── smoke/                  # Không chạy mặc định; có thể dùng mạng/tool thật
```

Dependency direction:

```text
presentation → application → domain
infrastructure ──────────────┘
bootstrap wires concrete adapters to application ports
```

Không tạo sẵn module rỗng chỉ để khớp cây thư mục. Thư mục xuất hiện khi milestone đầu tiên thực sự cần nó.

## 4. Quyết định nền tảng

| ID | Quyết định | Lý do |
|---|---|---|
| D-001 | Tách `AnalysisOperation` khỏi `DownloadTask` | Analyze/Configure là trạng thái tạm của Home; task bền vững chỉ bắt đầu khi được đưa vào queue. |
| D-002 | Retry tạo attempt mới nhưng giữ nguyên immutable `DownloadRequest` | Giữ được ý định người dùng và lịch sử lỗi, không đọc lại state từ widget. |
| D-003 | History là projection của task/attempt/output đã persisted | Tránh hai nguồn dữ liệu task và history bị lệch nhau. |
| D-004 | Worker chỉ phát typed event/snapshot; Task Manager là nơi duy nhất đổi state | Tránh race condition và UI/worker tự gán status tùy ý. |
| D-005 | Adapter nhận/trả model chuẩn hóa, không phát tán raw yt-dlp dict hoặc stderr | Cô lập dependency thay đổi thường xuyên và giữ application API ổn định. |
| D-006 | Pause chỉ xuất hiện sau khi semantics resume từ partial file được kiểm chứng | Không hứa một action mà backend không thực hiện đáng tin cậy. |
| D-007 | Mọi task mutation dùng optimistic aggregate replacement; repository commit trước khi publish event | Repository luôn là nguồn state có thẩm quyền. Event delivery lỗi không rollback state; caller phải refresh trước khi thử lại command. |
| D-008 | SQLite chỉ persist durable task facts và `updated_at` checkpoint; không persist progress snapshot, speed hoặc ETA | Giữ task/history phục hồi được nhưng tránh biến telemetry tần suất cao thành write amplification hoặc optimistic conflict giả. |
| D-009 | Analyze cancellation là cooperative; `socket_timeout` giới hạn từng I/O, không phải hard deadline toàn operation | Phản ánh đúng giới hạn Python API của yt-dlp, không hứa khả năng cưỡng bức dừng mà adapter không bảo đảm. |
| D-010 | Preset availability là application contract và phải hợp lệ trước enqueue; yt-dlp selector vẫn là infrastructure detail | UI nhận warning/choice typed, task không hợp lệ không lọt vào persistence, và provider format ID không vượt adapter boundary. |
| D-011 | Queue dùng FIFO với bounded thread pool; `DownloadManager` là state owner duy nhất và quyết định kết quả atomically với cancel | Giữ scheduling dự đoán được, không chạy engine trên UI/caller thread, không vượt concurrency và để cancel thắng nếu đã được yêu cầu trước lúc settle. |
| D-012 | Mỗi attempt tải vào staging riêng, không overwrite, giữ partial khi cancel/failure và chuyển `DOWNLOADING → PROCESSING` sau download thành công | Cho phép resume/retry an toàn; C6 vẫn phải xử lý, finalize và verify trước khi task được phép `COMPLETED`. yt-dlp auto-merge bị tắt và selector loại DRM. |
| D-013 | Progress event coalesce tối thiểu 250 ms; durable checkpoint tối thiểu 5 giây và repository tiếp tục loại speed/ETA/snapshot | UI có telemetry đủ mượt mà không biến progress hook thành write amplification trong SQLite. |
| D-014 | Dependency executable do composition root cung cấp; mặc định dùng `PATH` khi development, không tự tải/cập nhật FFmpeg | Probe và processor dùng cùng executable rõ ràng; packaging sau này có thể chọn bundle đã kiểm chứng hoặc đường dẫn do user cấu hình mà không đổi application contract. |
| D-015 | Queue worker thực thi trọn download → processing; completion callback chỉ thu kết quả và release slot | Loại race khiến callback của future đã hoàn tất có thể chạy trên caller/UI thread; concurrency limit bao phủ cả network, CPU và disk I/O của một task. |
| D-016 | Final output được tạo ở temporary sibling, FFprobe trước publish, publish atomic và kiểm tra tồn tại/kích thước sau publish | `Completed` chỉ xuất hiện sau output usable; default `rename` và `skip` không overwrite, `replace` chỉ dùng khi explicit. Downloaded staging input chỉ xóa sau success, còn failure/cancel giữ lại cho processing-only retry. |

C0 chọn CPython 3.13 x64, mypy strict, Ruff và pytest. `pyproject.toml` khai báo
dependency; `uv.lock` là dữ liệu sinh tự động khóa phiên bản gián tiếp và hash.
Chiến lược phân phối FFmpeg sẽ được chốt ở C6.

## 5. Thứ tự triển khai

```text
C0 Baseline
  ↓
C1 Domain & state machine
  ↓
C2 Ports & use cases
  ├──────────────┐
  ↓              ↓
C3 Persistence   C4 Analyzer & format selection
  └──────┬───────┘
         ↓
C5 Queue & download execution
         ↓
C6 FFmpeg & output finalization
         ↓
C7 Recovery, retry & shutdown
         ↓
C8 UI-facing application facade
         ↓
C9 Core release gate
```

`C3` và `C4` có thể thực hiện song song sau khi contracts ở `C2` ổn định. Các phần còn lại nên giữ đúng thứ tự dependency.

---

## C0 — Engineering baseline `P0`

Mục tiêu: có project Python tái lập được và quality gate tối thiểu trước khi viết domain.

- [x] **C0.1** Kiểm tra compatibility của Python, PySide6 và yt-dlp; chọn một Python baseline và ghi trong `pyproject.toml`.
- [x] **C0.2** Tạo `pyproject.toml` làm nguồn cấu hình duy nhất cho package, runtime dependencies và dev dependencies.
- [x] **C0.3** Tạo package tối thiểu `src/mediaflow` và test import; chưa tạo các module roadmap rỗng.
- [x] **C0.4** Cấu hình Ruff formatter/linter, một type checker và pytest với các lệnh chuẩn.
- [x] **C0.5** Tạo CI chạy format check, lint, type check và unit/integration tests không dùng mạng.
- [x] **C0.6** Tạo logging bootstrap an toàn: UTF-8, rotation hợp lý, không log secret, chưa phụ thuộc UI.
- [x] **C0.7** Viết README development ngắn: setup, test, lint/type-check và quy tắc smoke test.

Acceptance criteria:

- Cài mới trong virtual environment sạch thành công.
- `import mediaflow` thành công.
- Tất cả quality commands và test baseline chạy xanh trên Windows.
- Không có runtime artifact hoặc agent-local file trong Git index.

Checkpoint đề xuất: `chore: bootstrap Python project and quality gates`

---

## C1 — Domain model và state machine `P0`

Mục tiêu: khóa vocabulary và invariant trước khi tích hợp engine.

- [x] **C1.1** Định nghĩa typed value objects cho task ID, attempt ID, URL nguồn, output path và timestamp UTC.
- [x] **C1.2** Định nghĩa `MediaInfo`, normalized format/stream, video/audio preset và immutable `DownloadRequest`.
- [x] **C1.3** Tách lifecycle của `AnalysisOperation` khỏi lifecycle của `DownloadTask`.
- [x] **C1.4** Định nghĩa task states tối thiểu: `QUEUED`, `DOWNLOADING`, `PROCESSING`, `PAUSED`, `INTERRUPTED`, `COMPLETED`, `FAILED`, `CANCELLED`.
- [x] **C1.5** Viết transition table và guard; terminal attempt không được tự quay lại active state.
- [x] **C1.6** Định nghĩa `ProgressSnapshot` với unit/optionality rõ ràng; unknown không được biểu diễn bằng số giả.
- [x] **C1.7** Định nghĩa error taxonomy: input, unsupported source, unavailable, auth required, access denied, network, disk, dependency, conflict, download, processing, cancelled, unexpected.
- [x] **C1.8** Viết unit tests cho mọi transition hợp lệ/không hợp lệ và invariant `Completed`.

Acceptance criteria:

- Domain chạy bằng Python thuần và không import framework/infrastructure.
- Không dùng raw dictionary làm public domain contract.
- Test chứng minh download 100% vẫn có thể ở `PROCESSING`.
- Retry semantics dựa trên attempt được thể hiện trong model hoặc contract.

Checkpoint đề xuất: `feat(core): define download domain and lifecycle`

---

## C2 — Application ports, events và use cases `P0`

Mục tiêu: định nghĩa core API ổn định để infrastructure và UI phát triển độc lập.

- [x] **C2.1** Định nghĩa các port thực sự cần dùng: analyzer, downloader, media processor, task repository, settings store, event publisher và clock.
- [x] **C2.2** Định nghĩa typed application events: analysis result/failure, task queued, state changed, progress changed, output ready và task failed.
- [x] **C2.3** Xây use case `AnalyzeUrl`; hỗ trợ cancel operation và không persist raw metadata.
- [x] **C2.4** Xây use case tạo `DownloadRequest` và enqueue task từ normalized media/preset.
- [x] **C2.5** Xây command/query contracts cho cancel, retry, resume, lấy downloads và history.
- [x] **C2.6** Định nghĩa transaction/state ownership: repository commit trước hay sau event phải có quy tắc nhất quán.
- [x] **C2.7** Viết fake adapters và contract tests cho use cases, không cần yt-dlp/FFmpeg thật.

Acceptance criteria:

- Application layer chỉ phụ thuộc domain và `Protocol`/ABC do chính core sở hữu.
- Từ fake analyzer đến queued task chạy được hoàn toàn trong test.
- Events không chứa Qt object, raw engine payload hoặc secret.

Checkpoint đề xuất: `feat(core): add application contracts and use cases`

---

## C3 — SQLite persistence và migrations `P0`

Mục tiêu: lưu task truthfully, có khả năng migrate và phục hồi.

- [x] **C3.1** Thiết kế schema tối thiểu cho task, attempt, output và schema migration.
- [x] **C3.2** Viết migration runner có thứ tự, idempotent và transaction-safe.
- [x] **C3.3** Implement SQLite task repository theo application port; không trả database row ra ngoài adapter.
- [x] **C3.4** Persist durable state, request, error category/detail đã sanitize, output identity và timestamps.
- [x] **C3.5** Không persist telemetry tần suất cao như speed/ETA; xác định policy checkpoint progress nếu cần resume UI.
- [x] **C3.6** Implement history query từ persisted terminal tasks/attempts; chưa tạo bản sao history độc lập.
- [x] **C3.7** Viết migration/repository tests bằng temporary database, gồm rollback và reopen.

Acceptance criteria:

- Database mới và database qua từng migration đều mở được.
- Round-trip giữ nguyên `DownloadRequest`, task state, attempts và outputs.
- Test không chạm dữ liệu người dùng hoặc database ngoài temporary directory.

Checkpoint đề xuất: `feat(storage): persist tasks and attempts in SQLite`

---

## C4 — URL analyzer và format selection `P0`

Mục tiêu: cô lập yt-dlp và trả metadata/preset dễ dùng cho application/UI.

- [x] **C4.1** Implement yt-dlp analyzer adapter bằng Python API với option tối thiểu và timeout/cancel boundary rõ ràng.
- [x] **C4.2** Normalize title, uploader, duration, thumbnail, source, streams, subtitles/chapters availability và playlist summary.
- [x] **C4.3** Xử lý field thiếu, duration/live/unknown size và metadata không đúng kiểu mà không làm crash.
- [x] **C4.4** Implement format selector cho `Best`, 2160p, 1440p, 1080p, 720p và Video/Audio presets.
- [x] **C4.5** Không silent fallback resolution; trả warning/choice rõ khi preset không tồn tại.
- [x] **C4.6** Map yt-dlp errors sang error taxonomy, giữ cause cho diagnostics và redact dữ liệu nhạy cảm.
- [x] **C4.7** Unit test bằng metadata fixtures; live URL smoke test để riêng và không chạy mặc định.

Acceptance criteria:

- Không có raw yt-dlp dict/exception ngoài infrastructure adapter.
- Format selection được test độc lập với network.
- Unsupported, unavailable, sign-in required và access denied được phân loại khác nhau khi có đủ bằng chứng.

Checkpoint đề xuất: `feat(analyzer): normalize media metadata and presets`

---

## C5 — Queue và download execution `P0`

Mục tiêu: tải nhiều task có giới hạn, progress thật và failure isolation.

- [x] **C5.1** Implement Queue Manager với configurable concurrency và scheduling deterministic.
- [x] **C5.2** Implement Download Manager là nơi duy nhất điều khiển task transitions.
- [x] **C5.3** Implement yt-dlp downloader adapter từ immutable request/selector.
- [x] **C5.4** Chuẩn hóa progress hook thành `ProgressSnapshot`; throttle/coalesce event và tránh database write liên tục.
- [x] **C5.5** Bảo đảm slot luôn được release khi success, failure hoặc cancel, kể cả khi callback lỗi.
- [x] **C5.6** Implement cooperative cancellation cho queued và downloading task; ghi rõ policy giữ/xóa partial file.
- [x] **C5.7** Cô lập worker failure và callback failure; một task lỗi không dừng scheduler.
- [x] **C5.8** Viết deterministic tests cho queue limit, ordering, races cơ bản, cancel và slot release.

Acceptance criteria:

- Không có network/download chạy trên Qt UI thread khi được nối vào presentation.
- Concurrency limit không bị vượt trong test stress có kiểm soát.
- Mọi execution path kết thúc bằng state hợp lệ và không làm rò worker/slot.

Checkpoint đề xuất: `feat(download): add queued execution and progress`

---

## C6 — FFmpeg, filename và output finalization `P0`

Mục tiêu: tạo file cuối đáng tin cậy và phân biệt download với processing.

- [x] **C6.1** Implement dependency probe cho yt-dlp, FFmpeg và FFprobe với version/status typed.
- [x] **C6.2** Implement process runner dùng argument array, capture stderr/exit code, timeout và cancellation; không dựng shell string.
- [x] **C6.3** Implement merge video/audio và audio conversion tối thiểu phục vụ preset V1.
- [x] **C6.4** Implement Windows filename sanitizer: reserved names, invalid chars, trailing dot/space, collision và path-length policy.
- [x] **C6.5** Implement conflict policy `rename`, `skip`, `replace`; mặc định an toàn là `rename` hoặc `skip`.
- [x] **C6.6** Kiểm tra disk space khi ước lượng khả dụng và dùng wording/data thể hiện đây là estimate.
- [x] **C6.7** Finalize output atomically khi thực tế cho phép; verify file cuối bằng tồn tại/kích thước và FFprobe khi cần.
- [x] **C6.8** Phân loại processing failure riêng; giữ temporary inputs đủ để retry processing theo policy.
- [x] **C6.9** Test command args, exit mapping, cancel, filename edge cases, conflict và cleanup bằng fake process/temp directory.

Acceptance criteria:

- `Completed` chỉ được set sau khi final output được verify.
- Không overwrite hoặc delete file ngoài policy đã chọn.
- Processing-only retry không tải lại media nếu temporary inputs còn hợp lệ.

Checkpoint đề xuất: `feat(media): process and finalize downloaded outputs`

---

## C7 — Recovery, retry/resume và shutdown `P0`

Mục tiêu: app đóng/mở lại không báo state sai và không làm mất khả năng phục hồi.

- [ ] **C7.1** Khi startup, reconcile persisted `DOWNLOADING`/`PROCESSING`/`PAUSED` thành state recoverable phù hợp, mặc định `INTERRUPTED`.
- [ ] **C7.2** Implement retry tạo attempt mới và giữ nguyên request/options cũ.
- [ ] **C7.3** Implement resume khi yt-dlp/partial file thực sự hỗ trợ; fallback phải rõ ràng và không giả là resume.
- [ ] **C7.4** Implement processing-only retry cho failure sau download.
- [ ] **C7.5** Implement shutdown coordinator: ngừng nhận task, yêu cầu cancel, bounded wait và persist state trung thực.
- [ ] **C7.6** Định nghĩa cleanup policy cho success, cancel, failure và interrupted; không xóa dữ liệu có thể phục hồi ngoài ý muốn.
- [ ] **C7.7** Viết restart/reopen tests ở từng execution stage và test idempotency của recovery.

Acceptance criteria:

- Sau simulated crash/restart không task nào còn hiển thị active giả.
- Retry/resume không yêu cầu cấu hình lại và không làm mất attempt history.
- Shutdown không để worker/process thuộc app tiếp tục ngoài policy.

Checkpoint đề xuất: `feat(core): recover interrupted tasks and retries`

---

## C8 — Application facade cho UI `P0`

Mục tiêu: cung cấp contract đủ để xây Home, Downloads, History và Settings mà không lộ infrastructure.

- [ ] **C8.1** Tạo application facade/command bus nhỏ cho analyze, enqueue, cancel, retry/resume và queries.
- [ ] **C8.2** Tạo read models cho media configuration, downloads summary/list, task details và history.
- [ ] **C8.3** Tạo event subscription contract thread-agnostic; Qt bridge sẽ marshal sang UI thread ở presentation layer.
- [ ] **C8.4** Cung cấp action capability theo state (`can_cancel`, `can_retry`, `can_resume`, `can_open_output`) thay vì để UI tự đoán.
- [ ] **C8.5** Chuẩn hóa user-safe error/message keys, technical details và suggested action.
- [ ] **C8.6** Tạo composition root nối ports với SQLite, yt-dlp, FFmpeg, settings và worker executor.
- [ ] **C8.7** Contract tests chứng minh UI-facing API không trả raw engine/database/process types.

Acceptance criteria:

- Một test client không dùng PySide6 chạy được toàn bộ happy path và error path chính.
- UI có thể render state/action đúng chỉ từ read models và events.
- Composition root là nơi duy nhất chọn concrete adapters.

Checkpoint đề xuất: `feat(core): expose application facade for desktop UI`

---

## C9 — Core release gate `P0`

Mục tiêu: xác nhận core đủ ổn định để bắt đầu triển khai UI đầy đủ.

- [ ] **C9.1** End-to-end test với fake analyzer/downloader/processor + SQLite thật trong temporary directory.
- [ ] **C9.2** Integration test subprocess giả cho success, stderr failure, timeout và cancel.
- [ ] **C9.3** Test queue nhiều task: mixed success/failure/cancel, restart giữa chừng và processing failure.
- [ ] **C9.4** Audit log/error/diagnostics để bảo đảm redaction cookie/token/path nhạy cảm theo policy.
- [ ] **C9.5** Chạy format, lint, type check, full offline tests và kiểm tra clean shutdown.
- [ ] **C9.6** Chạy manual smoke test có kiểm soát với một URL được phép tải; ghi version yt-dlp/FFmpeg và không biến URL đó thành dependency của test suite.
- [ ] **C9.7** Cập nhật architecture notes và `task.md` theo implementation thực tế; không để quyết định quan trọng chỉ nằm trong code.

Acceptance criteria:

- Analyze → queue → download → process → persist → reopen chạy thành công.
- Error taxonomy và retry action đúng cho các failure lane chính.
- Không có thread/process/resource leak đã biết; không có secret/runtime artifact trong Git.
- Core API đủ cho UI V1 mà không cần UI gọi trực tiếp infrastructure.

Checkpoint đề xuất: `test(core): pass V1 core release gate`

---

## 6. Backlog sau Core V1

### P1 — Sau khi C9 ổn định

- [ ] Playlist group và item selection; mỗi item vẫn là task độc lập.
- [ ] Subtitle uploaded/auto-generated, thumbnail, chapter và metadata options.
- [ ] Settings adapter hoàn chỉnh: defaults, concurrency, filename template và dependency paths.
- [ ] Browser session hợp lệ do người dùng chủ động chọn; không lưu/export cookie plaintext.
- [ ] Pause/resume đầy đủ nếu backend semantics đã được integration-test.
- [ ] Dependency update check/status; chưa auto-update nếu chưa có rollback/integrity policy.

### P2 — Chưa đưa vào kế hoạch triển khai

- [ ] Custom yt-dlp arguments/format expression cho power user.
- [ ] Proxy profiles, scheduler, batch rules/import.
- [ ] Chapter cutting, segment download, comments.
- [ ] Plugin architecture, remote control, Android hoặc Web.

## 7. Risk register

| Risk | Mức độ | Mitigation bắt buộc |
|---|---|---|
| Website/extractor thay đổi | Cao | Cô lập yt-dlp adapter, version rõ, fixture tests và smoke test riêng. |
| Race condition giữa progress/cancel/complete | Cao | Một state owner, transition guards, immutable events và deterministic race tests. |
| FFmpeg tải xong nhưng merge lỗi | Cao | State `PROCESSING`, processing error riêng và retry từ temporary inputs. |
| SQLite bị ghi quá dày bởi progress | Trung bình | Không persist speed/ETA liên tục; checkpoint có throttle nếu cần. |
| Filename/path Windows không hợp lệ | Cao | Sanitizer tập trung, conflict policy và boundary tests. |
| Pause không đúng kỳ vọng | Trung bình | Không expose trước khi resume semantics được chứng minh. |
| Secret lọt vào log/repo | Cao | Redaction, safe diagnostics, `.gitignore` và staged-file audit. |
| Live-site tests flaky | Trung bình | Offline suite là release gate; smoke test tách riêng. |
| Scope V1 phình to | Cao | C9 chỉ gồm P0; P1/P2 không kéo vào trừ khi có quyết định mới. |

## 8. Definition of Done cho mỗi task

Một task chỉ được đánh dấu `[x]` khi:

- Behavior và acceptance criteria tương ứng đã đạt.
- Boundary/lifecycle/error semantics không bị phá.
- Có unit hoặc integration test có ý nghĩa; bug fix có regression test.
- Formatter/linter/type check và test liên quan chạy thành công.
- Không có placeholder, swallowed exception, fake progress hoặc unsupported action.
- Không thêm secret, local path, runtime database/log/download hoặc agent-local file vào Git.
- Tài liệu/task tracker được cập nhật nếu quyết định hoặc phạm vi thay đổi.

## 9. Blockers

Chưa có blocker tại thời điểm lập kế hoạch.

## 10. Nhật ký tiến độ

- **2026-09-07 — C6 hoàn thành:** Thêm dependency report typed cho yt-dlp/FFmpeg/FFprobe và probe version/status; process runner dùng argument tuple với `shell=False`, capture stdout/stderr, timeout, cooperative cancel và reap process. FFmpeg adapter hỗ trợ merge video/audio, remux combined video, M4A/MP3 conversion và copy audio gốc; mọi output được tạo ở temporary sibling, kiểm tra non-empty + FFprobe, publish atomic rồi kiểm tra final file trước khi application commit `COMPLETED`. Filename Windows xử lý invalid/control chars, reserved names, trailing dot/space, collision và path budget; conflict mặc định `rename`, `skip` không ghi file và `replace` chỉ overwrite khi explicit. Disk-space contract luôn đánh dấu estimate. Failure/cancel chỉ dọn unpublished generated output và giữ downloaded inputs; success mới dọn input staging. Queue chạy trọn download→processing trên worker, không xử lý trong future callback; processing-only retry tạo attempt `PROCESSING` mới và không gọi downloader. Toàn bộ 274 offline tests chạy xanh, 1 live smoke test deselect; probe thật trên máy phát hiện yt-dlp `2026.08.19` ready, FFmpeg/FFprobe chưa có trên `PATH`, nên FFmpeg behavior được xác nhận bằng fake runner/temp filesystem chứ chưa có live media smoke.
- **2026-09-07 — C5 hoàn thành:** Thêm Queue Manager FIFO dùng bounded `ThreadPoolExecutor`, configurable concurrency và lifecycle sở hữu tài nguyên rõ ràng; mọi download chạy trên worker thread, slot được release bằng completion callback cho success/failure/cancel. `DownloadManager` là state owner duy nhất, commit repository trước event, settle cancel/failure/success atomically và chỉ chuyển download thành công sang `PROCESSING`. yt-dlp downloader nhận immutable job/selector, dùng staging riêng theo task/attempt, không overwrite, giữ `.part` khi cancel/failure, không dùng browser cookie, loại DRM và tắt implicit merge để dành processing/final verification cho C6. Raw progress được normalize trung thực, event coalesce 250 ms, durable checkpoint 5 giây và callback/worker failure được cô lập. Stress/FIFO/race/cancel/adapter tests hoàn toàn offline; toàn bộ 236 tests chạy xanh, 1 live smoke test được deselect mặc định.
- **2026-09-07 — C3 và C4 hoàn thành song song:** SQLite có schema normalized cho task/attempt/output, migration history liên tục có checksum và rollback từng version, repository optimistic theo durable projection, history là projection của terminal task, đồng thời mọi connection được đóng tường minh để không giữ file handle trên Windows. Analyzer yt-dlp dùng option tối thiểu, logger im lặng, cooperative cancellation và per-I/O socket timeout; metadata thiếu/sai kiểu/non-finite, playlist/subtitle/chapter/live được normalize sang model typed. Source URL giữ nguyên ý định người dùng, canonical URL tách riêng, credential-bearing URL bị chặn trước event/persistence. Format availability thuộc application, validate trước enqueue; selector hạ tầng không dùng raw format ID, không fallback resolution/video-only ngầm. Error taxonomy phân biệt unsupported, unavailable, auth, access và network; raw cause chỉ nằm trong diagnostic boundary. Toàn bộ Ruff, mypy strict, dependency checks và 206 offline tests chạy xanh; 1 live smoke test được deselect mặc định.
- **2026-09-06 — C2 hoàn thành:** Tạo application API thuần Python gồm analyzer/downloader/media processor/task repository/settings/event/clock ports; typed analysis/task/progress/output/failure events; và các use case analyze, enqueue, cancel, retry, resume, downloads/history query. Analysis hỗ trợ cancellation token và chỉ trao đổi normalized outcome; task mutation dùng optimistic aggregate replacement, commit repository trước khi publish event. Fake adapters xác nhận luồng analyzer → queued task hoàn toàn offline, event không chứa raw dict/`Any` và application import không kéo framework/infrastructure. Toàn bộ Ruff, mypy strict, 128 offline tests và dependency checks chạy xanh trên Windows.
- **2026-09-06 — C1 hoàn thành:** Tạo domain thuần Python với typed identifiers/boundary values, normalized media và preset models, immutable `DownloadRequest`, lifecycle riêng cho analysis, cùng state machine cho download task/attempt. Retry tạo attempt mới và chỉ cho phép failure retryable; progress dùng unit rõ ràng và giữ `None` cho giá trị chưa biết; failure dùng taxonomy/code an toàn thay vì raw exception. Ma trận 64 cặp transition và các invariant lifecycle được kiểm thử; toàn bộ 112 offline tests, Ruff, mypy strict, lock/dependency check đều chạy xanh trên Windows.
- **2026-09-06 — C0 hoàn thành:** Chọn Python 3.13 x64; PySide6 6.11.2 và yt-dlp 2026.8.19 import thành công trên Python 3.13.2. Tạo package, pyproject, uv.lock, Windows CI và README. Logging UTF-8 JSON có rotation, allowlist event/context và fallback an toàn khi ghi thất bại. Hai môi trường sạch (editable và wheel không editable) đều đạt Ruff format/lint, mypy strict, 9 offline tests và dependency check. GitHub CI được cấu hình; kết quả chạy remote được theo dõi riêng, không suy ra từ local tests.
- **2026-09-06:** Phân tích `docs/overview.md` và `docs/ui-ux.md`; lập roadmap Core V1 theo dependency, acceptance criteria, risk và checkpoint commit.
