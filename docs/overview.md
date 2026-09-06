# Project Overview

## 1. Dự án này là gì?

Đây là một ứng dụng desktop dành cho Windows, được xây dựng như một công cụ cá nhân để phân tích và tải nội dung media từ các URL mà người dùng cung cấp. Phần xử lý tải xuống sẽ sử dụng `yt-dlp` làm engine chính, còn `FFmpeg` đảm nhiệm những công việc liên quan đến ghép video và audio, chuyển container, xử lý audio hoặc các bước hậu kỳ media khi cần.

Mục tiêu của dự án không phải là viết lại toàn bộ cơ chế download của `yt-dlp`, vì bản thân công cụ này đã xử lý rất tốt phần extractor, format, metadata và các thay đổi thường xuyên từ phía nền tảng. Thay vào đó, dự án tập trung xây một lớp ứng dụng desktop hoàn chỉnh bên trên `yt-dlp`, giúp việc sử dụng trở nên trực quan, có quản lý tiến trình, lịch sử, hàng đợi và cấu hình rõ ràng hơn so với thao tác trực tiếp bằng terminal.

Ở giai đoạn đầu, ứng dụng được định hướng dành riêng cho Windows. Việc giới hạn phạm vi như vậy giúp phần tích hợp với filesystem, process, FFmpeg, notification và packaging đơn giản hơn, đồng thời giảm đáng kể độ phức tạp so với việc cố hỗ trợ desktop và mobile cùng lúc ngay từ phiên bản đầu tiên.

---

## 2. Mục đích của dự án

Mục đích chính là tạo một công cụ desktop cá nhân có thể sử dụng hằng ngày, ổn định và dễ kiểm soát hơn việc chạy các lệnh `yt-dlp` thủ công.

Người dùng chỉ cần cung cấp URL, ứng dụng sẽ phân tích nội dung, lấy các thông tin cần thiết, cho phép chọn chất lượng hoặc kiểu tải phù hợp rồi xử lý phần còn lại. Những trạng thái như đang phân tích, đang tải, đang ghép media, hoàn tất hoặc lỗi đều được ứng dụng quản lý rõ ràng.

Một mục tiêu quan trọng khác là tách phần giao diện khỏi phần xử lý download. `yt-dlp` sẽ được coi như một engine phía dưới, còn ứng dụng chịu trách nhiệm quản lý workflow, trạng thái, cấu hình, lịch sử, hàng đợi và lỗi. Nhờ vậy, nếu sau này `yt-dlp` thay đổi hoặc cần thay thế một phần backend, phần còn lại của ứng dụng vẫn có thể duy trì tương đối độc lập.

Dự án này được thiết kế trước hết cho mục đích sử dụng cá nhân. Nếu sau này chuyển thành sản phẩm phân phối công khai, cần xem xét thêm license của các thành phần được đóng gói, chính sách của từng nền tảng và cách xử lý nội dung có bản quyền hoặc nội dung cần xác thực.

---

## 3. Phạm vi phiên bản đầu tiên

Phiên bản đầu tiên chỉ tập trung vào Windows Desktop và những chức năng thực sự cần thiết để hình thành một downloader hoàn chỉnh.

Luồng sử dụng chính sẽ là: người dùng nhập URL, ứng dụng phân tích URL, hiển thị metadata và các định dạng khả dụng, người dùng chọn phương án tải, tác vụ được đưa vào hàng đợi, sau đó ứng dụng theo dõi quá trình tải và lưu lại lịch sử khi hoàn tất.

Ứng dụng không cần server riêng ở giai đoạn này. Toàn bộ dữ liệu cấu hình, lịch sử và trạng thái cần lưu lâu dài có thể được giữ ngay trên máy người dùng.

---

## 4. Tech Stack

### Python

Python được sử dụng làm ngôn ngữ chính của ứng dụng. Lý do lớn nhất là `yt-dlp` cũng được viết bằng Python, nên việc tích hợp trực tiếp qua Python API sẽ tự nhiên hơn và giảm số lớp trung gian không cần thiết.

Python cũng phù hợp với một công cụ desktop cá nhân vì tốc độ phát triển nhanh, hệ sinh thái tốt và có đủ thư viện để xử lý GUI, filesystem, database, process, logging và packaging.

### PySide6

`PySide6` được dùng để xây ứng dụng desktop trên Windows. Đây là binding chính thức của Qt dành cho Python và phù hợp với một ứng dụng cần nhiều thành phần desktop như cửa sổ chính, danh sách tác vụ, progress, dialog cấu hình, system tray, file picker và notification.

