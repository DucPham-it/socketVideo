from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from VideoStreamHD import VideoStreamHD
from VideoLoader import load_video
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	clientInfo = {}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			data = connSocket.recv(256)
			if data:
				print("Data received:\n" + data.decode("utf-8"))
				self.processRtspRequest(data.decode("utf-8"))
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		lines = data.split('\n')
		line1 = lines[0].split(' ')
		requestType = line1[0]
		
		# Get the media file name
		filename = line1[1]
		
		# Get the RTSP sequence number 
		seqLine = lines[1].split(' ')
		seqNum = seqLine[1] if len(seqLine) > 1 else "1"
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = load_video(filename)
					self.state = self.READY
				except IOError:
					print(f"File {filename} not found")
					self.replyRtsp(self.FILE_NOT_FOUND_404, seqNum)
					return
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Get the RTP/UDP port from the Transport line
				for line in lines:
					if 'Transport:' in line:
						parts = line.split(';')
						for part in parts:
							if 'client_port' in part:
								port_str = part.split('=')[1].strip()
								if '-' in port_str:
									self.clientInfo['rtpPort'] = port_str.split('-')[0]
								else:
									self.clientInfo['rtpPort'] = port_str
								break
						break
				
				print(f"RTP port: {self.clientInfo['rtpPort']}")
				self.replyRtsp(self.OK_200, seqNum)
		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				
				self.replyRtsp(self.OK_200, seqNum)
				
				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event()
				self.clientInfo['worker'] = threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				self.clientInfo['event'].set()
				self.replyRtsp(self.OK_200, seqNum)
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")
			if 'event' in self.clientInfo:
				self.clientInfo['event'].set()
			self.replyRtsp(self.OK_200, seqNum)
			if 'rtpSocket' in self.clientInfo:
				self.clientInfo['rtpSocket'].close()
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			self.clientInfo['event'].wait(0.03)  # ~33 FPS
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])
					packet = self.makeRtp(data, frameNumber)
					self.clientInfo['rtpSocket'].sendto(packet, (address, port))
					print(f"Sent frame {frameNumber} to {address}:{port}")
				except Exception as e:
					print(f"Connection Error: {e}")
			else:
				# End of stream, restart from beginning
				print("End of stream, resetting...")
				self.clientInfo['videoStream'].reset()

	def makeRtp(self, payload, frameNbr):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26  # MJPEG type
		seqnum = frameNbr
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			reply = f"RTSP/1.0 200 OK\nCSeq: {seq}\nSession: {self.clientInfo['session']}\n\n"
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
			print(f"Sent: {reply}")
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")