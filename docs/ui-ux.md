# UI/UX Design

## 1. Tài liệu này dùng để làm gì?

Tài liệu này mô tả cách ứng dụng desktop downloader nên được tổ chức và vận hành về mặt UI/UX. Phạm vi hiện tại là **Windows Desktop**, đúng với định hướng trong `overview.md`. Những ghi chú về mobile hoặc web chỉ được xem là nền tảng để mở rộng sau này, không phải phạm vi cần triển khai ở V1.

Mục tiêu của thiết kế không phải là đưa toàn bộ option của `yt-dlp` lên màn hình. Người dùng cần cảm giác mình đang sử dụng một ứng dụng hoàn chỉnh, không phải một giao diện bọc quanh command line.

Ứng dụng nên cho phép một người không biết `yt-dlp`, format ID hay FFmpeg vẫn tải được nội dung theo luồng rất tự nhiên: dán link, xem thông tin, chọn chất lượng, tải xuống và theo dõi tiến trình.

Power user vẫn cần quyền kiểm soát sâu hơn. Vì vậy thiết kế sẽ dùng nguyên tắc **Simple first, Advanced when needed**.

---

## 2. Tư duy thiết kế chính

Ứng dụng nên tạo cảm giác nhanh, rõ và có thể đoán được bước tiếp theo.

Người dùng không nên phải tự hỏi:

- Link đã được nhận chưa?
- App đang phân tích hay bị treo?
- 1080p này có audio không?
- Download 100% rồi tại sao chưa xong?
- File được lưu ở đâu?
- Lỗi này do mạng, FFmpeg hay quyền truy cập?

Mỗi trạng thái quan trọng phải được thể hiện trực tiếp bằng giao diện và ngôn ngữ dễ hiểu.

Ba nguyên tắc xuyên suốt là:

**Một tác vụ chính trên mỗi màn hình.** Home tập trung thêm download. Downloads tập trung theo dõi task. History tập trung nội dung đã xử lý. Settings chỉ dành cho cấu hình.

**Progressive disclosure.** Những thứ phổ biến được đặt trước. Những thiết lập kỹ thuật nằm trong phần Advanced.

**UI phản ánh state thật.** Không giả vờ task đã hoàn thành chỉ vì download đạt 100%. Nếu app đang merge video và audio, phải hiển thị `Processing` hoặc `Merging`.

---

# PHẦN I — CẤU TRÚC ỨNG DỤNG

## 3. Information Architecture

V1 không cần quá nhiều mục điều hướng. Sidebar chính chỉ nên có:

```text
Home
Downloads
History

Settings
```

Playlist không cần trở thành một tab cố định. Khi URL được phân tích là playlist, Home chuyển sang trạng thái playlist hoặc mở một trang chi tiết playlist trong cùng navigation stack.

Tương tự, Video Details không phải menu riêng. Nó là trạng thái sau khi một URL được phân tích.

Cấu trúc này giúp sidebar giữ ổn định ngay cả khi ứng dụng có thêm nhiều capability.

```text
Application
│
├── Home
│   ├── URL Input
│   ├── Media Preview
│   ├── Download Options
│   └── Playlist Selection
│
├── Downloads
│   ├── Active
│   ├── Queue
│   └── Recently Completed
│
├── History
│
└── Settings
    ├── General
    ├── Downloads
    ├── Media
    └── Advanced
```

---

## 4. Cấu trúc cửa sổ desktop

Desktop dùng sidebar bên trái và content area bên phải.

```text
┌──────────────────────────────────────────────────────────────┐
│ App title                                              — □ × │
├──────────────┬───────────────────────────────────────────────┤
│              │                                               │
│  Home        │                                               │
│  Downloads   │                Main Content                   │
│  History     │                                               │
│              │                                               │
│              │                                               │
│  Settings    │                                               │
│              │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

Sidebar nên đủ hẹp để không lấy mất không gian, nhưng đủ rộng để icon và label đọc thoải mái.

Khi cửa sổ bị thu nhỏ, sidebar chuyển về icon-only thay vì ép content area trở nên quá chật.

Không nên dùng nhiều cấp sidebar lồng nhau. Những lựa chọn phụ nên nằm trong nội dung của màn hình hiện tại.

---

# PHẦN II — LUỒNG NGƯỜI DÙNG CHÍNH

## 5. Primary Flow

Luồng quan trọng nhất của sản phẩm là:

```text
Paste URL
    ↓
