# VideoLoader.py
from VideoStream import VideoStream
from VideoStreamHD import VideoStreamHD

def is_basic_mjpeg(filename):
    """
    Basic format lab: 5 byte đầu là ASCII digits ('0'..'9').
    HD/raw MJPEG: thường không như vậy.
    """
    with open(filename, 'rb') as f:
        first5 = f.read(5)
        if len(first5) < 5:
            return False
        return all(48 <= b <= 57 for b in first5)

def load_video(filename):
    if is_basic_mjpeg(filename):
        print(f"[VideoLoader] Detected BASIC MJPEG -> VideoStream")
        return VideoStream(filename)
    else:
        print(f"[VideoLoader] Detected HD MJPEG -> VideoStreamHD")
        return VideoStreamHD(filename)