Phần UI sẽ được tách khỏi logic download để tránh việc giao diện phụ thuộc trực tiếp vào `yt-dlp`.

### yt-dlp

`yt-dlp` là engine chính cho việc phân tích URL và tải media. Ứng dụng sẽ không tự viết extractor cho từng nền tảng nếu không thật sự cần thiết.

Các khả năng dự kiến dùng từ `yt-dlp` gồm đọc metadata, lấy danh sách format, chọn video/audio stream, tải playlist, tải subtitle, thumbnail, chapter và xử lý những nội dung cần session hợp lệ khi người dùng có quyền truy cập.

Ứng dụng không được thiết kế để vượt qua cơ chế phân quyền của nền tảng. Nếu một nội dung yêu cầu tài khoản hoặc quyền truy cập cụ thể, engine chỉ nên sử dụng session hợp lệ của chính người dùng khi họ thực sự có quyền xem nội dung đó.

### FFmpeg / FFprobe

`FFmpeg` được dùng cho các công việc hậu xử lý media. Một số video có video stream và audio stream tách riêng, vì vậy sau khi tải xong cần ghép chúng lại thành file cuối cùng.

Ngoài việc merge, FFmpeg có thể được sử dụng cho chuyển container, trích xuất audio, xử lý chapter hoặc cắt một đoạn video nếu các chức năng này được bật trong những phiên bản sau.

`FFprobe` có thể hỗ trợ việc đọc thông tin media sau khi download hoặc kiểm tra file output khi cần.

### SQLite

`SQLite` được dùng để lưu dữ liệu local. Vì ứng dụng không cần server nên đây là lựa chọn phù hợp, nhẹ và dễ backup.

Database có thể lưu lịch sử download, trạng thái task, đường dẫn file, URL gốc, metadata cơ bản và một số cấu hình cần truy vấn thường xuyên.

Những cấu hình đơn giản hơn vẫn có thể được lưu bằng file JSON hoặc Qt Settings. Không nhất thiết đưa mọi thứ vào database.

### Packaging

Ở giai đoạn phát triển có thể chạy trực tiếp từ Python environment. Khi ứng dụng ổn định, có thể đóng gói thành file thực thi cho Windows bằng `PyInstaller` hoặc `Nuitka`.

Cần đặc biệt chú ý cách phân phối `yt-dlp`, `FFmpeg` và các dependency đi kèm nếu sau này phát hành ứng dụng cho người khác.

---

## 5. Kiến trúc tổng thể

Ứng dụng nên được chia thành các lớp tương đối rõ ràng thay vì để giao diện gọi trực tiếp mọi thứ.

Một cấu trúc hợp lý có thể gồm phần presentation chịu trách nhiệm hiển thị dữ liệu, application layer quản lý workflow, download layer giao tiếp với `yt-dlp`, media layer giao tiếp với FFmpeg và persistence layer lưu dữ liệu local.

Luồng cơ bản có thể hiểu như sau:

```text
User
  ↓
Desktop Application
  ↓
Application / Task Manager
  ↓
Download Service
  ↓
yt-dlp
  ↓
FFmpeg khi cần
  ↓
Local File
```

Song song với luồng này, ứng dụng cập nhật trạng thái vào database và gửi event về giao diện để người dùng biết tiến trình hiện tại.

Một nguyên tắc quan trọng là không để tác vụ tải hoặc xử lý FFmpeg chạy trực tiếp trên UI thread. Download cần chạy trong worker thread hoặc process riêng. Nếu không, giao diện có thể bị treo trong lúc tải, phân tích playlist lớn hoặc merge file dung lượng cao.

---

## 6. Các module chính

### URL Analyzer

Module này nhận URL từ người dùng và dùng `yt-dlp` để phân tích nội dung trước khi tải.

Kết quả phân tích có thể bao gồm title, channel hoặc uploader, thumbnail, duration, loại nội dung, danh sách resolution, format, codec, FPS, audio format, subtitle và chapter nếu có.

Module cũng cần xử lý trường hợp URL không hợp lệ, URL không được hỗ trợ, nội dung đã bị xóa hoặc nền tảng yêu cầu xác thực.

### Download Manager

Đây là phần trung tâm của ứng dụng. Download Manager chịu trách nhiệm tạo task, bắt đầu download, pause hoặc cancel khi có thể, theo dõi trạng thái và cập nhật progress.