Analyze
    ↓
Review media
    ↓
Choose preset
    ↓
Add to Downloads
    ↓
Download / Process
    ↓
Completed
    ↓
Open file / Open folder
```

Từ góc nhìn người dùng, đây phải là một luồng liên tục. Không nên mở nhiều dialog liên tiếp chỉ để hoàn thành một download.

Nếu URL đã được nhận diện, app nên tự bắt đầu phân tích sau một khoảng debounce ngắn. Nút `Analyze` vẫn có thể tồn tại như fallback, nhưng không nên bắt người dùng bấm nếu link đã hợp lệ.

---

## 6. Simple Mode và Advanced Mode

Simple Mode là mặc định.

Người dùng chỉ cần thấy những thông tin như:

```text
Quality     1080p
Format      MP4
Audio       Best
Save to     Downloads
```

Advanced Mode mở thêm các lựa chọn như codec, FPS, subtitle, chapter, metadata, browser session hoặc format chi tiết.

Advanced không nên là một màn hình hoàn toàn khác. Nó nên mở rộng phần option hiện tại để người dùng vẫn giữ được context.

Ví dụ:

```text
Download Options

Quality      [1080p          ▾]
Format       [MP4            ▾]

▸ Advanced options

                         [Download]
```

Sau khi mở:

```text
▾ Advanced options

Video codec  [Auto            ▾]
Audio codec  [Auto            ▾]
FPS          [Auto            ▾]
Subtitles    [None            ▾]
Chapters     [Keep            ▾]
Metadata     [Embed             ]
```

Không hiển thị format ID trừ khi user bật một chế độ kỹ thuật rõ ràng hơn.

---

# PHẦN III — HOME

## 7. Home khi chưa có URL

Home ban đầu cần cực kỳ rõ ràng. Không nên lấp đầy bằng lịch sử, banner hoặc quá nhiều card.

```text
Download media

Paste a video or playlist URL

┌──────────────────────────────────────────────────────┐
│ https://...                                      Paste │
└──────────────────────────────────────────────────────┘

You can also paste with Ctrl + V
```

Nếu clipboard đang chứa một URL hợp lệ, app có thể hiển thị action nhẹ:

```text
URL found in clipboard
[Use clipboard link]
```

Không nên tự động đọc và analyze clipboard mọi lúc nếu chưa có thiết lập rõ ràng. Điều này có thể gây cảm giác xâm phạm hoặc tạo request ngoài ý muốn.

---

## 8. Trạng thái đang phân tích

Ngay sau khi nhận URL, input không biến mất. User vẫn cần biết app đang xử lý link nào.

```text
Analyzing media...

[loading indicator]
Getting title, formats and available media information
```

Nếu quá trình lâu hơn bình thường, copy có thể đổi thành:

```text
Still analyzing. Some playlists or authenticated content may take longer.
```

Không dùng spinner vô hạn mà không có message.

Nút Cancel Analysis có thể xuất hiện nếu request thực sự có khả năng kéo dài.

---

## 9. Kết quả phân tích video

Sau khi analyze thành công, Home chuyển thành media configuration view.

```text
┌───────────────┐
│               │   Video title that may span two lines
│   Thumbnail   │   Channel name
│               │   12:42 • YouTube
└───────────────┘

Download as
[ Video ]  [ Audio ]

Quality
[ 1080p                                             ▾ ]

Format
[ MP4                                               ▾ ]

Save to
[ D:\Downloads\Videos                              📁 ]

▸ Advanced options

                                   [ Add to Downloads ]
```

Thumbnail không nên quá lớn. Nội dung chính của màn hình là lựa chọn tải, không phải thumbnail.

Title nên giới hạn khoảng hai dòng và có tooltip hoặc vùng mở rộng nếu quá dài.

Channel/uploader, duration và nguồn chỉ là secondary information.

---

## 10. Cách hiển thị chất lượng

Không hiển thị danh sách format raw như:

```text
137
248
616
399
```

Simple Mode nên map thành ngôn ngữ người dùng hiểu:

```text
Best available
2160p (4K)
1440p
1080p
720p
480p
```

Nếu có nhiều phiên bản cùng resolution, app tự chọn phương án hợp lý dựa trên preset nội bộ.

Có thể hiển thị thêm `60 FPS` khi đó là khác biệt đáng kể:

```text
1080p • 60 FPS
1080p
720p • 60 FPS
```

Không cần hiện codec ở đây.

Nếu resolution người dùng chọn không tồn tại, app không nên silently tải một chất lượng khác mà không nói. Có thể fallback nhưng phải hiển thị rõ trước khi bắt đầu.

---

## 11. Video và Audio Mode

`Video` và `Audio` là hai mode rõ ràng.

Khi chọn Video, app ưu tiên resolution và container.

Khi chọn Audio, các option chuyển thành:

```text
Audio quality
[ Best available                                     ▾ ]

