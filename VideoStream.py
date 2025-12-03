class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except:
            raise IOError
        self.frameNum = 0

    def nextFrame(self):
        """Get next frame from proprietary MJPEG file.

        Định dạng lab:
        - Mỗi frame: 5 byte đầu là độ dài (ASCII), VD: b'01234'
        - Sau đó là đúng `length` byte JPEG.
        """
        # Đọc 5 byte đầu chứa độ dài frame (dạng text)
        length_bytes = self.file.read(5)

        if length_bytes:
            try:
                # Chuyển bytes -> string -> int
                frame_length = int(length_bytes.decode())
            except Exception as e:
                print("Error: Invalid frame length header:", length_bytes, e)
                return None

            # Đọc đúng số byte của frame
            data = self.file.read(frame_length)
            if not data or len(data) != frame_length:
                print("Error: Unexpected end of file when reading frame data")
                return None

            self.frameNum += 1
            print(f"[VideoStream] Read frame {self.frameNum}, length: {frame_length}")
            return data

        # EOF
        return None

    def frameNbr(self):
        """Get frame number."""
        return self.frameNum

    def reset(self):
        """Reset stream to beginning."""
        self.file.seek(0)
        self.frameNum = 0
