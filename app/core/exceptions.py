class TileServerException(Exception):
    """Base exception for the application."""
    pass

class UnsupportedFileFormatException(TileServerException):
    def __init__(self, filename: str):
        self.message = f"File format for '{filename}' is not supported. Use ZIP (for SHP), GeoJSON, or TIF."
        super().__init__(self.message)

class TilingProcessError(TileServerException):
    def __init__(self, detail: str):
        self.message = f"Error during tiling process: {detail}"
        super().__init__(self.message)

class FileSaveError(TileServerException):
    def __init__(self, detail: str):
        self.message = f"Failed to save file: {detail}"
        super().__init__(self.message)