Output
[ M4A                                                ▾ ]
```

Nếu chọn MP3 hoặc một định dạng cần conversion, nên ghi nhỏ:

```text
Requires media conversion after download
```

Không dùng wording quá kỹ thuật như "FFmpeg postprocessor" ở Simple Mode.

---

## 12. Save Location

Thư mục lưu mặc định được lấy từ Settings.

Người dùng có thể đổi location ngay tại task hiện tại mà không thay đổi default.

Cần phân biệt rõ:

```text
Use for this download
```

và

```text
Set as default download folder
```

Không nên tự thay default chỉ vì user chọn folder khác một lần.

---

# PHẦN IV — PLAYLIST

## 13. Khi URL là playlist

Nếu app phát hiện playlist, phần preview cần nói rõ ngay:

```text
Playlist
34 videos • Channel Name
```

Sau đó hiển thị danh sách item có checkbox.

```text
☑ Select all

☑ 01  Video title                              05:42
☑ 02  Another video                            12:11
☐ 03  Third video                              08:29
☑ 04  Another title                            03:55
```

Danh sách dài phải virtualize hoặc lazy render về mặt implementation, nhưng UX không cần nói điều đó với user.

Ở cuối hoặc sticky action area:

```text
31 selected

Quality [1080p ▾]       [Add 31 to Downloads]
```

Không tạo một download task duy nhất đại diện cho cả playlist nếu backend thực tế quản lý từng video. Playlist có thể là group, còn mỗi item vẫn là một task riêng để lỗi một video không làm cả playlist thất bại.

---

## 14. Playlist selection nhanh

Ngoài checkbox, nên có những lựa chọn hữu ích:

```text
Select all
Clear selection
Select range
```

`Select range` mở một control đơn giản:

```text
From  5
To    20
```

Không cần xây quá nhiều rule selection phức tạp ở V1.

---

# PHẦN V — DOWNLOADS

## 15. Downloads là trung tâm trạng thái của app

Màn hình này không chỉ là progress list. Nó là nơi user biết app đang làm gì.

Phía trên có summary ngắn:

```text
Downloads

2 active   4 queued   18 completed today
```

Sau đó chia thành section theo trạng thái thay vì tạo quá nhiều tab.

```text
Active
Queued
Recently completed
```

Nếu số lượng task lớn, có thể thêm filter sau.

---

## 16. Download task card

Mỗi task cần đủ thông tin nhưng không quá dày.

```text
┌──────────────────────────────────────────────────────┐
│ [thumb]  Video title                                 │
│          1080p • MP4                                 │
│                                                      │
│          ███████████████░░░░  74%                   │
│          8.2 MB/s • 128 MB / 173 MB • 00:11 left   │
│                                                      │
│                                 Pause      Cancel    │
└──────────────────────────────────────────────────────┘
```

Khi processing:

```text
Merging video and audio...
```

Progress bar có thể chuyển sang indeterminate nếu backend không có phần trăm chính xác.

Khi completed:

```text
Completed
[Open file] [Open folder]
```

Khi failed:

```text
Failed — Network connection was interrupted
[Retry] [Details]
```

Không hiển thị traceback trực tiếp trong card.

---

## 17. Task status language

Internal state có thể là enum kỹ thuật, nhưng UI dùng wording nhất quán:

```text
Analyzing
Waiting
Downloading
Processing
Paused
Completed
Failed
Cancelled
```

`Queued` có thể hiển thị là `Waiting` nếu muốn tự nhiên hơn với người dùng phổ thông.

Nếu task đang chờ vì giới hạn concurrent downloads, có thể ghi:

```text
Waiting — 3 downloads are currently active
```

---

## 18. Pause, Cancel và Retry

Không hiển thị action nếu backend không thật sự hỗ trợ đúng semantics.

Nếu Pause chỉ là dừng process để resume bằng partial file sau đó, UI vẫn có thể gọi là Pause, nhưng phải bảo đảm resume hoạt động có thể dự đoán được.

Cancel cần confirmation khi task đã tải đáng kể:

```text
Cancel this download?

