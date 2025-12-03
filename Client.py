from tkinter import *
from tkinter import messagebox as tkMessageBox
from PIL import Image, ImageTk,ImageFile
import socket, threading, sys, traceback, os
from collections import deque
import time

from RtpPacket import RtpPacket

ImageFile.LOAD_TRUNCATED_IMAGES = True

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"


class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3

    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()

        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename

        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0

        # RTP-related
        self.rtpSocket = None
        self.frameNbr = 0

        # Event để dừng thread nghe RTP khi pause/teardown
        self.playEvent = threading.Event()

        # ----- Client-side caching (frame buffer) -----
        self.bufferSize = 60          # N frames pre-buffer
        self.frameBuffer = deque()    # Lưu đường dẫn file cache
        self.buffering = False        # Đang ở trạng thái buffer hay đã play

        # ----- Statistics -----
        self.totalFramesReceived = 0
        self.lostFrames = 0
        self.startPlayTime = None

        self.connectToServer()

    # --------------------------------------------------------
    # GUI
    # --------------------------------------------------------
    def createWidgets(self):
        """Build GUI."""
        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        # Create Play button
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        # Create Pause button
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)

        # Create a label to display the movie
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4,
                        sticky=W + E + N + S, padx=5, pady=5)

    # --------------------------------------------------------
    # Button handlers
    # --------------------------------------------------------
    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)

    def exitClient(self):
        """Teardown button handler."""
        if self.state != self.INIT:
            self.sendRtspRequest(self.TEARDOWN)
        # Dừng thread RTP nếu đang chạy
        self.playEvent.set()
        self.clearBuffer()

        self.master.destroy()
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Bắt đầu ở trạng thái buffering
            self.buffering = True
            self.clearBuffer()
            self.frameNbr = 0

            # Tạo thread nghe RTP
            threading.Thread(target=self.listenRtp, daemon=True).start()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)

    # --------------------------------------------------------
    # RTP handling + client-side caching
    # --------------------------------------------------------
    def listenRtp(self):
        """Listen for RTP packets."""
        while True:
            try:
                data = self.rtpSocket.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)

                    currFrameNbr = rtpPacket.seqNum()
                    print("Current Seq Num: " + str(currFrameNbr))

                    # Thống kê mất frame
                    if self.frameNbr != 0 and currFrameNbr > self.frameNbr + 1:
                        self.lostFrames += (currFrameNbr - self.frameNbr - 1)

                    if currFrameNbr > self.frameNbr:
                        self.frameNbr = currFrameNbr
                        self.totalFramesReceived += 1

                        # Ghi ra file cache và đẩy vào buffer
                        frameFile = self.writeFrame(rtpPacket.getPayload())
                        self.frameBuffer.append(frameFile)

                        # Khi buffer đủ N frame thì bắt đầu phát
                        if self.buffering and len(self.frameBuffer) >= self.bufferSize:
                            print(f"[Client] Buffer filled with {len(self.frameBuffer)} frames, start playback.")
                            self.buffering = False
                            # Bắt đầu đếm thời gian phát
                            self.startPlayTime = time.time()

                        # Nếu đã hết giai đoạn buffer thì hiển thị frame ngay
                        if not self.buffering and len(self.frameBuffer) > 0:
                            imageFile = self.frameBuffer.popleft()
                            self.updateMovie(imageFile)

            except:
                # Thread dừng khi pause/teardown
                if self.playEvent.isSet():
                    break
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    except:
                        pass
                    self.rtpSocket.close()
                    break

    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        with open(cachename, "wb") as file:
            file.write(data)
        return cachename

    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        try:
            photo = ImageTk.PhotoImage(Image.open(imageFile))
            self.label.configure(image=photo, height=288)
            self.label.image = photo
        except Exception as e:
            print(f"Error updating movie: {e}")

    def clearBuffer(self):
        """Xoá buffer cache (dùng khi pause/teardown)."""
        self.frameBuffer.clear()
        self.buffering = False

    # --------------------------------------------------------
    # RTSP over TCP
    # --------------------------------------------------------
    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
            print(f"Connected to server {self.serverAddr}:{self.serverPort}")
        except:
            tkMessageBox.showwarning(
                'Connection Failed',
                'Connection to \'%s\' failed.' % self.serverAddr)

    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""
        # Setup request
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply, daemon=True).start()
            self.rtspSeq += 1
            request = (
                f"SETUP {self.fileName} RTSP/1.0\n"
                f"CSeq: {self.rtspSeq}\n"
                f"Transport: RTP/UDP; client_port= {self.rtpPort}\n\n"
            )
            self.requestSent = self.SETUP

        # Play request
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = (
                f"PLAY {self.fileName} RTSP/1.0\n"
                f"CSeq: {self.rtspSeq}\n"
                f"Session: {self.sessionId}\n\n"
            )
            self.requestSent = self.PLAY

        # Pause request
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = (
                f"PAUSE {self.fileName} RTSP/1.0\n"
                f"CSeq: {self.rtspSeq}\n"
                f"Session: {self.sessionId}\n\n"
            )
            self.requestSent = self.PAUSE

        # Teardown request
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = (
                f"TEARDOWN {self.fileName} RTSP/1.0\n"
                f"CSeq: {self.rtspSeq}\n"
                f"Session: {self.sessionId}\n\n"
            )
            self.requestSent = self.TEARDOWN
        else:
            return

        self.rtspSocket.send(request.encode())
        print('\nData sent:\n' + request)

    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            reply = self.rtspSocket.recv(1024)

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))

            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                try:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                self.rtspSocket.close()
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        print(f"Received reply: {data}")
        lines = data.split('\n')

        if len(lines) < 2:
            return

        # Get status code
        status_line = lines[0].split(' ')
        if len(status_line) < 2:
            return
        status_code = int(status_line[1])

        # Get sequence number
        seq_num = None
        for line in lines:
            if line.startswith('CSeq:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    seq_num = int(parts[1])
                break

        if seq_num is None or seq_num != self.rtspSeq:
            return

        # Get session ID
        session_id = None
        for line in lines:
            if line.startswith('Session:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    session_id = int(parts[1])
                break

        if status_code == 200:
            if self.requestSent == self.SETUP:
                self.sessionId = session_id
                self.state = self.READY
                print("Setup OK - Opening RTP port")
                self.openRtpPort()
            elif self.requestSent == self.PLAY:
                self.state = self.PLAYING
                print("Play OK")
            elif self.requestSent == self.PAUSE:
                self.state = self.READY
                self.playEvent.set()
                self.clearBuffer()
                print("Pause OK")
            elif self.requestSent == self.TEARDOWN:
                self.state = self.INIT
                self.teardownAcked = 1
                self.playEvent.set()
                self.clearBuffer()
                # In ra thống kê cho report
                self.printStatistics()
                print("Teardown OK")

    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        try:
            self.rtpSocket.bind(('', self.rtpPort))
            print(f"RTP port {self.rtpPort} opened successfully")
        except:
            tkMessageBox.showwarning(
                'Unable to Bind',
                'Unable to bind PORT=%d' % self.rtpPort
            )

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:
            # Nếu người dùng không thoát thì tiếp tục play (nếu đang READY)
            if self.state == self.READY:
                self.playMovie()

    # --------------------------------------------------------
    # Statistics helpers (dùng cho report)
    # --------------------------------------------------------
    def printStatistics(self):
        if self.startPlayTime is None:
            return
        duration = time.time() - self.startPlayTime
        if duration <= 0:
            return

        print("\n========== STATISTICS ==========")
        print(f"Total frames received: {self.totalFramesReceived}")
        print(f"Lost frames (estimated): {self.lostFrames}")
        print(f"Loss rate: {self.lostFrames / max(1, self.totalFramesReceived + self.lostFrames) * 100:.2f}%")
        print(f"Playback time: {duration:.2f} s")
        print("================================\n")
