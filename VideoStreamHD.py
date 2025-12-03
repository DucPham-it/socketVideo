# VideoStreamHD.py
#
# Đọc file MJPEG "raw": một chuỗi các ảnh JPEG nối tiếp nhau.
# Mỗi frame = bytes từ SOI (0xFFD8) tới EOI (0xFFD9).
# Dùng buffer 4KB để tìm marker, tránh cắt frame -> Pillow không báo truncated.

class VideoStreamHD:
    SOI = b'\xff\xd8'  # Start of Image
    EOI = b'\xff\xd9'  # End of Image

    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except:
            raise IOError(f"Cannot open file {filename}")
        self.frameNum = 0
        self.buffer = b''  # buffer tạm để tìm marker

    def nextFrame(self):
        """
        Trả về 1 frame JPEG đầy đủ (SOI..EOI).
        Nếu hết file, trả về None.
        """

        # 1. Tìm SOI
        if not self._seek_soi():
            return None  # không còn frame nào

        # bây giờ buffer chắc chắn bắt đầu bằng SOI
        # 2. Tìm EOI
        while True:
            idx = self.buffer.find(self.EOI, 2)  # tìm từ sau SOI
            if idx != -1:
                end = idx + len(self.EOI)
                frame = self.buffer[:end]
                # giữ lại phần sau frame trong buffer để dùng cho lần sau
                self.buffer = self.buffer[end:]
                self.frameNum += 1
                # print(f"[VideoStreamHD] Read frame {self.frameNum} ({len(frame)} bytes)")
                return frame

            # chưa thấy EOI -> đọc thêm
            chunk = self.file.read(4096)
            if not chunk:
                # EOF mà vẫn chưa có EOI -> coi như hết, bỏ luôn
                return None
            self.buffer += chunk

    def _seek_soi(self):
        """
        Đảm bảo buffer bắt đầu bằng SOI.
        Trả về True nếu tìm được SOI, False nếu EOF.
        """
        while True:
            idx = self.buffer.find(self.SOI)
            if idx != -1:
                # bỏ phần rác trước SOI
                self.buffer = self.buffer[idx:]
                return True

            # nếu không thấy trong buffer hiện tại -> đọc thêm
            chunk = self.file.read(4096)
            if not chunk:
                # EOF -> không còn frame
                return False
            self.buffer += chunk

    def frameNbr(self):
        return self.frameNum

    def reset(self):
        """Đặt con trỏ file về đầu, xoá buffer, reset frameNum."""
        self.file.seek(0)
        self.buffer = b''
        self.frameNum = 0