Downloaded data may be kept temporarily so the task can be resumed later.

[Keep downloading] [Cancel download]
```

Nếu cancel đồng thời xóa partial file thì wording phải nói rõ.

Retry không yêu cầu user cấu hình lại task.

---

## 19. Bulk actions

Khi chọn nhiều task, action bar mới xuất hiện:

```text
3 selected
[Pause] [Resume] [Cancel]
```

Không để các bulk action luôn chiếm chỗ trên màn hình.

---

# PHẦN VI — HISTORY

## 20. History

History là nơi xem kết quả đã hoàn thành hoặc đã thất bại trong quá khứ.

Nó không phải Downloads phiên bản thứ hai.

Mỗi row có thể gồm:

```text
Thumbnail | Title | Quality | Date | Status | Actions
```

Action phổ biến:

```text
Open file
Open folder
Download again
Copy source URL
Remove from history
```

Nếu file đã bị user xóa ngoài app, `Open file` phải chuyển thành trạng thái:

```text
File not found
```

và có thể cung cấp `Download again`.

---

## 21. Xóa History

`Remove from history` không được mặc định xóa file.

Nếu user muốn xóa cả file, đó phải là action riêng:

```text
Remove history entry
Delete downloaded file
```

Nếu thiết kế dialog:

```text
Remove this item from history?

☐ Also delete the downloaded file from disk
```

Checkbox mặc định tắt.

---

# PHẦN VII — ADVANCED OPTIONS

## 22. Advanced không được biến thành một màn hình hỗn loạn

Các option nâng cao nên chia thành nhóm nhỏ.

Ví dụ:

```text
Advanced options

Video
Quality behavior
Codec
FPS

Audio
Codec
Conversion

Extras
Subtitles
Thumbnail
Metadata
Chapters

Authentication
Browser session

Technical
Custom format / arguments
```

Không cần triển khai toàn bộ ngay V1. Structure này giúp mở rộng mà không phá layout.

---

## 23. Subtitle

Subtitle control cần phân biệt hai loại:

```text
Uploaded subtitles
Auto-generated subtitles
```

Ví dụ:

```text
Subtitles
[ Vietnamese ▾ ]

Output
○ Embed when supported
● Save as separate file
```

Nếu không có subtitle:

```text
No subtitles were found for this media.
```

Không để dropdown trống mà không giải thích.

---

## 24. Chapter và metadata

Các option này nên là checkbox hoặc switch đơn giản:

```text
☑ Keep chapters
☑ Embed thumbnail
☑ Embed media metadata
☐ Save description
```

Nếu một lựa chọn làm tăng thời gian processing, có thể ghi chú ngắn bên dưới.

---

## 25. Authenticated content

Nếu user muốn dùng browser session hợp lệ của chính họ, wording nên trung tính:

```text
Browser session
Use an existing browser session for content that requires you to be signed in.
```

Các lựa chọn có thể là:

```text
None
Chrome
Edge
Firefox
```

Không dùng wording như `Bypass`, `Unlock` hoặc `Premium bypass`.

Nếu tài khoản không có quyền:

```text
This account does not have access to this content.
```

Không gợi ý rằng app có thể vượt qua authorization.

---

# PHẦN VIII — SETTINGS

## 26. Cấu trúc Settings

Settings nên dùng navigation phụ hoặc section theo chiều dọc.

### General

```text
Theme
System / Light / Dark

Language
English / Vietnamese

Start behavior
Optional startup preferences
```

### Downloads

```text
Default folder
Default quality
Default output format
Concurrent downloads
Filename template
```

### Media

```text
Default audio output
Subtitle preference
Metadata defaults
```

### Advanced

```text
yt-dlp status
FFmpeg status
Browser session
Proxy
Custom arguments
Logs
```

Không đưa technical dependency lên General Settings.

---

## 27. Dependency status

Vì app phụ thuộc `yt-dlp` và FFmpeg, Settings nên hiển thị trạng thái dễ hiểu:

```text
yt-dlp
Ready • version x.x.x

FFmpeg
Ready • version x.x
```

Nếu thiếu:

```text
FFmpeg
Not available
Some formats may not be merged or converted.