Nó không nên phụ thuộc vào giao diện. Thay vào đó, nó phát ra các event như progress changed, status changed, completed hoặc failed để UI phản ứng tương ứng.

### Queue Manager

Queue Manager quản lý nhiều tác vụ download cùng lúc.

Người dùng có thể thêm nhiều video hoặc một playlist vào hàng đợi. Ứng dụng cần giới hạn số tác vụ chạy đồng thời để tránh chiếm toàn bộ bandwidth, CPU hoặc disk I/O.

Số lượng download song song nên là một cấu hình thay đổi được.

### Media Processor

Module này bọc các thao tác FFmpeg. Nó xử lý merge video/audio, convert container, extract audio và các bước hậu xử lý khác.

Việc bọc FFmpeg thành một module riêng giúp phần download không phải biết chi tiết command của FFmpeg.

### History Manager

Sau khi task hoàn tất hoặc thất bại, thông tin được lưu lại để người dùng có thể xem lịch sử.

Lịch sử nên giữ URL gốc, title, thời gian download, format, quality, output path và trạng thái cuối cùng.

Xóa lịch sử và xóa file vật lý phải là hai hành động khác nhau. Không nên tự động xóa file chỉ vì người dùng xóa một record lịch sử.

### Settings Manager

Settings Manager chịu trách nhiệm những cấu hình như thư mục mặc định, chất lượng mặc định, định dạng mặc định, số download song song, template tên file, theme, đường dẫn FFmpeg và các tùy chọn nâng cao.

Nếu sau này hỗ trợ authenticated content, cấu hình liên quan browser cookies hoặc session cũng nên nằm trong module này nhưng không lưu thông tin nhạy cảm dưới dạng plaintext nếu có lựa chọn an toàn hơn.

### Logging và Error Handling

Ứng dụng cần có log riêng thay vì chỉ hiển thị raw output từ `yt-dlp`.

Ở mức người dùng, lỗi nên được chuyển thành thông báo dễ hiểu như "không tìm thấy video", "nội dung yêu cầu đăng nhập", "không tìm thấy FFmpeg", "không còn đủ dung lượng" hoặc "mạng bị gián đoạn".

Ở mức developer, log chi tiết vẫn cần giữ traceback, command, extractor error và trạng thái của task để debug khi cần.

---

## 7. Chức năng dự kiến triển khai

### Phân tích video

Người dùng nhập hoặc paste URL. Ứng dụng tự phân tích và lấy thông tin video trước khi download.

Nếu URL là playlist, ứng dụng nhận biết đây là playlist và tải danh sách item thay vì xử lý như một video đơn.

### Tải video

Người dùng có thể chọn resolution và container phù hợp. Ở mức đơn giản, ứng dụng chỉ cần cung cấp những lựa chọn dễ hiểu như Best, 4K, 1440p, 1080p, 720p và MP4 hoặc MKV.

Phần mapping từ lựa chọn của người dùng sang `yt-dlp format selector` sẽ được xử lý nội bộ.

### Tải audio

Ứng dụng hỗ trợ chế độ chỉ tải audio. Có thể hỗ trợ các output như M4A, MP3 hoặc audio stream gốc tùy trường hợp.

Nếu cần convert audio, phần này sẽ dùng FFmpeg.

### Download Queue

Người dùng có thể thêm nhiều tác vụ và để ứng dụng xử lý lần lượt hoặc chạy song song theo giới hạn cấu hình.

Mỗi task cần có trạng thái riêng và không được làm ảnh hưởng đến các task khác nếu một download bị lỗi.

### Progress Tracking

Ứng dụng theo dõi phần trăm download, tốc độ tải, dung lượng đã tải, ETA và trạng thái hậu xử lý.

Cần phân biệt rõ download đã đạt 100% với task đã hoàn tất hoàn toàn, vì sau bước tải có thể vẫn còn quá trình merge hoặc convert.

### Pause, Resume và Retry

Ứng dụng nên hỗ trợ resume những download mà `yt-dlp` có thể tiếp tục từ file tạm.

Retry cần giữ lại cấu hình của task cũ để người dùng không phải thiết lập lại.

Pause có thể phụ thuộc vào cách triển khai worker/process và khả năng của backend tại thời điểm đó, nên cần thiết kế task state từ đầu để không khóa kiến trúc vào một cách duy nhất.

### Playlist

Ứng dụng có thể phân tích playlist, hiển thị danh sách item và cho phép chọn video cần tải.

Các tùy chọn như tải toàn bộ playlist, chọn một khoảng index hoặc bỏ qua file đã tồn tại có thể được hỗ trợ.

