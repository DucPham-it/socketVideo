## 1. Mục tiêu
Dự án mô phỏng hệ thống **streaming video thời gian thực** sử dụng:
- **Giao thức RTSP (TCP)** để điều khiển (SETUP / PLAY / PAUSE / TEARDOWN).
- **Giao thức RTP (UDP)** để truyền dữ liệu video.
- **Jitter buffer client-side** để phát lại mượt trên đường truyền không ổn định.
- **Fragmented RTP per frame** (chia frame thành nhiều packet) để truyền video HD / khung hình lớn.

- Hỗ trợ file MJPEG HD thật (JPEG toàn vẹn với SOI–EOI)
- Reassembly packet theo `marker bit`
- Thanh progress 
- Thống kê network (packet loss, frame loss, bitrate)

---

## 2. Kiến trúc toàn hệ thống

### 2.1 Thành phần hệ thống

#### 1️⃣ Client
- Giao diện Tkinter
- Nhận gói RTP
- **Ghép (reassemble)** từng frame từ nhiều packet
- Cache frame → Playback mượt
- Điều khiển RTSP

Mã chính nằm trong **Client.py**

#### 2️⃣ Server
- Lắng nghe RTSP (TCP)
- Load video (Basic hoặc HD MJPEG)
- Gửi frame → chia thành nhiều packet
- Gửi qua UDP đến Client

#### 3️⃣ Video Loader
Tự động detect loại file:
- MJPEG Basic Lab → **VideoStream**
- MJPEG HD Real JPEG → **VideoStreamHD**

---

## 3. Định dạng video

### 3.1 MJPEG Basic
Cấu trúc mỗi frame: [5 byte ASCII length] [JPEG data]


### 3.2 MJPEG HD (True JPEG)
File có các marker JPEG:
- SOI = `FF D8`
- EOI = `FF D9`

---

## 4. Giao thức RTSP

### Chuỗi lệnh theo trạng thái
INIT ──SETUP──▶ READY ─ PLAY ─▶ PREBUFFERING ─ sufficient N frame ─▶ PLAYING

---

## 5. RTP Layer

### 5.1 RTP Packet Format
Header 12 byte gồm:
- Version 2
- Sequence number (16 bit)
- Timestamp (32 bit)
- **Marker bit** (đánh dấu packet cuối của frame)
- Payload: dữ liệu JPEG.

---

## 6. Xử lý phía server

### 6.1 Phân mảnh RTP
Server **không truyền 1 frame = 1 RTP**, mà:

frame JPEG → chia thành nhiều packet < MTU (1300)
packet cuối đặt marker = 1


### 6.2 Vòng send frame (25fps)
event.wait(0.04)
---

## 7. Xử lý phía client

### 7.1 Buffering 30 frame
- Frame loss → drop toàn bộ frame
- Khi nhận packet marker=1 → kết thúc frame

### 7.2 PREBUFFERING → PLAYING
Chỉ khi đủ 30 frame:
buffer >= bufferSize → PLAYING


### 7.3 Playback Scheduler
every 40ms → pop 1 frame → update GUI

---

## 8. Thanh progress giống YouTube

- Xám = buffered
- Đỏ = đã play

---

## 9. Thống kê mạng (Stats)

Khi Teardown:
- Tổng packet nhận
- Packet loss rate
- Frame dropped
- Bitrate thực tế

---

## 10. Cách chạy

### Server:
python3 Server.py <Server Port>

### Client:
python3 ClientLauncher.py <server_ip> <server_port> <rtp_port> <video_file>

---

## 11. Test và đánh giá
- Streaming ổn định
- Prebuffer=30 giúp giảm jitter
- HD → 3–10 packet/frame

---

# 🎯 Kết luận
Dự án minh họa pipeline truyền video real-time có jitter.
Client phát theo buffer + timer thay vì tốc độ mạng → playback mượt.