[Configure]
```

Không hiện một lỗi kỹ thuật ngay khi app mở nếu user chưa thực hiện tác vụ cần FFmpeg. Tuy nhiên first-run check vẫn nên phát hiện sớm để tránh lỗi bất ngờ về sau.

---

# PHẦN IX — FIRST RUN EXPERIENCE

## 28. Lần chạy đầu tiên

Không cần tutorial nhiều trang.

App chỉ cần kiểm tra những thứ thiết yếu và đưa user tới Home nhanh nhất có thể.

Nếu mọi dependency sẵn sàng:

```text
Ready to download
Paste a media URL to get started.
```

Nếu thiếu một dependency quan trọng:

```text
One component needs attention

FFmpeg was not found. Basic downloads may still work, but merging or conversion can fail.

[Configure now] [Continue]
```

Không chặn toàn bộ app nếu component đó chưa cần cho mọi tác vụ.

---

# PHẦN X — ERROR UX

## 29. Lỗi phải trả lời được “chuyện gì xảy ra và tôi làm gì tiếp?”

Thông báo lỗi tốt:

```text
Download failed
The network connection was interrupted.

[Retry]
```

Thông báo lỗi kém:

```text
ERROR: HTTP Error 403: Forbidden
```

Raw error vẫn được giữ trong Details hoặc log.

Các nhóm lỗi cần có wording riêng:

```text
Invalid URL
Unsupported URL
Media unavailable
Sign-in required
Access not permitted
Network unavailable
Not enough disk space
FFmpeg unavailable
Output file conflict
Unexpected processing error
```

---

## 30. Error Details

`Details` dành cho user kỹ thuật hoặc debug.

Có thể chứa:

```text
Task ID
Source
Current stage
Technical message
Timestamp
```

Có action:

```text
Copy details
Open logs
```

Không để technical detail làm message chính.

---

# PHẦN XI — EMPTY, LOADING VÀ EDGE STATES

## 31. Empty states

Downloads trống:

```text
No downloads yet
Add a media URL from Home to start a download.

[Go to Home]
```

History trống:

```text
Your download history will appear here.
```

Không dùng những câu marketing dài trong empty state.

---

## 32. File đã tồn tại

Không nên silently overwrite.

Dialog có thể là:

```text
A file with this name already exists.

○ Keep existing file and rename the new one
○ Replace existing file
○ Skip this download

☐ Apply to remaining items in this playlist
```

Lựa chọn an toàn nhất nên là mặc định: rename hoặc skip, không phải replace.

---

## 33. Không đủ dung lượng

Nếu có thể ước lượng kích thước trước, app nên cảnh báo trước khi download.

```text
Not enough free space
This download needs approximately 4.8 GB, but only 2.1 GB is available.

[Choose another folder]
```

Nếu không thể ước lượng chính xác, wording phải nói `approximately`.

---

# PHẦN XII — WINDOWS-SPECIFIC UX

## 34. System tray

System tray hữu ích khi user đóng/minimize cửa sổ nhưng task vẫn chạy.

Tray menu chỉ cần:

```text
Open app
Active downloads: 2
Pause all
Exit
```

Nếu user bấm nút Close trong lúc còn download, lần đầu nên hỏi:

```text
Downloads are still running.

○ Minimize to tray and keep downloading
○ Cancel downloads and exit

