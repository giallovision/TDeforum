"""
Folder DAT Callbacks

me - this DAT

dat - the DAT that is querying
info - the file or folder being queried
	name 				- the name with extension
	baseName 			- the name without extension
	path 				- the full path
	extension 			- the extension of the file
	folder 				- the path of the folder this is in
	isFolder			- true if a folder, false if a file
	depth 				- the depth of the file/folder from the root
	size 				- size of file or folder
	type 				- a description of the file type
	dateCreated 		- the file or folder creation date
	dateModified 		- the file or folder last modified date
	dateAccessed 		- the file or folder last accessed date
"""

from typing import List, Any

# Uncomment following two functions to add custom columns

# def onInitGetColumnNames(dat: folderDAT) -> List[str]:
# 	"""
# 	Called to initialize custom column names. Return a list of column names.
# 	"""
# 	return ['digits']

# def onGetValues(dat: folderDAT, info: FileEntry, row: int) -> List[Any]:
# 	"""
# 	Called to get custom column values. Return a list of values corresponding
#   to the custom columns defined in onInitGetColumnNames.
# 	"""
# 	return [dat.digits]

# control which folders are included

def onGetInclude(dat: folderDAT, info: FileEntry, row: int) -> bool:
	"""
	Called to determine if a file/folder should be included.
	
	Args:
		dat: The DAT that is querying
		info: The FileEntry being queried
		row: The table row index
		
	Returns:
		bool: True if the file/folder should be included
	"""
	return True

def onFound(dat: folderDAT, info: FileEntry, row: int):
	"""
	Called when a file/folder is found.
	
	Args:
		dat: The DAT that is querying
		info: The FileEntry that was found
		row: The table row index
	"""
	return
