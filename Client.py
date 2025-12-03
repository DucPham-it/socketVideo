from tkinter import *
from tkinter import messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, os, time
from collections import deque

from RtpPacket import RtpPacket

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

        self.rtpSocket = None

        # Reassembly state
        self.currentFrameData = bytearray()
        self.frameCorrupted = False
        self.expectedSeq = None

        # Jitter buffer
        self.frameBuffer = deque()
        self.bufferSize = 30          # số frame buffer để mượt nhưng latency thấp
        self.playIntervalMs = 40      # ~25fps

        # Stats
        self.totalPackets = 0
        self.lostPackets = 0
        self.framesCompleted = 0
        self.framesDropped = 0
        self.bytesReceived = 0
        self.playStartTime = None

        self.playEvent = threading.Event()

        # Loop playback smooth
        self.master.after(self.playIntervalMs, self.playbackLoop)

        self.connectToServer()
        
    def createWidgets(self):
        """Build GUI."""
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)
        
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)
        
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)
        
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] =  self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)
        
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5)
    
    def setupMovie(self):
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
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
        if self.state == self.READY:
            self.playStartTime = time.time()
            self.playEvent.clear()
            threading.Thread(target=self.listenRtp, daemon=True).start()
            self.sendRtspRequest(self.PLAY)
    
    # -------------------------------------
    # RTP receive + reassembly
    # -------------------------------------
    def listenRtp(self):		
        """Listen for RTP packets, reassemble into frames."""
        while True:
            try:
                data = self.rtpSocket.recv(20480)
                if data:
                    self.bytesReceived += len(data)
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    
                    seq = rtpPacket.seqNum()
                    marker = rtpPacket.marker()
                    payload = rtpPacket.getPayload()

                    self.totalPackets += 1

                    # detect packet loss
                    if self.expectedSeq is None:
                        self.expectedSeq = (seq + 1) % 65536
                    else:
                        if seq != self.expectedSeq:
                            gap = (seq - self.expectedSeq) % 65536
                            if gap < 30000:  # bỏ trường hợp wrap-around lớn
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
                            # đẩy vào buffer
                            if len(self.frameBuffer) >= self.bufferSize:
                                self.frameBuffer.popleft()  # bỏ frame cũ để giữ latency thấp
                            self.frameBuffer.append(frameBytes)
                            self.framesCompleted += 1
                        else:
                            self.framesDropped += 1
                            print("Drop corrupted frame")

                        # reset for next frame
                        self.currentFrameData = bytearray()
                        self.frameCorrupted = False

            except:
                if self.playEvent.isSet(): 
                    break
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    except:
                        pass
                    self.rtpSocket.close()
                    break

    # -------------------------------------
    # Smooth playback loop
    # -------------------------------------
    def playbackLoop(self):
        """Được gọi định kỳ bằng Tkinter để hiển thị frame từ buffer."""
        if self.state == self.PLAYING and self.frameBuffer:
            frameBytes = self.frameBuffer.popleft()
            imageFile = self.writeFrame(frameBytes)
            self.updateMovie(imageFile)
        self.master.after(self.playIntervalMs, self.playbackLoop)
                    
    def writeFrame(self, data):
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        with open(cachename, "wb") as file:
            file.write(data)
        return cachename
    
    def updateMovie(self, imageFile):
        try:
            photo = ImageTk.PhotoImage(Image.open(imageFile))
            self.label.configure(image = photo, height=288) 
            self.label.image = photo
        except Exception as e:
            print(f"Error updating movie: {e}")
        
    # -------------------------------------
    # RTSP
    # -------------------------------------
    def connectToServer(self):
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
            print(f"Connected to server {self.serverAddr}:{self.serverPort}")
        except:
            tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
    
    def sendRtspRequest(self, requestCode):
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply, daemon=True).start()
            self.rtspSeq += 1
            request = f"SETUP {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nTransport: RTP/UDP; client_port= {self.rtpPort}\n\n"
            self.requestSent = self.SETUP
        
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = f"PLAY {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n\n"
            self.requestSent = self.PLAY
        
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = f"PAUSE {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n\n"
            self.requestSent = self.PAUSE
            
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = f"TEARDOWN {self.fileName} RTSP/1.0\nCSeq: {self.rtspSeq}\nSession: {self.sessionId}\n\n"
            self.requestSent = self.TEARDOWN
        else:
            return
        
        self.rtspSocket.send(request.encode())
        print('\nData sent:\n' + request)

    def recvRtspReply(self):
        while True:
            reply = self.rtspSocket.recv(1024)
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
        
        seq_num = None
        for line in lines:
            if line.startswith('CSeq:'):
                parts = line.split(' ')
                if len(parts) > 1:
                    seq_num = int(parts[1])
                break
        
        if seq_num is None or seq_num != self.rtspSeq:
            return
        
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
                print("Pause OK")
            elif self.requestSent == self.TEARDOWN:
                self.state = self.INIT
                self.teardownAcked = 1
                self.playEvent.set()
                print("Teardown OK")
                self.printStats()
    
    def openRtpPort(self):
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        try:
            self.rtpSocket.bind(('', self.rtpPort))
            print(f"RTP port {self.rtpPort} opened successfully")
        except:
            tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:
            self.playMovie()

    # -------------------------------------
    # Stats: frame loss + network usage
    # -------------------------------------
    def printStats(self):
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

        duration = 0
        if self.playStartTime is not None:
            duration = max(0.001, time.time() - self.playStartTime)
            bitrate = self.bytesReceived * 8 / duration / 1000  # kbps
            print(f"Playback time              : {duration:.2f} s")
            print(f"Approx. received bitrate   : {bitrate:.2f} kbps")
        print("==================================\n")