☐ Remember my choice
```

Không tự terminate task mà không nói.

---

## 35. Windows notifications

Notification chỉ nên dùng cho sự kiện có giá trị:

```text
Download completed
Download failed
Playlist completed
```

Không notification mỗi khi task bắt đầu hoặc chuyển trạng thái nhỏ.

Click notification nên mở đúng task trong app hoặc mở file khi hợp lý.

---

## 36. Keyboard support

Desktop tool nên có keyboard shortcuts cơ bản:

```text
Ctrl + V     Paste URL
Ctrl + L     Focus URL input
Ctrl + ,     Settings
Ctrl + J     Downloads
Ctrl + H     History
Esc          Close transient dialog / selection
```

Không cần quá nhiều shortcut ở V1.

Tab navigation phải hoạt động đúng thứ tự.

---

# PHẦN XIII — RESPONSIVE WINDOW TRÊN DESKTOP

## 37. Không coi desktop là một kích thước cố định

Ứng dụng cần sử dụng tốt khi window lớn hoặc nhỏ.

Có thể chia theo ba mức tư duy:

```text
Large      ≥ 1200 px
Standard   900–1199 px
Compact    700–899 px
```

Đây không phải breakpoint bắt buộc theo pixel tuyệt đối. Mục tiêu là xác định behavior.

### Large

Media preview và options có thể đặt hai cột nếu hợp lý.

### Standard

Dùng layout một cột rộng, sidebar đầy đủ.

### Compact

Sidebar chuyển icon-only. Media preview stack theo chiều dọc. Các action quan trọng vẫn phải nhìn thấy mà không scroll ngang.

Không hỗ trợ cửa sổ nhỏ đến mức layout trở thành mobile giả lập. Nên đặt minimum window size hợp lý.

---

# PHẦN XIV — VISUAL SYSTEM

## 38. Phong cách tổng thể

Visual direction nên gần với Windows 11 Fluent nhưng không cần sao chép hoàn toàn.

App nên có cảm giác:

```text
Clean
Quiet
Fast
Technical but approachable
```

Không dùng quá nhiều gradient, glass effect hoặc animation chỉ để trang trí.

Phần media thumbnail đã có nhiều màu sắc, vì vậy chrome của app nên trung tính để không cạnh tranh thị giác.

---

## 39. Spacing

Dùng spacing scale nhất quán thay vì mỗi component một khoảng cách khác nhau.

Ví dụ:

```text
4   micro spacing
8   small
12  compact
16  standard
24  section
32  large section
```

Không cần user biết scale này, nhưng toàn bộ app phải có nhịp spacing thống nhất.

---

## 40. Border radius

Card, input và button nên dùng radius vừa phải.

Khoảng 8–12 px thường phù hợp với desktop hiện đại.

Không bo tròn quá mức như mobile consumer app nếu điều đó làm giảm mật độ thông tin.

---

## 41. Typography

Ưu tiên font hệ thống hoặc font phù hợp Windows để rendering ổn định.

Hierarchy gợi ý:

```text
Page title       24–28
Section title    18–20
Body             14–15
Secondary        12–13
```

Không dùng quá nhiều font weight.

Title video có thể semi-bold. Metadata và supporting text dùng regular hoặc secondary tone.

---

## 42. Color semantics

Màu accent dùng cho primary action và selected navigation.

Status color chỉ mang ý nghĩa nhất quán:

```text
Success     Completed
Warning     Attention / paused / partial issue
Error       Failed
Accent      Active / selected / primary action
Neutral     Waiting / metadata
```

Không chỉ dựa vào màu để truyền trạng thái. Icon hoặc text luôn đi cùng.

Ví dụ không chỉ có chấm đỏ; phải có `Failed`.

---

## 43. Dark Mode

Dark Mode phải được thiết kế như một theme thật sự.

Không đảo màu máy móc.

Thumbnail, separator, input, hover, disabled state và focus ring đều phải có contrast phù hợp.

Nếu chọn `System`, app theo Windows appearance và phản ứng khi hệ thống đổi theme nếu framework cho phép.

---

# PHẦN XV — COMPONENT RULES

## 44. Buttons

Một màn hình chỉ nên có một primary action nổi bật.

Ví dụ Media Details:

```text
Primary     Add to Downloads
Secondary   Change folder
Tertiary    Advanced options
```

Không biến `Cancel`, `Open folder`, `Retry`, `Settings` thành cùng một mức nổi bật.

Danger action như delete file hoặc cancel playlist nên có visual treatment riêng nhưng không quá hung hăng.

---

## 45. Inputs

URL input cần:

- Paste action.
- Clear action khi có nội dung.
- Validation state.
- Keyboard focus rõ.

Không validate URL quá sớm khi user vẫn đang gõ. Paste thì có thể validate ngay.

---

## 46. Dropdown / Combo box

Dropdown đơn giản dùng cho danh sách ngắn như Quality, Format, Language.

Nếu danh sách subtitle hoặc playlist rất dài, dùng searchable selection thay vì combo box khổng lồ.

Option không khả dụng nên disable kèm lý do khi cần, thay vì biến mất nếu việc biến mất gây khó hiểu.

---

## 47. Progress

Progress bar luôn đi cùng text khi task đang chạy.

```text
74%
128 MB / 173 MB
8.2 MB/s
00:11 remaining
```

Không bắt buộc phải hiển thị tất cả nếu backend chưa có dữ liệu. Không dùng `0 MB/s` khi speed chưa xác định; dùng `—` hoặc ẩn field.

ETA là estimate, không được trình bày như thời gian chính xác tuyệt đối.

---

## 48. Tooltips

Tooltip dành cho icon action không có label và technical metadata.

Không dùng tooltip để giấu thông tin quan trọng. Nếu user cần biết một setting làm gì để quyết định, description phải nằm trên màn hình.

---

# PHẦN XVI — MICROCOPY

## 49. Ngôn ngữ giao diện

Copy nên ngắn và nói đúng hành động.

Tốt:

```text
Add to Downloads
Open folder
Retry
Choose another folder
```

Không nên:

```text
Proceed with media acquisition
Execute download operation
```

Technical terminology chỉ dùng ở Advanced hoặc Details.

---

## 50. Không dùng wording gây hiểu nhầm về quyền truy cập

App là downloader sử dụng quyền hiện có của user, không phải công cụ phá access control.

Vì vậy dùng:

```text
Sign-in required
Use browser session
Access not permitted
```

Không dùng:

```text
Bypass
Unlock Premium
Crack access
Force download
```

---

# PHẦN XVII — ACCESSIBILITY

## 51. Keyboard và focus

Mọi control chính phải dùng được bằng keyboard.

Focus state phải nhìn thấy rõ ở Light và Dark Mode.

Không tự động chuyển focus bất ngờ khi progress update.

Nếu download card liên tục render lại, focus của user không được bị mất.

---

## 52. Contrast và trạng thái

Text phụ vẫn phải đủ contrast.

Disabled state phải khác Enabled nhưng vẫn đọc được.

Không truyền thông tin chỉ bằng màu.

Icon-only button cần accessible label hoặc tooltip phù hợp.

---

## 53. Motion

Animation chỉ dùng để giúp hiểu state transition.

Ví dụ expand Advanced, card được thêm vào queue hoặc progress state đổi có thể animate nhẹ.

Tôn trọng Windows reduced motion nếu có thể.

Không dùng animation dài trong tác vụ lặp lại thường xuyên.

---

# PHẦN XVIII — PRIVACY UX

## 54. Browser session và dữ liệu cá nhân

Nếu app đọc browser cookies/session, user phải chủ động bật tính năng đó.

UI phải nói rõ browser nào được dùng và mục đích là gì.

Không nên có toggle mặc định bật kiểu:

```text
Automatically import all browser cookies
```

Nếu app lưu cấu hình liên quan session, không hiển thị token/cookie raw trên màn hình.

---

## 55. Logs

Log có thể chứa URL, path hoặc technical information.

Khi user chọn `Copy diagnostics`, app nên cố tránh đưa credential hoặc cookie vào clipboard.

UX cần coi log là dữ liệu kỹ thuật, không phải nơi lưu secret.

---

# PHẦN XIX — UX CHO CÁC TÌNH HUỐNG THỰC TẾ

## 56. User paste URL mới khi đang cấu hình video cũ

Không silently thay nội dung hiện tại nếu user đã thay đổi option.

Có thể analyze URL mới nhưng nếu cấu hình hiện tại chưa được download, hỏi nhẹ:

```text
Replace the current media?
Your current download options will be cleared.

