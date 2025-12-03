# VideoStreamHD.py
# Đọc file MJPEG HD: mỗi frame là 1 JPEG từ SOI (0xFFD8) tới EOI (0xFFD9)

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
        self.buffer = b''

    def _seek_soi(self):
        """Đảm bảo buffer bắt đầu bằng SOI."""
        while True:
            idx = self.buffer.find(self.SOI)
            if idx != -1:
                self.buffer = self.buffer[idx:]
                return True

            chunk = self.file.read(4096)
            if not chunk:
                return False
            self.buffer += chunk

    def nextFrame(self):
        """
        Trả về 1 frame JPEG đầy đủ (SOI..EOI).
        Nếu hết file, trả về None.
        """
        if not self._seek_soi():
            return None

        while True:
            idx = self.buffer.find(self.EOI, 2)  # tìm từ sau SOI
            if idx != -1:
                end = idx + len(self.EOI)
                frame = self.buffer[:end]
                self.buffer = self.buffer[end:]
                self.frameNum += 1
                # print(f"[VideoStreamHD] Read frame {self.frameNum} ({len(frame)} bytes)")
                return frame

            chunk = self.file.read(4096)
            if not chunk:
                return None
            self.buffer += chunk

    def frameNbr(self):
        return self.frameNum

    def reset(self):
        self.file.seek(0)
        self.buffer = b''
        self.frameNum = 0
