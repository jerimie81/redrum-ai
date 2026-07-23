class RedrumError(Exception):
    """Base class for all redrum-ai errors."""
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code

class ConfigurationError(RedrumError):
    """Raised when there is an issue with the configuration."""
    def __init__(self, message: str):
        super().__init__(message, exit_code=2)

class DatabaseError(RedrumError):
    """Raised when there is an issue interacting with the database."""
    def __init__(self, message: str):
        super().__init__(message, exit_code=3)

class ModelConnectionError(RedrumError):
    """Raised when unable to connect to Ollama or the model provider."""
    def __init__(self, message: str):
        super().__init__(message, exit_code=4)

class AgentExecutionError(RedrumError):
    """Raised when the agent loop fails unexpectedly."""
    def __init__(self, message: str):
        super().__init__(message, exit_code=5)