[Keep current] [Analyze new URL]
```

Nếu chưa chỉnh gì, có thể thay trực tiếp.

---

## 57. App restart khi task chưa hoàn tất

Khi mở lại, Downloads phải phản ánh state thật.

Task đang chạy trước khi app tắt không được hiển thị `Downloading` mãi.

Có thể chuyển thành:

```text
Interrupted
[Resume]
```

hoặc tự resume nếu user đã bật preference rõ ràng.

---

## 58. yt-dlp không còn tương thích với nguồn

Thông báo cần phân biệt app lỗi với extractor/source thay đổi.

Ví dụ:

```text
This source could not be analyzed with the current downloader engine.
Updating yt-dlp may resolve the issue.

[Check for update] [View details]
```

Không kết luận `Video unavailable` nếu chưa chắc.

---

## 59. FFmpeg processing thất bại sau khi download xong

Đây là trường hợp cần wording chính xác.

Không hiển thị `Download failed` nếu media stream đã tải thành công nhưng merge lỗi.

Nên ghi:

```text
Media downloaded, but final processing failed.

[Retry processing] [Open temporary files] [Details]
```

Nếu app có khả năng retry chỉ processing, không bắt tải lại toàn bộ.

---

# PHẦN XX — ƯU TIÊN TRIỂN KHAI V1

## 60. V1 cần có

V1 UI nên hoàn thiện thật tốt luồng cơ bản trước:

```text
Home
Paste / Analyze URL
Video preview
Video / Audio mode
Quality
Format
Save location
Add to Downloads
Downloads queue
Progress
Completed / Failed states
History
Settings cơ bản
Light / Dark / System theme
```

Playlist có thể nằm cuối V1 hoặc đầu V1.1 tùy effort của backend.

---

## 61. V1 không nên ôm quá nhiều

Các phần sau có thể để sau nếu làm chậm core flow:

```text
Complex format editor
Advanced proxy UI
Chapter cutting timeline
Comment download
Power-user command builder
Large-scale batch rules
Plugin marketplace
```

Một downloader có 10 option nhưng ổn định tốt hơn một app có 80 option nhưng khó hiểu và nhiều state lỗi.

---

# PHẦN XXI — HƯỚNG MỞ RỘNG MOBILE / WEB

## 62. Mobile sau này không phải bản desktop thu nhỏ

Nếu có Android trong tương lai, logic nghiệp vụ có thể giữ tương đồng nhưng navigation và interaction phải thay đổi.

Sidebar sẽ chuyển thành bottom navigation:

```text
Home
Downloads
History
Settings
```

Dropdown có thể chuyển thành bottom sheet.

Share Intent từ YouTube hoặc browser sẽ trở thành entry point quan trọng hơn paste URL thủ công.

Download task card sẽ stack theo chiều dọc và action có touch target lớn hơn.

Những thay đổi này nên được coi là một UX implementation riêng, không phải responsive CSS của desktop.

---

## 63. Web nếu có sau này

Web version sẽ gặp những ràng buộc khác hẳn như browser sandbox, filesystem, download behavior, authentication và backend processing.

Vì vậy không nên hứa rằng toàn bộ capability desktop có thể chuyển nguyên trạng sang web.

Nếu có web client sau này, document này chỉ nên được dùng như nguồn tham khảo về information architecture, naming và task lifecycle. Interaction và backend architecture cần được thiết kế lại theo môi trường web.

---

# PHẦN XXII — DEFINITION OF DONE CHO UI/UX

## 64. Một màn hình chỉ được coi là hoàn thành khi xử lý đủ state

Không chỉ thiết kế happy path.

Mỗi feature cần xem tối thiểu:

```text
Empty
Loading
Success
Partial / unavailable data
Error
Disabled
Long text
Small window
Dark mode
Keyboard focus
```

Ví dụ Video Details chưa hoàn thành nếu chỉ đẹp với video title ngắn và đầy đủ thumbnail.

---

## 65. UX review trước khi merge feature

Trước khi xem một UI feature là hoàn thành, cần tự hỏi:

- User có biết bước tiếp theo là gì không?
- Có nhiều hơn một primary action cạnh tranh nhau không?
- Error có nói cách khắc phục không?
- Long title có phá layout không?
- Mất mạng giữa chừng thì màn hình trông thế nào?
- User có biết file cuối nằm ở đâu không?
- Window nhỏ hơn có còn dùng được không?
- Keyboard navigation có hợp lý không?
- Dark Mode có thực sự đọc được không?
- App có đang để lộ thuật ngữ nội bộ của `yt-dlp` cho user phổ thông không?

Nếu một câu trả lời chưa rõ, phần đó chưa thật sự xong.

---

# PHẦN XXIII — TÓM TẮT HƯỚNG THIẾT KẾ

Ứng dụng nên được nhìn như một **desktop media download manager**, không phải một terminal command builder.

Home chỉ làm một việc thật tốt: nhận URL và tạo download.

Downloads là source of truth trực quan cho các task đang chạy.

History quản lý những gì đã xảy ra, không can thiệp vào file nếu user chưa yêu cầu.

Settings giữ các preference lâu dài, còn option của từng download nằm ngay tại Home.

Simple Mode phục vụ hầu hết người dùng. Advanced Mode mở sức mạnh của `yt-dlp` khi thật sự cần.

Toàn bộ giao diện phải phản ánh đúng lifecycle:

```text
Analyze
→ Configure
→ Queue
→ Download
→ Process
→ Complete
```

Nếu giữ được flow này rõ ràng, app sẽ vẫn dễ sử dụng kể cả khi backend sau này có thêm playlist, subtitle, chapter, browser session hoặc nhiều nền tảng khác.