### Subtitle

Nếu nội dung có subtitle, ứng dụng cho phép tải subtitle riêng hoặc nhúng vào file khi phù hợp.

Nên phân biệt subtitle do uploader cung cấp với auto-generated subtitle.

### Thumbnail và Metadata

Người dùng có thể tùy chọn tải thumbnail, lưu description, metadata hoặc embed một số metadata vào file media.

### History

Ứng dụng lưu lại lịch sử task để người dùng có thể mở file, mở thư mục chứa file, tải lại hoặc truy cập URL gốc.

### Local Settings

Ứng dụng lưu các thiết lập mặc định để không phải cấu hình lại mỗi lần mở app.

### Authenticated Content

Ứng dụng có thể hỗ trợ sử dụng browser cookies hoặc session hợp lệ của người dùng cho những nội dung mà tài khoản đó vốn có quyền truy cập.

Chức năng này chỉ nhằm tái sử dụng trạng thái đăng nhập hợp lệ. Nó không phải chức năng bypass paywall, bypass membership hoặc vượt authorization của nền tảng.

---

## 8. Những chức năng chưa cần làm ngay

Một số tính năng có giá trị nhưng không nên đưa hết vào phiên bản đầu tiên vì sẽ làm tăng đáng kể độ phức tạp.

Ví dụ như cắt video theo timeline, split theo chapter, tải comment, proxy profiles, rate limiting nâng cao, custom format expression, custom yt-dlp arguments, scheduler, batch import từ file, plugin system hoặc remote control có thể để cho các phiên bản sau.

Điểm quan trọng ở V1 là download ổn định, queue hoạt động đúng, xử lý lỗi rõ ràng và file output đáng tin cậy.

---

## 9. Quản lý dữ liệu local

Ứng dụng nên giữ database đơn giản và có khả năng migrate khi schema thay đổi.

Một `download_task` có thể chứa các trường như ID, URL, title, content type, selected format, output path, status, progress, created time, completed time và error message.

Thông tin transient như tốc độ hiện tại hoặc ETA không nhất thiết phải ghi database liên tục vì việc write quá thường xuyên là không cần thiết.

Settings có thể được chia thành hai loại: cấu hình nhỏ lưu qua QSettings hoặc JSON, còn dữ liệu dạng lịch sử và task lưu trong SQLite.

---

## 10. Cấu trúc thư mục gợi ý

```text
project/
│
├── app/
│   ├── main.py
│   │
│   ├── ui/
│   │   ├── windows/
│   │   ├── dialogs/
│   │   └── components/
│   │
│   ├── core/
│   │   ├── models/
│   │   ├── events/
│   │   └── enums/
│   │
│   ├── services/
│   │   ├── analyzer_service.py
│   │   ├── download_service.py
│   │   ├── ffmpeg_service.py
│   │   ├── queue_service.py
│   │   └── settings_service.py
│   │
│   ├── workers/
│   │   ├── download_worker.py
│   │   └── analyze_worker.py
│   │
│   ├── repositories/
│   │   ├── download_repository.py
│   │   └── settings_repository.py
│   │
│   └── database/
│       ├── connection.py
│       └── migrations/
│
├── resources/
├── tests/
├── scripts/
├── requirements.txt
├── README.md
└── overview.md
```

Cấu trúc này chỉ là điểm bắt đầu. Không nên tạo quá nhiều abstraction nếu project còn nhỏ. Khi codebase lớn dần mới cần tách sâu hơn.

---

## 11. Xử lý task và concurrency

Đây là một phần cần thiết kế kỹ ngay từ đầu.

Mỗi download nên được coi là một task có lifecycle riêng. Task có thể đi qua các trạng thái như Pending, Analyzing, Queued, Downloading, Processing, Completed, Failed hoặc Cancelled.

Không nên để UI giữ state chính của task. State thật nên nằm trong application layer hoặc task manager, sau đó UI chỉ render theo state đó.

Đối với PySide6, có thể dùng `QThread`, `QThreadPool` hoặc worker process tùy mức độ phức tạp. Với các lệnh external như FFmpeg, `QProcess` cũng là một lựa chọn phù hợp vì dễ theo dõi stdout, stderr và exit code.

Nếu dùng `yt-dlp` Python API trực tiếp, progress hook có thể được chuyển thành signal để cập nhật task.

---

## 12. Error handling

Không nên coi mọi lỗi đều giống nhau.

