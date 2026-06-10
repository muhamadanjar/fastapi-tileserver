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


class SessionNotFoundError(TileServerException):
    def __init__(self, upload_id: str):
        self.message = f"Upload session '{upload_id}' not found."
        super().__init__(self.message)


class SessionAlreadyCompleteError(TileServerException):
    def __init__(self, upload_id: str):
        self.message = f"Upload session '{upload_id}' is already complete."
        super().__init__(self.message)


class SessionExpiredError(TileServerException):
    def __init__(self, upload_id: str):
        self.message = f"Upload session '{upload_id}' has expired."
        super().__init__(self.message)


class ChunkUploadError(TileServerException):
    def __init__(self, detail: str):
        self.message = f"Chunk upload error: {detail}"
        super().__init__(self.message)


class LayerNotFoundError(TileServerException):
    def __init__(self, layer_id: str):
        self.message = f"Layer '{layer_id}' not found."
        super().__init__(self.message)


class LayerFieldsUnavailableError(TileServerException):
    def __init__(self, layer_type: str, reason: str = None):
        self.message = reason or f"Fields not available for layer type '{layer_type}'."
        super().__init__(self.message)
