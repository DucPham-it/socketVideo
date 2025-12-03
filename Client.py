from tkinter import *
from tkinter import messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, os, time
from collections import deque

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"


class Client:
    # States
    INIT = 0
    READY = 1
    PREBUFFERING = 2
    PLAYING = 3

    # RTSP commands
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

        self.state = self.INIT

        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0

        self.rtspSocket = None
        self.rtpSocket = None

        # Reassembly state
        self.currentFrameData = bytearray()
        self.frameCorrupted = False
        self.expectedSeq = None

        # Client-side caching / jitter buffer
        self.frameBuffer = deque()
        self.bufferSize = 60          # số frame cần prebuffer
        self.playIntervalMs = 16      # 60 fps

        # Stats (packet/frame)
        self.totalPackets = 0
        self.lostPackets = 0
        self.framesCompleted = 0      # frames đã cache được (TỔNG đã buffered)
        self.framesDropped = 0
        self.bytesReceived = 0
        self.playStartTime = None
        self.playedFrames = 0         # frames đã phát (để hiển thị)

        # Hybrid progress: byte-based
        self.totalFileBytes = None    # set nếu server gửi "FileSize: <bytes>"
        self.bytesBuffered = 0        # tổng byte của frame trong buffer
        self.bytesPlayed = 0          # tổng byte của frame đã play

        self.playEvent = threading.Event()

        # Smooth playback loop
        self.master.after(self.playIntervalMs, self.playbackLoop)

        self.connectToServer()

    # ----------------------------------------------------
    # GUI
    # ----------------------------------------------------
    def createWidgets(self):
        self.setup = Button(self.master, width=20, padx=3, pady=3,
                            text="Setup", command=self.setupMovie)
        self.setup.grid(row=2, column=0, padx=2, pady=2)

        self.start = Button(self.master, width=20, padx=3, pady=3,
                            text="Play", command=self.playMovie)
        self.start.grid(row=2, column=1, padx=2, pady=2)

        self.pause = Button(self.master, width=20, padx=3, pady=3,
                            text="Pause", command=self.pauseMovie)
        self.pause.grid(row=2, column=2, padx=2, pady=2)

        self.teardown = Button(self.master, width=20, padx=3, pady=3,
                               text="Teardown", command=self.exitClient)
        self.teardown.grid(row=2, column=3, padx=2, pady=2)

        # Video frame
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4,
                        sticky=W + E + N + S, padx=5, pady=5)

        # Status text
        self.status = Label(self.master, text="INIT", anchor="w")
        self.status.grid(row=1, column=0, columnspan=4, sticky=W, padx=5)

        #  label hiển thị thông số
        self.infoLabel = Label(
            self.master,
            text="Played: 0 | In-buffer: 0 |  TotalLive: 0 | Total buffered: 0",
            anchor="w",
            font=("Consolas", 10)
        )
        self.infoLabel.grid(row=3, column=0, columnspan=4, sticky=W, padx=5, pady=(0, 5))

    # ----------------------------------------------------
    # Button handlers
    # ----------------------------------------------------
    def setupMovie(self):
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)

    def exitClient(self):
        if self.state != self.INIT:
            self.sendRtspRequest(self.TEARDOWN)
        self.playEvent.set()
        self.master.destroy()
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except:
            pass

    def pauseMovie(self):
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)

    def playMovie(self):
        # Bấm Play khi đã SETUP xong (READY) -> bắt đầu PREBUFFERING
        if self.state == self.READY:
            self.playStartTime = None
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)

    # ----------------------------------------------------
    # RTP receive + reassembly → CACHE ONLY
    # ----------------------------------------------------
    def listenRtp(self):
        """Receive fragmented RTP → reassemble → push into CACHE."""
        while True:
            try:
                packet = self.rtpSocket.recv(65536)
            except socket.timeout:
                if self.teardownAcked:
                    break
                continue
            except Exception:
                break

            self.bytesReceived += len(packet)
            rtp = RtpPacket()
            try:
                rtp.decode(packet)
            except Exception as e:
                print(f"[RTP] decode error: {e}")
                continue

            seq = rtp.seqNum()
            payload = rtp.getPayload()
            marker = rtp.marker()
            self.totalPackets += 1

            # detect packet loss
            if self.expectedSeq is None:
                self.expectedSeq = (seq + 1) % 65536
            else:
                if seq != self.expectedSeq:
                    gap = (seq - self.expectedSeq) % 65536
                    if gap < 30000:
                        self.lostPackets += gap
                        self.frameCorrupted = True
                    self.expectedSeq = (seq + 1) % 65536
                else:
                    self.expectedSeq = (self.expectedSeq + 1) % 65536

            if not self.frameCorrupted:
                self.currentFrameData.extend(payload)

            if marker == 1:
                # end-of-frame
                if not self.frameCorrupted and self.currentFrameData:
                    frameBytes = bytes(self.currentFrameData)
                    # Bỏ frame cũ nhất nếu buffer quá đầy để giữ latency thấp
                    if len(self.frameBuffer) >= self.bufferSize:
                        old = self.frameBuffer.popleft()
                        self.bytesBuffered -= len(old)
                        if self.bytesBuffered < 0:
                            self.bytesBuffered = 0

                    self.frameBuffer.append(frameBytes)
                    self.bytesBuffered += len(frameBytes)
                    self.framesCompleted += 1
                    print(f"[CACHE] frame {self.framesCompleted} cached "
                          f"(buffer={len(self.frameBuffer)} frames, "
                          f"{self.bytesBuffered/1024:.1f} KB)")
                else:
                    self.framesDropped += 1
                    print("[CACHE] Drop corrupted frame")

                # Reset for next frame
                self.currentFrameData = bytearray()
                self.frameCorrupted = False

                # PREBUFFERING 
                if self.state == self.PREBUFFERING and len(self.frameBuffer) >= self.bufferSize:
                    print("[CACHE] Prebuffer OK → START PLAYING FROM BUFFER")
                    self.state = self.PLAYING
                    self.status.config(
                        text=f"PLAYING")
                    if self.playStartTime is None:
                        self.playStartTime = time.time()

                # update progress
                self.updateProgressBar()

    # ----------------------------------------------------
    # Smooth playback from buffer
    # ----------------------------------------------------
    def playbackLoop(self):
        if self.state == self.PLAYING and self.frameBuffer:
            frameBytes = self.frameBuffer.popleft()
            self.playedFrames += 1

            # Hybrid byte-based
            self.bytesPlayed += len(frameBytes)
            self.bytesBuffered -= len(frameBytes)
            if self.bytesBuffered < 0:
                self.bytesBuffered = 0

            imageFile = self.writeFrame(frameBytes)
            self.updateMovie(imageFile)
            self.status.config(
                text=f"PLAYING"
            )
            # update “progress” 
            self.updateProgressBar()

        self.master.after(self.playIntervalMs, self.playbackLoop)

    def writeFrame(self, data):
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        with open(cachename, "wb") as file:
            file.write(data)
        return cachename

    def updateMovie(self, imageFile):
        try:
            photo = ImageTk.PhotoImage(Image.open(imageFile))
            self.label.configure(image=photo, height=288)
            self.label.image = photo
        except Exception as e:
            print(f"Error updating movie: {e}")

    # ----------------------------------------------------
    # Progress bar
    # ----------------------------------------------------
    def updateProgressBar(self):
        """Hiển thị số liệu."""
        if not hasattr(self, "infoLabel") or self.infoLabel is None:
            return
        played = self.playedFrames
        inbuf = len(self.frameBuffer)
        totalLive = played + inbuf
        totalbuf = self.framesCompleted
        self.infoLabel.config(
            text=f"Played: {played}  |  In-buffer: {inbuf}  |  Total Live: {totalLive}  |  Total buffered: {totalbuf}"
        )

    # ----------------------------------------------------
    # RTSP
    # ----------------------------------------------------
    def connectToServer(self):
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
            print(f"Connected to server {self.serverAddr}:{self.serverPort}")
        except Exception:
            tkMessageBox.showwarning(
                'Connection Failed',
                'Connection to \'%s\' failed.' % self.serverAddr)

    def sendRtspRequest(self, requestCode):
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply, daemon=True).start()
            self.rtspSeq += 1
            request = (f"SETUP {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Transport: RTP/UDP; client_port= {self.rtpPort}\n\n")
            self.requestSent = self.SETUP

        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = (f"PLAY {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}\n\n")
            self.requestSent = self.PLAY

        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = (f"PAUSE {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}\n\n")
            self.requestSent = self.PAUSE

        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = (f"TEARDOWN {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}\n\n")
            self.requestSent = self.TEARDOWN
        else:
            return

        self.rtspSocket.send(request.encode())
        print('\nData sent:\n' + request)

    def recvRtspReply(self):
        while True:
            try:
                reply = self.rtspSocket.recv(1024)
            except Exception:
                break

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))
            if self.requestSent == self.TEARDOWN:
                try:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                self.rtspSocket.close()
                break

    def parseRtspReply(self, data):
        print(f"Received reply: {data}")
        lines = data.split('\n')
        if len(lines) < 2:
            return

        status_line = lines[0].split(' ')
        if len(status_line) < 2:
            return
        status_code = int(status_line[1])

        # CSeq
        seq_num = None
        for line in lines:
            if line.startswith('CSeq:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    try:
                        seq_num = int(parts[1])
                    except:
                        seq_num = None
                break

        if seq_num is None or seq_num != self.rtspSeq:
            return

        # Session
        session_id = None
        for line in lines:
            if line.startswith('Session:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    try:
                        session_id = int(parts[1])
                    except:
                        session_id = None
                break

        # Hybrid: đọc FileSize nếu có
        for line in lines:
            if line.startswith('FileSize:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    try:
                        self.totalFileBytes = int(parts[1])
                        print(f"[RTSP] Total file bytes = {self.totalFileBytes}")
                    except:
                        self.totalFileBytes = None
                break

        if status_code == 200:
            if self.requestSent == self.SETUP:
                self.sessionId = session_id
                self.state = self.READY
                self.status.config(text="READY (click PLAY to start prebuffering)")
                print("Setup OK - Opening RTP port")
                self.openRtpPort()

            elif self.requestSent == self.PLAY:
                # Bắt đầu prebuffer (nhận RTP vào buffer, chưa play)
                self.state = self.PREBUFFERING
                self.status.config(text="PREBUFFERING...")
                print("Play OK - start prebuffering")
                threading.Thread(target=self.listenRtp, daemon=True).start()

            elif self.requestSent == self.PAUSE:
                self.state = self.READY
                self.playEvent.set()
                self.status.config(text="READY (paused)")
                print("Pause OK")

            elif self.requestSent == self.TEARDOWN:
                self.state = self.INIT
                self.teardownAcked = 1
                self.playEvent.set()
                self.status.config(text="TEARDOWN")
                print("Teardown OK")
                self.printStats()

    def openRtpPort(self):
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        try:
            self.rtpSocket.bind(('', self.rtpPort))
            print(f"RTP port {self.rtpPort} opened successfully")
        except Exception:
            tkMessageBox.showwarning(
                'Unable to Bind',
                'Unable to bind PORT=%d' % self.rtpPort)

    def handler(self):
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:
            self.playMovie()

    # ----------------------------------------------------
    # Stats: frame loss + network usage
    # ----------------------------------------------------
    def printStats(self):
        # Nếu chưa stream gì thì khỏi in
        if self.totalPackets == 0 and self.framesCompleted == 0 and self.framesDropped == 0:
            return

        print("\n========== CLIENT STATS ==========")
        print(f"Total RTP packets received : {self.totalPackets}")
        print(f"Estimated packets lost     : {self.lostPackets}")
        if self.totalPackets + self.lostPackets > 0:
            plr = self.lostPackets / (self.totalPackets + self.lostPackets) * 100
            print(f"Packet loss rate           : {plr:.2f}%")

        print(f"Frames completed           : {self.framesCompleted}")
        print(f"Frames dropped             : {self.framesDropped}")
        if self.framesCompleted + self.framesDropped > 0:
            flr = self.framesDropped / (self.framesCompleted + self.framesDropped) * 100
            print(f"Frame loss rate            : {flr:.2f}%")

        if self.playStartTime is not None:
            duration = max(0.001, time.time() - self.playStartTime)
            bitrate = self.bytesReceived * 8 / duration / 1000  # kbps
            print(f"Playback time              : {duration:.2f} s")
            print(f"Approx. received bitrate   : {bitrate:.2f} kbps")
        print("==================================\n")