Một số lỗi thuộc nhóm input, ví dụ URL sai hoặc nội dung không tồn tại. Một số lỗi thuộc authentication, một số thuộc network, một số thuộc disk hoặc FFmpeg. Việc phân loại lỗi sẽ giúp ứng dụng phản hồi đúng hơn và dễ debug hơn.

Ví dụ, nếu một download thất bại do mạng, ứng dụng có thể cho phép retry. Nhưng nếu nội dung đã bị xóa, retry liên tục không có ý nghĩa.

Raw error từ yt-dlp vẫn nên được lưu trong log nhưng không nhất thiết hiển thị toàn bộ cho người dùng.

---

## 13. Cập nhật yt-dlp và FFmpeg

Đây là vấn đề rất quan trọng đối với loại ứng dụng này.

Các nền tảng video thường xuyên thay đổi API hoặc player behavior, vì vậy `yt-dlp` cũng phải cập nhật liên tục. Nếu đóng gói một phiên bản cố định vào app mà không có chiến lược update, downloader có thể ngừng hoạt động sau một thời gian.

Do đó ứng dụng nên coi `yt-dlp` là một dependency có version rõ ràng. Có thể hiển thị version hiện tại và sau này bổ sung cơ chế kiểm tra hoặc cập nhật engine.

FFmpeg ít thay đổi theo kiểu phá compatibility hơn nhưng vẫn cần quản lý version và đường dẫn rõ ràng.

---

## 14. Bảo mật và quyền riêng tư

Vì đây là ứng dụng local, phần lớn dữ liệu không cần rời khỏi máy người dùng ngoài các request vốn cần thiết để truy cập nội dung từ nền tảng.

Không nên ghi cookies, session token hoặc credential vào log.

Nếu hỗ trợ đọc cookies từ browser, cần giới hạn việc sử dụng đúng cho task cần xác thực và không export cookie ra file plaintext nếu không cần thiết.

Database và log cũng không nên lưu những header hoặc token không cần thiết.

---

## 15. Giới hạn và trách nhiệm sử dụng

`yt-dlp` có thể hỗ trợ rất nhiều website, nhưng không có nghĩa mọi nội dung đều có thể hoặc nên được tải xuống.

Ứng dụng cần tôn trọng authorization của dịch vụ. Một tài khoản không có quyền truy cập nội dung thì app không nên cố tạo cơ chế bypass quyền đó.

Ngoài vấn đề kỹ thuật, người dùng vẫn cần tuân thủ điều khoản của nền tảng và quyền của chủ sở hữu nội dung. Việc sử dụng `yt-dlp` làm engine không tự động làm cho mọi hình thức download trở thành được phép.

---

## 16. Testing

Dự án nên có test cho những phần không phụ thuộc trực tiếp vào UI, đặc biệt là format selection, task state transition, filename handling, settings, database và error mapping.

Các integration test với yt-dlp cần thận trọng vì website bên ngoài thay đổi liên tục. Không nên để toàn bộ test suite phụ thuộc vào một video công khai cụ thể mà không có fallback.

Có thể mock metadata và progress event để test Download Manager mà không cần thực sự tải file trong mọi test.

---

## 17. Roadmap đề xuất

V1 nên tập trung vào URL analyzer, tải video/audio, format selection, queue, progress, FFmpeg merge, history, settings và error handling.

Sau khi những phần này ổn định, V1.1 có thể thêm playlist đầy đủ hơn, subtitle, thumbnail, metadata, retry/resume tốt hơn và authenticated session.

V2 mới nên xem xét advanced format controls, chapter handling, segment download, scheduler hoặc plugin architecture.

Android có thể được nghiên cứu sau khi engine và task architecture trên Windows đã ổn định. Không nên coi mobile chỉ là việc thu nhỏ lại phiên bản desktop vì background execution, storage và packaging trên mobile có nhiều ràng buộc khác.

---

## 18. Tiêu chí để xem V1 là hoàn thành

V1 có thể được coi là sử dụng được khi người dùng có thể đưa vào một URL hợp lệ, xem được thông tin nội dung, chọn một format phổ biến, tải file thành công, theo dõi được tiến trình, không làm treo ứng dụng, nhận được thông báo lỗi dễ hiểu và tìm lại được file đã tải trong lịch sử.

Ứng dụng cũng cần xử lý tốt việc đóng/mở lại, lưu settings ổn định và không để task lỗi làm crash toàn bộ chương trình.

Nếu đạt được những điểm này thì project đã có nền móng tốt để mở rộng, thay vì chỉ là một wrapper đơn giản quanh command line của `yt-dlp`.
