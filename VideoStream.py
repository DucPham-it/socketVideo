class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		
	def nextFrame(self):
		"""Get next frame."""
		data = self.file.read(5) # Get the framelength from the first 5 bits
		if data: 
			try:
				framelength = int(data)
			except:
				print("Error: Invalid frame length")
				return None
							
			# Read the current frame
			data = self.file.read(framelength)
			self.frameNum += 1
			print(f"Read frame {self.frameNum}, length: {framelength}")
			return data
		return None
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	def reset(self):
		"""Reset stream to beginning."""
		self.file.seek(0)
		self.frameNum = 0