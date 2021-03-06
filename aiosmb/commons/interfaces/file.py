from pathlib import PureWindowsPath
from aiosmb.wintypes.access_mask import *
from aiosmb.protocol.smb2.commands import *


class SMBFile:
	def __init__(self):
		self.tree_id = None
		self.parent_dir = None
		self.fullpath = None
		self.unc_path = None
		self.share_path = None
		self.name = None
		self.size = None
		self.creation_time = None
		self.last_access_time = None
		self.last_write_time = None
		self.change_time = None
		self.allocation_size = None
		self.attributes = None
		self.file_id = None
		self.sid = None

		#internal
		self.__connection = None
		self.__position = 0
		self.is_pipe = False

	@staticmethod
	def from_uncpath(unc_path):
		unc = PureWindowsPath(unc_path)
		f = SMBFile()
		f.share_path = unc.drive
		f.fullpath = '\\'.join(unc.parts[1:])
		
		return f

	async def __read(self, size, offset):
		"""
		This is the main function for reading.
		It does not do buffering, so if more data is returned it will just discard it
		If less data is returned than requested it will do more reads until the requested size is reached.
		Do not call this directly as it could go in an infinite loop 
		"""
		if self.is_pipe == True:
			data, remaining = await self.__connection.read(self.tree_id, self.file_id, offset = offset, length = size)
			return data
		
		buffer = b''
		while len(buffer) <= size:
			data, remaining = await self.__connection.read(self.tree_id, self.file_id, offset = offset, length = size)
			buffer += data
			
		return buffer[:size]

	async def __write(self, data, offset = 0):
		remaining = len(data)
		total_bytes_written = 0
		
		while remaining != 0:
			bytes_written = await self.__connection.write(self.tree_id, self.file_id, data[offset:len(data)], offset = offset)
			total_bytes_written += bytes_written
			remaining -= bytes_written
			offset += bytes_written
		
		return total_bytes_written

	async def open(self, connection, mode = 'r'):
		self.__connection = connection
		self.mode = mode
		if 'p' in self.mode:
			self.is_pipe = True
		
		if not self.tree_id:
			tree_entry = await connection.tree_connect(self.share_path)
			self.tree_id = tree_entry.tree_id
		

		#then connect to file
		if 'r' in mode and 'w' in mode:
			raise ValueError('must have exactly one of read/write mode')
			
		if 'r' in mode:
			desired_access = FileAccessMask.FILE_READ_DATA | FileAccessMask.FILE_READ_ATTRIBUTES
			share_mode = ShareAccess.FILE_SHARE_READ
			create_options = CreateOptions.FILE_NON_DIRECTORY_FILE | CreateOptions.FILE_SYNCHRONOUS_IO_NONALERT 
			file_attrs = 0
			create_disposition = CreateDisposition.FILE_OPEN
			
			self.file_id, smb_reply = await connection.create(self.tree_id, self.fullpath, desired_access, share_mode, create_options, create_disposition, file_attrs, return_reply = True)
			self.size = smb_reply.EndofFile
			
		elif 'w' in mode:
			desired_access = FileAccessMask.GENERIC_READ | FileAccessMask.GENERIC_WRITE
			share_mode = ShareAccess.FILE_SHARE_READ | ShareAccess.FILE_SHARE_WRITE
			create_options = CreateOptions.FILE_NON_DIRECTORY_FILE | CreateOptions.FILE_SYNCHRONOUS_IO_NONALERT 
			file_attrs = 0
			create_disposition = CreateDisposition.FILE_OPEN_IF #FILE_OPEN ? might cause an issue?
			
			self.file_id, smb_reply = await connection.create(self.tree_id, self.fullpath, desired_access, share_mode, create_options, create_disposition, file_attrs, return_reply = True)
			self.size = smb_reply.EndofFile
			
		else:
			raise Exception('ONLY read and write is supported at the moment!')
		
		
	async def seek(self, offset, whence = 0):
		if whence == 0:
			if offset < 0:
				raise Exception('Offset must be > 0 when whence is 0')
			if offset > self.size:
				raise Exception('Seeking outside of file size!')
			self.__position = offset
		
		elif whence == 1:
			if 0 < self.__position + offset < self.size:
				self.__position += offset
			else:
				raise Exception('Seeking outside of file size!')
		
		elif whence == 2:
			if 0 < self.size + offset < self.size:
				self.__position = self.size + offset
			else:
				raise Exception('Seeking outside of file size!')
		
	async def read(self, size = -1):
		if size == 0:
			raise Exception('Cant read 0 bytes')
			
		elif size == -1:
			data = await self.__read(self.size - self.__position, self.__position)
			if self.is_pipe == False:
				self.__position += len(data)
			return data
			
		elif size > 0:
			if self.__position == self.size:
				return None
			if size + self.__position > self.size:
				size = self.size - self.__position
			data = await self.__read(size, self.__position)
			self.__position += len(data)
			return data
			
			
	async def write(self, data):
		count = await self.__write(data, self.__position)
		if self.is_pipe == False:
			self.__position += count
		
	async def flush(self):
		if 'r' in self.mode:
			return
		else:
			await self.__connection.flush(self.tree_id, self.file_id)
		
	async def close(self):
		await self.flush()
		await self.__connection.close(self.tree_id, self.file_id)
	
		
	def __str__(self):
		t = '===== FILE =====\r\n'
		for k in self.__dict__:
			if k.startswith('parent_'):
				continue
			t += '%s : %s\r\n' % (k, self.__dict__[k])
		
		return t