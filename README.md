# 🎬 Real-Time MJPEG Streaming Client (RTSP + RTP Fragmentation)

Client Python mô phỏng hệ thống **streaming video thời gian thực**, hỗ trợ:

- **RTSP/TCP** cho điều khiển: SETUP / PLAY / PAUSE / TEARDOWN  
- **RTP/UDP + phân mảnh payload từng frame (fragmentation)**  
- **Reassembly packet → JPEG hoàn chỉnh**  
- **Jitter buffer 30 frames** để phát mượt khi mạng không ổn định  
- **Progress bar dạng thông số**  
- **Thống kê network khi teardown**  

---

## 1. Kiến trúc tổng quan

Client gồm bốn thành phần chính:

### 1. RTSP Controller
- Gửi lệnh RTSP  
- Nhận phản hồi và cập nhật trạng thái: INIT → READY → PREBUFFERING → PLAYING  
- Quản lý session ID, CSeq

### 2. RTP Receiver + Frame Reassembly
- Nhận RTP qua UDP  
- Kiểm tra sequence number, packet loss  
- Ghép payload thành frame JPEG  
- Marker bit (`1`) đánh dấu packet cuối của frame  
- Drop frame nếu phát hiện mất gói trong cùng frame

### 3. Jitter Buffer (Frame Queue)
- Cấu trúc: `deque()`  
- Dung lượng mặc định: **30 frames**  
- PREBUFFERING cho đến khi buffer đủ 30 frames  
- Playback luôn đều 40ms/frame (25 FPS)

### 4. Playback/UI (Tkinter + PIL)
- Hiển thị video từ file tạm `cache-<session>.jpg`  
- Nút điều khiển: Setup / Play / Pause / Teardown  
- Nhãn thống kê realtime: Played / In-buffer / Total buffered  

---

## 2. Luồng hoạt động
INIT → SETUP → READY → PLAY → PREBUFFERING → PLAYING

### Mô tả nhanh:

- **SETUP**: mở RTSP session, bind RTP port  
- **PLAY**: chuyển sang PREBUFFERING → nhận frame nhưng chưa phát  
- Khi buffer đủ 30 frames → chuyển sang **PLAYING**  
- **PLAYING**: 40ms → phát 1 frame từ buffer  
- **PAUSE**: dừng playback nhưng giữ session  
- **TEARDOWN**: đóng session + xuất thống kê

---

## 3. RTP Fragmentation & Reassembly

### Server gửi (yêu cầu server phải hỗ trợ):
Frame JPEG → chia thành nhiều RTP packet (<1300 bytes)
Packet cuối → marker = 1

### Client xử lý:
- Kiểm tra thứ tự gói (sequence number)  
- Nếu mất packet → flag `frameCorrupted = True`  
- Append payload vào `currentFrameData`  
- Khi gặp marker = 1:
  - Nếu không lỗi → đưa frame vào `frameBuffer`
  - Nếu lỗi → tăng bộ đếm dropped  
- Reset trạng thái để nhận frame tiếp theo

---

## 4. Jitter Buffer & Playback

### Jitter Buffer (deque)
- Ngăn xếp FIFO lưu các frame đã hoàn chỉnh  
- Nếu đầy → drop frame cũ nhất (giảm latency)

### Playback Loop (40ms)
- Nếu đang PLAYING:  
  - Pop 1 frame  
  - Ghi ra file cache  
  - Hiển thị bằng Tkinter  
  - Cập nhật số liệu Played / In-buffer  

---

## 5. Giao diện người dùng

### Nút điều khiển:
- **Setup**
- **Play**
- **Pause**
- **Teardown**

### Label chính:
- Khung hiển thị video  
- Trạng thái RTSP: INIT / READY / PREBUFFERING / PLAYING  
- Thông số:
Played: X | In-buffer: Y | Total live: X+Y | Total buffered: Z

---

## 6. RTSP Layer

### Ví dụ lệnh gửi:
SETUP movie.MJPEG RTSP/1.0
CSeq: 1
Transport: RTP/UDP; client_port=5000

### PLAY:
PLAY movie.MJPEG RTSP/1.0
CSeq: 2
Session: 12345

### PAUSE / TEARDOWN tương tự.

---

## 7. Thống kê mạng (in ra khi TEARDOWN)

Client in ra:

Total RTP packets received
Packets lost (ước lượng)
Packet loss rate %
Frames completed
Frames dropped
Frame loss rate %
Playback time
Approx. received bitrate (kbps)


Các thống kê giúp đánh giá chất lượng đường truyền.

---

## 8. Cách chạy

### Chạy Client:
`python3 ClientLauncher.py <server_ip> <server_port> <rtp_port> <video_file>`

ví dụ:
`python3 ClientLauncher.py 127.0.0.1 8554 5000 movie.mjpeg`

### Server yêu cầu:
- Trả về video MJPEG đã phân mảnh RTP  
- Đặt marker bit = 1 cho packet cuối frame  
- Tăng sequence number đúng chuẩn  

---

## 9. Cache Frame

Client ghi frame mới nhất vào:
`cache-<session>.jpg`

File sẽ bị ghi đè liên tục và bị xóa khi teardown.

---

## 10. Kết luận

Hệ thống streaming này tái hiện pipeline thực tế:

- RTSP điều khiển phiên  
- RTP gửi video phân mảnh  
- Reassembly phía client  
- Jitter buffer để phát mượt  
- Playback tách biệt hoàn toàn tốc độ mạng  

Dễ sử dụng, dễ mở rộng sang:
- Adaptive Bitrate  
- FEC / retransmission  
- Timeline dạng YouTube  
- Buffer visualization  

---
